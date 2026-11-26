"""Tiny hand-built frames for metric tests."""

from datetime import date
from typing import Any

import polars as pl

from glint.financials.store import SCHEMA as FIN_SCHEMA


def fin(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    """financials rows from (cik, line_item, basis, period_end, value[, derived[, first_filed
    value[, filed[, first_filed_date[, source_tag]]]]]); filed defaults to period_end,
    first_filed_date to filed, source_tag to `Tag<line_item>`."""
    out: list[dict[str, Any]] = []
    for r in rows:
        cik, item, basis, end, value, *rest = r
        filed = rest[2] if len(rest) > 2 else end
        out.append({
            "cik": cik, "line_item": item, "basis": basis, "period_end": end,
            "period_start": None, "value": float(value), "unit": "USD",
            "source_tag": rest[4] if len(rest) > 4 else f"Tag{item}", "source_accn": "0000000000-26-000001",
            "filed": filed, "first_filed_date": rest[3] if len(rest) > 3 else filed,
            "first_filed_value": float(value if len(rest) < 2 or rest[1] is None else rest[1]),
            "derived": bool(rest[0]) if rest else False,
        })  # fmt: skip
    return pl.DataFrame(out, schema=FIN_SCHEMA)


def companies(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """companies rows; anything not given gets a domestic operating default."""
    defaults: dict[str, Any] = {
        "name": "Test Co", "tickers": ["TST"], "primary_ticker": "TST", "exchange": "NYSE",
        "sector": "Industrials", "kind": "operating", "is_foreign_filer": False,
        "is_reit": False, "has_facts": True, "taxonomy": "us-gaap", "reporting_currency": "USD",
        "last_annual_date": date(2026, 2, 20), "last_quarterly_date": date(2026, 8, 1),
        "nt_filing_12m": False, "fy_end_changed": False,
    }  # fmt: skip
    return pl.DataFrame([{**defaults, **r} for r in rows]).with_columns(
        pl.col("tickers").cast(pl.List(pl.String)),
        pl.col("primary_ticker").cast(pl.String),
        pl.col("exchange").cast(pl.String),
    )
