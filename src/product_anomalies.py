
import pandas as pd


def add_product_price_flags(df, min_observations=30):
    """Assess price anomalies without changing source values."""

    required = {
        "StockCode", "Description", "Price",
        "transaction_class"
    }

    if not required.issubset(df.columns):
        raise ValueError("Missing required columns")

    if min_observations < 1:
        raise ValueError("min_observations must be positive")

    result = df.copy()

    stock = (
        result["StockCode"]
        .astype("string").str.strip().str.upper()
        .replace("", pd.NA)
    )

    price = pd.to_numeric(result["Price"], errors="coerce")

    population = (
        result["transaction_class"].eq(
            "Positive line / sales candidate"
        ).fillna(False)
        & stock.notna()
        & price.gt(0)
    )

    work = pd.DataFrame({
        "StockKey": stock.loc[population],
        "Price": price.loc[population],
        "DescriptionKey": (
            result.loc[population, "Description"]
            .astype("string").str.strip().str.upper()
            .str.replace(r"\s+", " ", regex=True)
        )
    })

    groups = work.groupby("StockKey")

    work["ReferenceCount"] = groups["Price"].transform("size")
    work["MedianPrice"] = groups["Price"].transform("median")
    work["DescriptionVariants"] = (
        groups["DescriptionKey"].transform("nunique")
    )

    comparable = (
        work["ReferenceCount"].ge(min_observations)
        & work["MedianPrice"].gt(0)
    )

    work["PriceRatio"] = (
        work["Price"] / work["MedianPrice"]
    )

    anomaly = (
        work["PriceRatio"].ge(3)
        | work["PriceRatio"].le(1 / 3)
    )

    # Missing flags indicate rows outside evaluation scope
    result["Product_Price_Anomaly"] = pd.Series(
        pd.NA, index=result.index, dtype="boolean"
    )
    result["Product_Price_Ratio"] = pd.Series(
        pd.NA, index=result.index, dtype="Float64"
    )
    result["Product_Identity_Review"] = pd.Series(
        pd.NA, index=result.index, dtype="boolean"
    )

    eligible_index = work.index[comparable]

    result.loc[
        eligible_index, "Product_Price_Anomaly"
    ] = anomaly.loc[eligible_index].astype(bool)

    result.loc[
        eligible_index, "Product_Price_Ratio"
    ] = work.loc[eligible_index, "PriceRatio"]

    result.loc[
        eligible_index, "Product_Identity_Review"
    ] = work.loc[
        eligible_index, "DescriptionVariants"
    ].gt(1).astype(bool)

    summary = pd.DataFrame({
        "Metric": [
            "Sales candidate lines",
            "Eligible product price comparisons",
            "Potential product price anomalies",
            "Flagged prices with multiple descriptions",
            "Product identity review lines"
        ],
        "Records": [
            int(population.sum()),
            int(comparable.sum()),
            int(anomaly.loc[comparable].sum()),
            int(
                (
                    anomaly
                    & comparable
                    & work["DescriptionVariants"].gt(1)
                ).sum()
            ),
            int(
                work.loc[
                    comparable, "DescriptionVariants"
                ].gt(1).sum()
            )
        ]
    })

    return result, summary
