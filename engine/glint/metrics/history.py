"""`metric_history` (WT-06 step 6): drawer sparklines over every FY end (latest 10) and TTM end
(latest 12) the financials table keeps. Pure polars.

Each point uses the snapshot's formula at that period: flows at the period end (FY or TTM), balances
at the same date (FY-end instants for FY points, balance-sheet instants for TTM points), and the
balance about a year earlier (±window days) for averages and year-on-year changes. A point whose
inputs are missing, or whose metric is n/m for the company (§4.5), is left out: a sparkline gap,
never a filled value. Series ids are the metric ids the UI reads (as in the synthetic build).
"""

from datetime import date, timedelta
from typing import Any

import polars as pl

from glint.contracts.enums import Basis
from glint.contracts.metrics import MetricRegistry, load_registry
from glint.financials.concepts import load_concepts
from glint.ingest.prices.splits import SplitIndex
from glint.metrics.applicability import currency_sensitive, scope_expr
from glint.metrics.compute import SPLITS_SCHEMA
from glint.metrics.foreign import with_foreign_price_ok
from glint.metrics.inputs import FILING_FIELDS, filing_exprs
from glint.metrics.params import Params
from glint.metrics.prices import confirmed_splits, share_basis, share_split_ratios

HISTORY_METRICS = (
    "revenue_ttm",
    "gross_margin",
    "operating_margin",
    "fcf_margin",
    "share_count_change_yoy",
    "roic",
    "revenue_growth_yoy",
    "net_debt_to_ebitda",
)
FLOWS = [
    "revenue", "gross_profit", "operating_income", "fcf", "pretax_income", "income_tax", "ebitda",
]  # fmt: skip
INSTANTS = ["total_debt", "equity", "minority_interest", "cash", "st_investments"]
OPTIONAL = ["minority_interest", "st_investments"]  # untagged = none, unless tagged a year earlier
SHARES = "diluted_shares"
FILING = [f"{SHARES}_{f}" for f in FILING_FIELDS]  # inputs to `prices.share_basis`
SPLIT = "share_split"  # splits between the year-ago count's basis date and this count's


def _wide(rows: pl.DataFrame, items: list[str], prefix: str = "") -> pl.DataFrame:
    out = rows.select("cik", "period_end").unique()
    for item in items:
        r = rows.filter(pl.col("line_item") == item).select(
            "cik", "period_end", pl.col("value").alias(prefix + item)
        )
        out = out.join(r, on=["cik", "period_end"], how="left")
    return out


def _with_year_ago(
    frame: pl.DataFrame, source: pl.DataFrame, cols: list[str], window: int, years: int = 1
) -> pl.DataFrame:
    """Join `source` columns (as `<col>_<years>y`) at the end nearest `years` before each end."""
    target = frame.with_columns(
        pl.col("period_end").dt.offset_by(f"-{years}y").alias("_target")
    ).sort("_target")
    src = source.select(
        "cik",
        pl.col("period_end").alias("_target"),
        *(pl.col(c).alias(f"{c}_{years}y") for c in cols),
    ).sort("_target")
    return target.join_asof(
        src,
        on="_target",
        by="cik",
        strategy="nearest",
        tolerance=timedelta(days=window),
        check_sortedness=False,  # both sides sorted on _target above
    ).drop("_target")


def _basis_points(fin: pl.DataFrame, basis: Basis, window: int) -> pl.DataFrame:
    flows = _wide(fin.filter(pl.col("basis") == basis.value), FLOWS)
    inst_basis = Basis.FY if basis is Basis.FY else Basis.MRQ
    inst = _wide(fin.filter(pl.col("basis") == inst_basis.value), INSTANTS)
    share_basis = Basis.FY if basis is Basis.FY else Basis.Q
    shares = fin.filter(
        (pl.col("basis") == share_basis.value) & (pl.col("line_item") == SHARES)
    ).select(
        "cik", "period_end", pl.col("value").alias(SHARES),
        **{f"{SHARES}_{k}": e for k, e in filing_exprs().items()},
    )  # fmt: skip
    # Points at every flow end and every share-count end: the latest diluted count often has no
    # flow row at its date (a 16-week quarter, a gap in the year, a fiscal-year change), and the
    # snapshot's share_count_change_yoy is taken at that count's date. Other metrics are null there.
    ends = pl.concat([flows.select("cik", "period_end"), shares.select("cik", "period_end")])
    pts = ends.unique().join(flows, on=["cik", "period_end"], how="left")
    pts = pts.join(inst, on=["cik", "period_end"], how="left")
    pts = pts.join(shares, on=["cik", "period_end"], how="left")
    pts = _with_year_ago(pts, inst, INSTANTS, window)
    pts = _with_year_ago(pts, inst.select("cik", "period_end", *OPTIONAL), OPTIONAL, window, 2)
    pts = _with_year_ago(pts, shares, [SHARES, *FILING], window)
    pts = _with_year_ago(pts, flows.select("cik", "period_end", "revenue"), ["revenue"], window)
    return pts.with_columns(pl.lit(basis.value).alias("basis"))


