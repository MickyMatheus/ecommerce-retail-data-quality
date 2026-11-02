
import pandas as pd

REQUIRED_COLUMNS = [
    "Invoice", "StockCode", "Description",
    "Quantity", "InvoiceDate", "Price",
    "Customer ID", "Country",
    "_source_sheet", "_source_row"
]


def transform_transactions(df):
    """Apply non-destructive transaction transformations."""

    # 1. Validate required columns
    missing_columns = set(REQUIRED_COLUMNS) - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    result = df.copy()

    # 2. Standardize Description data type
    result["Description"] = (
        result["Description"].astype("string")
    )

    # 3. Prepare normalized expressions
    invoice = (
        result["Invoice"]
        .astype("string")
        .str.strip()
        .str.upper()
        .fillna("")
    )

    stock = (
        result["StockCode"]
        .astype("string")
        .str.strip()
        .str.upper()
        .fillna("")
    )

    qty = pd.to_numeric(
        result["Quantity"], errors="coerce"
    )

    price = pd.to_numeric(
        result["Price"], errors="coerce"
    )

    is_cancel = invoice.str.startswith("C")

    # 4. Define quality flags
    flags = {
        "DQ_Missing_Customer":
            result["Customer ID"].isna(),

        "DQ_Missing_Description":
            result["Description"].isna(),

        "DQ_Cancellation":
            is_cancel,

        "DQ_Negative_Qty_Without_C":
            qty.lt(0) & ~is_cancel,

        "DQ_C_With_Nonnegative_Qty":
            is_cancel & qty.ge(0),

        "DQ_Zero_Price":
            price.eq(0),

        "DQ_Negative_Price":
            price.lt(0),

        "DQ_Special_StockCode":
            stock.isin([
                "DOT", "POST", "ADJUST",
                "AMAZONFEE", "B", "M"
            ])
    }

    for name, mask in flags.items():
        result[name] = mask.fillna(False).astype(bool)

    result["DQ_Any_Flag"] = (
        result[list(flags)].any(axis=1)
    )

    # 5. Initialize transaction classification
    classification = pd.Series(
        "Other / review",
        index=result.index,
        dtype="string"
    )

    def assign(mask, category):
        available = classification.eq("Other / review")
        selected = available & mask.fillna(False)
        classification.loc[selected] = category

    # Priority-based business rules
    assign(
        is_cancel & qty.ge(0),
        "C prefix anomaly"
    )

    assign(is_cancel, "Cancellation")

    assign(
        qty.lt(0) & ~is_cancel,
        "Negative non-C / review"
    )

    assign(
        stock.isin(["B", "ADJUST"]),
        "Accounting adjustment"
    )

    assign(
        stock.isin(["DOT", "POST"]),
        "Postage / shipping"
    )

    assign(
        stock.eq("AMAZONFEE"),
        "Marketplace fee"
    )

    assign(
        stock.eq("M"),
        "Manual entry / review"
    )

    assign(
        qty.eq(0) | price.le(0)
        | result["Description"].isna(),
        "Zero-price or incomplete / review"
    )

    assign(
        qty.gt(0) & price.gt(0),
        "Positive line / sales candidate"
    )

    result["transaction_class"] = classification

    # 6. Calculate recorded amount
    # This is NOT confirmed net revenue.
    result["LineAmount_Recorded"] = qty * price

    return result
