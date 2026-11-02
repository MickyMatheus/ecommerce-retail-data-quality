
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from consolidation import consolidate_workbook
from transformations import transform_transactions
from description_recovery import add_description_suggestions
from outliers import detect_outliers


# --------------------------------------------------
# Helper: small synthetic transaction
# --------------------------------------------------

def make_row(invoice, date, quantity=2, price=5.0,
             stock="P001"):

    return {
        "Invoice": invoice,
        "StockCode": stock,
        "Description": "Test Product",
        "Quantity": quantity,
        "InvoiceDate": pd.Timestamp(date),
        "Price": price,
        "Customer ID": "10001",
        "Country": "United Kingdom"
    }


def make_test_workbook(tmp_path, conflict=False):

    # Two identical records in the overlapping period
    a = pd.DataFrame([
        make_row("100", "2010-11-30"),
        make_row("200", "2010-12-01"),
        make_row("200", "2010-12-01")
    ])

    b = pd.DataFrame([
        make_row("200", "2010-12-01"),
        make_row("200", "2010-12-01"),
        make_row("300", "2010-12-02")
    ])

    if conflict:
        b.loc[1, "Price"] = 99.0

    path = tmp_path / "test_retail.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        a.to_excel(
            writer, sheet_name="Year A", index=False
        )
        b.to_excel(
            writer, sheet_name="Year B", index=False
        )

    return path


# --------------------------------------------------
# TEST 1: Historical consolidation
# --------------------------------------------------

def test_consolidation_preserves_internal_repeats(tmp_path):

    path = make_test_workbook(tmp_path)

    result, audit = consolidate_workbook(path)

    assert audit["Original_Records"] == 6
    assert audit["Excluded_Records"] == 2
    assert audit["Consolidated_Records"] == 4

    # Two identical lines remain in Year B
    assert result["Invoice"].eq("200").sum() == 2


# --------------------------------------------------
# TEST 2: Reject inconsistent historical overlap
# --------------------------------------------------

def test_consolidation_rejects_conflicting_overlap(tmp_path):

    path = make_test_workbook(
        tmp_path, conflict=True
    )

    with pytest.raises(ValueError):
        consolidate_workbook(path)


# --------------------------------------------------
# TEST 3: Classification and value preservation
# --------------------------------------------------

def test_transaction_classification():

    df = pd.DataFrame([
        make_row("100", "2010-12-01", 3, 5.0),
        make_row("C101", "2010-12-01", -2, 5.0),
        make_row("102", "2010-12-01", 1, 7.0, "POST"),
        make_row("103", "2010-12-01", -1, 0.0)
    ])

    df["_source_sheet"] = "Year A"
    df["_source_row"] = range(2, 6)

    result = transform_transactions(df)

    assert len(result) == 4

    expected = [
        "Positive line / sales candidate",
        "Cancellation",
        "Postage / shipping",
        "Negative non-C / review"
    ]

    assert result["transaction_class"].tolist() == expected

    # Original numerical values must not change
    pd.testing.assert_series_equal(
        result["Quantity"], df["Quantity"]
    )

    pd.testing.assert_series_equal(
        result["Price"], df["Price"]
    )

    assert result.loc[1, "DQ_Cancellation"]
    assert result.loc[3, "DQ_Negative_Qty_Without_C"]


# --------------------------------------------------
# TEST 4: Reject an invalid schema
# --------------------------------------------------

def test_transformation_rejects_missing_columns():

    invalid = pd.DataFrame({
        "Invoice": ["100"],
        "Quantity": [2]
    })

    with pytest.raises(ValueError):
        transform_transactions(invalid)


# --------------------------------------------------
# TEST 5: Description recovery rules
# --------------------------------------------------

def test_description_recovery_rules():

    rows = (
        [{"StockCode": "A", "Description": "RED HAT"}] * 5
        + [{"StockCode": "A", "Description": None}]
        + [{"StockCode": "B", "Description": "BLUE HAT"}] * 5
        + [{"StockCode": "B", "Description": "GREEN HAT"}]
        + [{"StockCode": "B", "Description": None}]
        + [{"StockCode": "C", "Description": "SCARF"}]
        + [{"StockCode": "C", "Description": None}]
        + [{"StockCode": "D", "Description": None}]
    )

    df = pd.DataFrame(rows)

    result = add_description_suggestions(
        df, min_observations=5
    )

    missing = result.loc[
        result["Description"].isna()
    ].set_index("StockCode")

    assert missing.loc["A", "Description_Suggested"] == "RED HAT"

    assert (
        missing.loc["B", "Description_Recovery_Status"]
        == "Ambiguous descriptions"
    )

    assert (
        missing.loc["C", "Description_Recovery_Status"]
        == "Insufficient evidence"
    )

    assert (
        missing.loc["D", "Description_Recovery_Status"]
        == "No reference"
    )

    assert result["Description"].equals(df["Description"])


# --------------------------------------------------
# TEST 6: Statistical outlier detection
# --------------------------------------------------

