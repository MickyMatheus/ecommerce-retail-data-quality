
"""Command-line entry point for Online Retail II data quality pipeline."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Reproducible Online Retail II data quality pipeline"
    )

    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the original Excel workbook"
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/processed/online_retail_quality_flagged_v2.parquet",
        help="Destination Parquet file"
    )

    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input file not found: {args.input}")

    final, audit, outliers, products = run_pipeline(
        args.input
    )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    final.to_parquet(
        args.output,
        index=False,
        engine="pyarrow"
    )

    print("\nPIPELINE EXECUTED SUCCESSFULLY")
    print("Original records:", audit["Original_Records"])
    print("Excluded replicated records:", audit["Excluded_Records"])
    print("Final records:", len(final))
    print("Final columns:", len(final.columns))
    print("Output:", args.output)

    print("\nSTATISTICAL OUTLIER REPORT")
    print(outliers.to_string(index=False))

    print("\nPRODUCT ANOMALY REPORT")
    print(products.to_string(index=False))


if __name__ == "__main__":
    main()
