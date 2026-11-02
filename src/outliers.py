
import numpy as np
import pandas as pd


def detect_outliers(df, mad_threshold=3.5):
    """Flag statistical outliers without modifying source values."""

    required = {"Invoice", "Quantity", "Price"}

    if not required.issubset(df.columns):
        raise ValueError("Missing required columns")

    if mad_threshold <= 0:
        raise ValueError("mad_threshold must be positive")

    result = df.copy()

    invoice = (
        result["Invoice"].astype("string")
        .str.strip().str.upper().fillna("")
    )

    qty = pd.to_numeric(
        result["Quantity"], errors="coerce"
    )
    price = pd.to_numeric(
        result["Price"], errors="coerce"
    )

    # Do not silently accept invalid numeric values
    if (
        (qty.isna() & result["Quantity"].notna()).any()
        or (price.isna() & result["Price"].notna()).any()
    ):
        raise ValueError("Invalid numeric transaction values")

    # Match the original exploratory population
    eligible = (
        qty.gt(0)
        & price.gt(0)
        & ~invoice.str.startswith("C")
    ).fillna(False)

    result["Outlier_Eligible"] = eligible

    variables = {
        "Quantity": qty,
        "Price": price,
        "LineAmount": qty * price
    }

    report_rows = []

    for name, full_values in variables.items():

        values = full_values.loc[eligible]

        # IQR on original scale
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        iqr_flag = (
            (values < lower) | (values > upper)
        )

        # Modified Z-Score on log1p scale
        log_values = np.log1p(values)

        median = log_values.median()
        mad = (log_values - median).abs().median()

        if np.isclose(mad, 0):
            raise ValueError(
                f"MAD is zero for {name}; review required"
            )

        modified_z = (
            0.6745 * (log_values - median) / mad
        )

        mad_flag = modified_z.abs() > mad_threshold

        # Nullable flags: NA means outside analytical scope
        iqr_full = pd.Series(
            pd.NA, index=result.index, dtype="boolean"
        )
        mad_full = pd.Series(
            pd.NA, index=result.index, dtype="boolean"
        )

        iqr_full.loc[eligible] = iqr_flag
        mad_full.loc[eligible] = mad_flag

        result[f"Outlier_IQR_{name}"] = iqr_full
        result[f"Outlier_MAD_{name}"] = mad_full

        report_rows.append({
            "Variable": name,
            "Eligible_Records": len(values),
            "IQR_Lower": lower,
            "IQR_Upper": upper,
            "MAD_Log": mad,
            "IQR_Outliers": int(iqr_flag.sum()),
            "MAD_Outliers": int(mad_flag.sum()),
            "Both_Methods": int(
                (iqr_flag & mad_flag).sum()
            )
        })

    # Combined IQR alert
    iqr_columns = [
        f"Outlier_IQR_{name}"
        for name in variables
    ]

    result["Outlier_IQR_Any"] = (
        result[iqr_columns].any(axis=1).astype("boolean")
    )

    result.loc[
        ~eligible, "Outlier_IQR_Any"
    ] = pd.NA

    report = pd.DataFrame(report_rows)

    return result, report
