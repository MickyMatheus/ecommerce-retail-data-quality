
from pathlib import Path
import pandas as pd

BUSINESS_COLUMNS = [
    "Invoice", "StockCode", "Description",
    "Quantity", "InvoiceDate", "Price",
    "Customer ID", "Country"
]


def load_raw_workbook(file_path):
    """Load both worksheets and preserve source traceability."""

    frames = []

    with pd.ExcelFile(file_path, engine="openpyxl") as book:
        sheet_names = book.sheet_names

        if len(sheet_names) != 2:
            raise ValueError("Expected exactly two worksheets")

        for sheet in sheet_names:
            frame = pd.read_excel(
                book,
                sheet_name=sheet,
                dtype={
                    "Invoice": "string",
                    "StockCode": "string",
                    "Customer ID": "string"
                }
            )

            if list(frame.columns) != BUSINESS_COLUMNS:
                raise ValueError(
                    f"Unexpected schema in worksheet: {sheet}"
                )

            frame["_source_sheet"] = sheet
            frame["_source_row"] = range(
                2, len(frame) + 2
            )

            frames.append(frame)

    raw = pd.concat(frames, ignore_index=True)

    return raw, sheet_names


def count_signatures(frame):
    """Count occurrences of every complete transaction signature."""

    return (
        frame.groupby(BUSINESS_COLUMNS, dropna=False)
        .size()
        .rename("frequency")
        .reset_index()
    )


def consolidate_workbook(file_path):
    """Consolidate only a fully validated historical overlap."""

    raw, sheets = load_raw_workbook(file_path)

    dates = pd.to_datetime(
        raw["InvoiceDate"],
        errors="coerce"
    )

    if dates.isna().any():
        raise ValueError("Invalid or missing invoice dates")

    first_mask = raw["_source_sheet"].eq(sheets[0])
    second_mask = raw["_source_sheet"].eq(sheets[1])

    first_dates = dates[first_mask]
    second_dates = dates[second_mask]

    overlap_start = max(
        first_dates.min(), second_dates.min()
    )

    overlap_end = min(
        first_dates.max(), second_dates.max()
    )

    excluded_mask = pd.Series(
        False, index=raw.index
    )

    shared_signatures = 0
    overlap_rows_a = 0
    overlap_rows_b = 0

    if overlap_start <= overlap_end:

        in_overlap = dates.between(
            overlap_start, overlap_end
        )

        a = raw.loc[
            first_mask & in_overlap,
            BUSINESS_COLUMNS
        ]

        b = raw.loc[
            second_mask & in_overlap,
            BUSINESS_COLUMNS
        ]

        overlap_rows_a = len(a)
        overlap_rows_b = len(b)

        # Compare complete signatures and their multiplicities
        signatures_a = count_signatures(a)
        signatures_b = count_signatures(b)

        comparison = signatures_a.merge(
            signatures_b,
            on=BUSINESS_COLUMNS,
            how="outer",
            suffixes=("_a", "_b"),
            indicator=True,
            validate="one_to_one"
        )

        identical_signatures = (
            comparison["_merge"].eq("both").all()
        )

        identical_frequencies = (
            comparison["frequency_a"]
            .eq(comparison["frequency_b"])
            .all()
        )

        if not (
            identical_signatures
            and identical_frequencies
            and overlap_rows_a == overlap_rows_b
        ):
            raise ValueError(
                "Overlapping worksheets are not identical. "
                "Automatic consolidation was stopped."
            )

        shared_signatures = len(comparison)

        # Retain the second worksheet's copy of the overlap
        excluded_mask = first_mask & in_overlap

    consolidated = (
        raw.loc[~excluded_mask]
        .reset_index(drop=True)
        .copy()
    )

    audit = {
        "Original_Records": len(raw),
        "Overlap_Rows_A": overlap_rows_a,
        "Overlap_Rows_B": overlap_rows_b,
        "Shared_Signatures": shared_signatures,
        "Excluded_Records": int(excluded_mask.sum()),
        "Consolidated_Records": len(consolidated)
    }

    if (
        audit["Original_Records"]
        - audit["Excluded_Records"]
        != audit["Consolidated_Records"]
    ):
        raise AssertionError("Record reconciliation failed")

    return consolidated, audit
