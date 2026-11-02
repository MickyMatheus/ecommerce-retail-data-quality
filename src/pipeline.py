
import gc

from consolidation import consolidate_workbook
from transformations import transform_transactions
from description_recovery import add_description_suggestions
from outliers import detect_outliers
from product_anomalies import add_product_price_flags


def run_pipeline(source_file):
    """Run the complete reproducible data quality pipeline."""

    # 1. Historical consolidation
    consolidated, consolidation_audit = (
        consolidate_workbook(source_file)
    )

    expected_rows = len(consolidated)

    # 2. Transaction classification and quality flags
    transformed = transform_transactions(consolidated)

    assert len(transformed) == expected_rows

    del consolidated
    gc.collect()

    # 3. Description recovery suggestions
    enriched = add_description_suggestions(
        transformed,
        min_observations=5
    )

    assert len(enriched) == expected_rows

    del transformed
    gc.collect()

    # 4. Statistical outlier detection
    flagged, outlier_report = detect_outliers(enriched)

    assert len(flagged) == expected_rows

    del enriched
    gc.collect()

    # 5. Product-level price anomaly detection
    final_data, product_report = add_product_price_flags(
        flagged,
        min_observations=30
    )

    assert len(final_data) == expected_rows

    del flagged
    gc.collect()

    # 6. Final record reconciliation
    assert (
        consolidation_audit["Original_Records"]
        - consolidation_audit["Excluded_Records"]
        == len(final_data)
    )

    return (
        final_data,
        consolidation_audit,
        outlier_report,
        product_report
    )
