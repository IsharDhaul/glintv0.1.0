"""A full inputs frame from hand-written rows: financials → inputs → prices → metrics."""

from collections.abc import Mapping
from datetime import date
from typing import Any

import polars as pl

from glint.contracts.metrics import load_registry
from glint.financials.concepts import load_concepts
from glint.ingest.prices.stats import STAT_COLUMNS
from glint.metrics.compute import compute_metrics, prepare
from glint.metrics.params import Params
from glint.metrics.share_classes import ShareClassEntry
from tests.metrics.helpers import companies, fin

AS_OF_PRICES = date(2026, 10, 28)
AS_OF_FUNDAMENTALS = date(2026, 10, 29)
PARAMS = Params()


def stats(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """price_stats rows; unspecified stats are null, history_days defaults to 300."""
    out = [
        {"ticker": r["ticker"], "as_of": r.get("as_of", AS_OF_PRICES),
         **{c: r.get(c) for c in STAT_COLUMNS}, "history_days": r.get("history_days", 300)}
        for r in rows
    ]  # fmt: skip
    schema = {"ticker": pl.String, "as_of": pl.Date, "history_days": pl.Int32}
    schema |= dict.fromkeys(STAT_COLUMNS, pl.Float64)
    return pl.DataFrame(out, schema=schema)


def run(
    fin_rows: list[tuple[Any, ...]],
    company_rows: list[dict[str, Any]],
    price_rows: list[dict[str, Any]] = (),  # type: ignore[assignment]
    *,
    splits: pl.DataFrame | None = None,
    params: Params = PARAMS,
    share_classes: Mapping[str, ShareClassEntry] | None = None,
) -> pl.DataFrame:
    """Every registered metric for the given rows."""
    frame = prepare(
        companies(company_rows),
        fin(fin_rows),
        stats(list(price_rows)),
        splits,
        load_concepts(),
        as_of_fundamentals=AS_OF_FUNDAMENTALS,
        as_of_prices=AS_OF_PRICES,
        share_classes=share_classes or {},
        split_confirm_tolerance=params.split_confirm_tolerance,
    )
    return compute_metrics(frame, load_registry(), params)


def cell(out: pl.DataFrame, cik: str, metric_id: str) -> tuple[Any, str | None, str | None]:
    """(value, note code, note message) for one company and metric."""
    r = out.filter(pl.col("cik") == cik).row(0, named=True)
    return r[metric_id], r[f"{metric_id}__code"], r[f"{metric_id}__msg"]
