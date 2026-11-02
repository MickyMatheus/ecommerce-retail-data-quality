
import pandas as pd


def add_description_suggestions(df, min_observations=5):
    """
    Generate auditable description suggestions.
    Original values remain unchanged.
    """

    required = {"StockCode", "Description"}

    if not required.issubset(df.columns):
        raise ValueError("Missing required columns")

    if min_observations < 1:
        raise ValueError("min_observations must be >= 1")

    result = df.copy()

    # 1. Normalize identifiers for matching
    stock_key = (
        result["StockCode"]
        .astype("string")
        .str.strip()
        .str.upper()
        .replace("", pd.NA)
    )

    description_key = (
        result["Description"]
        .astype("string")
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
        .replace("", pd.NA)
    )

    # 2. Build reference from observed descriptions
    reference_data = pd.DataFrame({
        "StockCode_key": stock_key,
        "Description_key": description_key
    })

    reference = (
        reference_data
        .dropna(
            subset=["StockCode_key", "Description_key"]
        )
        .groupby("StockCode_key")["Description_key"]
        .agg(
            Known_Descriptions="size",
            Unique_Descriptions="nunique",
            Reference_Description="first"
        )
    )

    # 3. Match reference evidence
    known_count = (
        stock_key
        .map(reference["Known_Descriptions"])
        .fillna(0)
    )

    unique_count = (
        stock_key
        .map(reference["Unique_Descriptions"])
        .fillna(0)
    )

    missing_original = result["Description"].isna()

    eligible = (
        missing_original
        & known_count.ge(min_observations)
        & unique_count.eq(1)
    )

    # 4. Generate suggestions without overwriting
    suggestions = (
        stock_key
        .map(reference["Reference_Description"])
        .astype("string")
    )

    result["Description_Suggested"] = (
        suggestions.where(eligible, pd.NA)
    )

    # 5. Assign traceable recovery statuses
    status = pd.Series(
        "Not applicable",
        index=result.index,
        dtype="string"
    )

    status.loc[missing_original] = "No reference"

    status.loc[
        missing_original & unique_count.gt(1)
    ] = "Ambiguous descriptions"

    status.loc[
        missing_original
        & unique_count.eq(1)
        & known_count.lt(min_observations)
    ] = "Insufficient evidence"

    status.loc[eligible] = "Suggested / pending review"

    result["Description_Recovery_Status"] = status

    return result