def test_outlier_detection_and_scope():

    quantities = list(range(1, 10)) + [1000, -2, 3]
    prices = list(range(1, 10)) + [200, 5, 0]

    invoices = (
        [str(i) for i in range(10)]
        + ["C100", "101"]
    )

    df = pd.DataFrame({
        "Invoice": invoices,
        "Quantity": quantities,
        "Price": prices
    })

    result, report = detect_outliers(df)

    # Ten eligible observations
    assert result["Outlier_Eligible"].sum() == 10

    # Extreme positive observation must be flagged
    assert bool(result.loc[9, "Outlier_IQR_Quantity"])
    assert bool(result.loc[9, "Outlier_IQR_Price"])

    # Cancellation and zero-price record not evaluated
    assert pd.isna(result.loc[10, "Outlier_IQR_Any"])
    assert pd.isna(result.loc[11, "Outlier_IQR_Any"])

    # No numerical modification
    pd.testing.assert_series_equal(
        result["Quantity"], df["Quantity"]
    )

    pd.testing.assert_series_equal(
        result["Price"], df["Price"]
    )

    assert len(report) == 3

from product_anomalies import add_product_price_flags
from pipeline import run_pipeline


# TEST 7: Product-level anomalies and business scope

def test_product_price_anomalies():

    rows = []

    # Product A: median price 10, one extreme price
    for p in [10, 10, 10, 10, 10, 100]:
        rows.append({
            "StockCode": "A",
            "Description": (
                "ALPHA PACK" if p == 100 else "ALPHA"
            ),
            "Price": float(p),
            "transaction_class": "Positive line / sales candidate"
        })

    # Product B: median 5, one unusually low price
    for p in [5, 5, 5, 5, 0.5]:
        rows.append({
            "StockCode": "B",
            "Description": "BETA",
            "Price": float(p),
            "transaction_class": "Positive line / sales candidate"
        })

    # Special transaction: must be excluded
    rows.append({
        "StockCode": "DOT",
        "Description": "DOTCOM POSTAGE",
        "Price": 2000.0,
        "transaction_class": "Postage / shipping"
    })

    # Same code A, but special operation
    rows.append({
        "StockCode": "A",
        "Description": "ALPHA",
        "Price": 2000.0,
        "transaction_class": "Manual entry / review"
    })

    # Insufficient sample size
    rows.append({
        "StockCode": "C",
        "Description": "GAMMA",
        "Price": 500.0,
        "transaction_class": "Positive line / sales candidate"
    })

    df = pd.DataFrame(rows)

    result, summary = add_product_price_flags(
        df, min_observations=5
    )

    assert int(result["Product_Price_Anomaly"].notna().sum()) == 11
    assert int(result["Product_Price_Anomaly"].sum()) == 2

    assert bool(result.loc[5, "Product_Price_Anomaly"])
    assert bool(result.loc[10, "Product_Price_Anomaly"])

    assert result.loc[5, "Product_Price_Ratio"] == 10
    assert result.loc[10, "Product_Price_Ratio"] == 0.1

    assert int(result["Product_Identity_Review"].sum()) == 6

    assert result.loc[11:, "Product_Price_Anomaly"].isna().all()

    pd.testing.assert_frame_equal(result[df.columns], df)


# TEST 8: Invalid product anomaly inputs

def test_product_anomalies_reject_invalid_inputs():

    with pytest.raises(ValueError):
        add_product_price_flags(
            pd.DataFrame({"StockCode": ["A"]})
        )

    valid = pd.DataFrame({
        "StockCode": ["A"],
        "Description": ["PRODUCT A"],
        "Price": [10.0],
        "transaction_class": [
            "Positive line / sales candidate"
        ]
    })

    with pytest.raises(ValueError):
        add_product_price_flags(
            valid, min_observations=0
        )


# TEST 9: Full pipeline with synthetic Excel data

def test_full_pipeline_end_to_end(tmp_path):

    first_rows = [
        make_row(str(i), f"2010-11-{27+i}", i, float(i))
        for i in range(1, 4)
    ]

    shared = [
        make_row("4", "2010-12-01", 4, 4.0),
        make_row("5", "2010-12-02", 5, 5.0)
    ]

    last_rows = [
        make_row(str(i), f"2010-12-0{i-3}", i, float(i))
        for i in range(6, 10)
    ]

    path = tmp_path / "complete_pipeline_test.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(first_rows + shared).to_excel(
            writer, sheet_name="Year A", index=False
        )
        pd.DataFrame(shared + last_rows).to_excel(
            writer, sheet_name="Year B", index=False
        )

    final, audit, outliers, products = run_pipeline(path)

    assert audit["Original_Records"] == 11
    assert audit["Excluded_Records"] == 2

    assert final.shape == (9, 34)

    assert final["Description"].isna().sum() == 0
    assert int(final["Outlier_Eligible"].sum()) == 9

    # Product sample size is below the default minimum
    assert final["Product_Price_Anomaly"].isna().all()

    assert (final["LineAmount_Recorded"] == (
        final["Quantity"] * final["Price"]
    )).all()

    assert len(outliers) == 3
    assert not products.empty