def _formulas(p: Params) -> dict[str, pl.Expr]:
    rev = pl.when(pl.col("revenue") > 0).then(pl.col("revenue"))

    def part(c: str, sfx: str) -> pl.Expr:
        """As the snapshot: untagged counts as none, unless it was tagged a year earlier."""
        prior = pl.col(c + {"": "_1y", "_1y": "_2y"}[sfx])
        now = pl.col(c + sfx)
        return pl.when(now.is_null() & prior.is_null()).then(0.0).otherwise(now)

    def ic(sfx: str) -> pl.Expr:
        v = {c: part(c, sfx) if c in OPTIONAL else pl.col(c + sfx) for c in INSTANTS}
        return (
            v["total_debt"] + v["equity"] + v["minority_interest"] - v["cash"] - v["st_investments"]
        )

    lo, hi = p.tax_rate_clamp
    t = (
        pl.when(pl.col("pretax_income") <= 0)
        .then(p.statutory_tax_rate)
        .otherwise((pl.col("income_tax") / pl.col("pretax_income")).clip(lo, hi))
    )
    avg_ic = (ic("") + ic("_1y")) / 2
    prior = pl.col(f"{SHARES}_1y") * pl.col(SPLIT).fill_null(1.0)  # as `prices.split_adjusted`
    return {
        "revenue_ttm": pl.col("revenue"),
        "gross_margin": pl.col("gross_profit") / rev,
        "operating_margin": pl.col("operating_income") / rev,
        "fcf_margin": pl.col("fcf") / rev,
        "share_count_change_yoy": pl.col(SHARES) / pl.when(prior > 0).then(prior) - 1,
        "roic": pl.col("operating_income") * (1 - t) / pl.when(avg_ic > 0).then(avg_ic),
        "revenue_growth_yoy": pl.col("revenue")
        / pl.when(pl.col("revenue_1y") > 0).then(pl.col("revenue_1y"))
        - 1,
        "net_debt_to_ebitda": (pl.col("total_debt") - pl.col("cash") - part("st_investments", ""))
        / pl.when(pl.col("ebitda") > 0).then(pl.col("ebitda")),
    }


def build_history(
    companies: pl.DataFrame,
    fin: pl.DataFrame,
    p: Params,
    *,
    window: int,
    registry: MetricRegistry | None = None,
    splits: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Rows for `metric_history`: cik, metric_id, basis, period_end, value (never null).
    `splits` (WT-02's table) adjusts year-ago share counts for the `primary_ticker`'s splits."""
    registry = registry or load_registry()
    pts = pl.concat(
        [_basis_points(fin, Basis.FY, window), _basis_points(fin, Basis.TTM, window)],
        how="diagonal",
    )
    extra = ["last_annual_form"] if "last_annual_form" in companies.columns else []
    meta = with_foreign_price_ok(
        companies.select(
            "cik",
            "primary_ticker",
            "sector",
            "is_reit",
            "is_foreign_filer",
            "reporting_currency",
            *extra,
        ),
    )
    pts = pts.join(meta, on="cik", how="inner")
    table = splits if splits is not None else pl.DataFrame(schema=SPLITS_SCHEMA)
    tickers = companies.select("cik", "primary_ticker")
    tol = p.split_confirm_tolerance
    index = SplitIndex(confirmed_splits(table, fin, tickers, tol))
    n = len(FILING)
    bases: list[tuple[Any, date | None, date | None]] = []  # (ticker, year-ago basis, this one)
    for t, *r in pts.select("primary_ticker", *FILING, *(f"{c}_1y" for c in FILING)).iter_rows():
        now, ago = r[:n], r[n:]
        bases.append((t, share_basis(index, (t, *ago), tol), share_basis(index, (t, *now), tol)))
    pts = pts.with_columns(share_split_ratios(index, bases).alias(SPLIT))
    sensitive = currency_sensitive(registry, load_concepts())
    non_usd = pl.col("reporting_currency").is_not_null() & (pl.col("reporting_currency") != "USD")
    parts: list[pl.DataFrame] = []
    for mid, expr in _formulas(p).items():
        m = registry.get(mid)
        n_m = pl.any_horizontal(
            pl.lit(False), *(scope_expr(s) for s in (m.applicability.not_meaningful if m else []))
        )
        if mid in sensitive:
            n_m = n_m | non_usd
        parts.append(
            pts.select(
                "cik",
                pl.lit(mid).alias("metric_id"),
                "basis",
                "period_end",
                pl.when(n_m).then(None).otherwise(expr).alias("value"),
            )
        )
    out = pl.concat(parts).filter(pl.col("value").is_not_null() & pl.col("value").is_finite())
    keep = {"fy": p.history_fy_points, "ttm": p.history_ttm_points}
    out = out.sort("cik", "metric_id", "basis", "period_end").filter(
        pl.int_range(pl.len()).reverse().over("cik", "metric_id", "basis")
        < pl.col("basis").replace_strict(keep, return_dtype=pl.Int64)
    )
    return out
