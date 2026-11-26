"""Data quality (§2.4, §4.6). `flag_count` is filled after the flag engine runs."""

import polars as pl

from glint.contracts.enums import LineItem as L
from glint.contracts.enums import NoteCode, PeriodKind
from glint.financials.concepts import load_concepts
from glint.metrics.core import Guard, MetricExprs, metric, result
from glint.metrics.inputs import MRQ, TTM, col_name
from glint.metrics.params import Params
from glint.metrics.prices import shares_stale


def core_present() -> list[pl.Expr]:
    """One boolean per §4.6 core item: present at the common TTM end / MRQ date (the share
    count at its own date unless stale), as in WT-03's coverage report."""
    concepts = load_concepts()
    out: list[pl.Expr] = []
    for i in concepts.core:
        if i is L.SHARES_OUTSTANDING:
            out.append(
                pl.col("shares_outstanding__now").is_not_null() & ~shares_stale().fill_null(False)
            )
        elif concepts[i].kind is PeriodKind.DURATION:
            out.append(pl.col(col_name(i, TTM)).is_not_null())
        else:
            out.append(pl.col(col_name(i, MRQ)).is_not_null())
    return out


@metric("data_coverage")
def data_coverage(p: Params) -> MetricExprs:
    present = core_present()
    share = pl.sum_horizontal(*(e.cast(pl.Int32) for e in present)) / len(present)
    return result(share, [])


@metric("days_since_filing")
def days_since_filing(p: Params) -> MetricExprs:
    latest = pl.max_horizontal("last_annual_date", "last_quarterly_date")
    days = (pl.col("as_of_fundamentals") - latest).dt.total_days()
    none = Guard(
        latest.is_null(),
        NoteCode.MISSING_INPUT,
        "days_since_filing: no 10-K, 10-Q, 20-F or 40-F on file",
    )
    return result(days, [], [none])


@metric("flag_count")
def flag_count(p: Params) -> MetricExprs:
    """Raised flags (computed after the flag engine has run on the other metrics)."""
    return result(pl.col("n_flags").cast(pl.Float64), [])
