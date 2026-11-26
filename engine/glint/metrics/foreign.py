"""Foreign filers and US prices (§4.3 rule 13; user decision 2026-10-30).

`foreign_price_ok`: a foreign filer may have price-based metrics only if it reports in USD and its
listed shares are the ordinary shares. The data can't tell an ADR from an ordinary listing, so only
40-F filers qualify (Canadian issuers list their ordinary shares directly). Every 20-F filer stays
FOREIGN_PRICE_BASIS until F20 (FX + ADR ratios). `last_annual_form` is WT-01's provenance column
in companies.parquet; without it nobody qualifies.
"""

import polars as pl

ELIGIBLE_FORMS = ("40-F",)


def with_foreign_price_ok(frame: pl.DataFrame) -> pl.DataFrame:
    if "last_annual_form" not in frame.columns:
        return frame.with_columns(pl.lit(False).alias("foreign_price_ok"))
    ok = (
        pl.col("is_foreign_filer")
        & (pl.col("reporting_currency") == "USD")
        & pl.col("last_annual_form").is_in(ELIGIBLE_FORMS)
    )
    return frame.with_columns(ok.fill_null(False).alias("foreign_price_ok"))
