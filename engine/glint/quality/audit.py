"""`glint audit` (WT-06 step 11, §4.6): outliers for a person to review. Never changes a value.

- **Rules** (thresholds.yaml `audit`): gross margin outside its range, market cap above the cap,
  revenue TTM ≠ FY at a fiscal year end, equity jumps, share-count jumps without a split. Each hit
  carries the inputs behind it.
- **Distribution** per metric: n, p1/p5/p50/p95/p99, null share and null share by reason.
- **Extremes** per metric: the most extreme values, so tiny denominators show up (never clipped).
- **Null rates** for a group of companies (domestic non-financials for the acceptance record).
"""

from typing import Any

import polars as pl

from glint.contracts.enums import NON_NULL_NOTE_CODES, NoteCode
from glint.ingest.prices.splits import SplitIndex
from glint.metrics.compute import SPLITS_SCHEMA

QUANTILES = (0.01, 0.05, 0.5, 0.95, 0.99)
NULL_CODES = [c.value for c in NoteCode if c not in NON_NULL_NOTE_CODES]
ID_COLS = ["cik", "primary_ticker", "name", "sector"]


def _top(
    frame: pl.DataFrame, cond: pl.Expr, severity: pl.Expr, cols: list[str], top: int
) -> pl.DataFrame:
    return (
        frame.filter(cond.fill_null(False))
        .with_columns(severity.alias("severity"))
        .sort(["severity", "cik"], descending=[True, False])
        .select(*ID_COLS, *cols, "severity")
        .head(top)
    )


def rule_outliers(
    frame: pl.DataFrame,
    fin: pl.DataFrame,
    splits: pl.DataFrame | None,
    cfg: dict[str, Any],
    *,
    top: int,
) -> dict[str, pl.DataFrame]:
    lo, hi = cfg["gross_margin_range"]
    gm = pl.col("gross_margin")
    out = {
        "gross_margin_range": _top(
            frame, (gm < lo) | (gm > hi), (gm - gm.clip(lo, hi)).abs(),
            ["gross_margin", "gross_profit__ttm", "revenue__ttm", "cost_of_revenue__ttm"], top,
        ),
        "market_cap_max": _top(
            frame, pl.col("market_cap") > float(cfg["market_cap_max_usd"]), pl.col("market_cap"),
            ["market_cap", "px__close", "shares_outstanding__now", "shares_as_of", "split_ratio"],
            top,
        ),
    }  # fmt: skip
    ratio = (pl.col("equity__mrq") / pl.col("equity__mrq_1y")).abs()
    out["equity_jump"] = _top(
        frame,
        (ratio > cfg["equity_jump_max_ratio"]) | (ratio < 1 / cfg["equity_jump_max_ratio"]),
        pl.max_horizontal(ratio, 1 / ratio),
        ["equity__mrq", "equity__mrq_1y", "mrq_end", "mrq_1y_end"],
        top,
    )
    index = SplitIndex(splits if splits is not None else pl.DataFrame(schema=SPLITS_SCHEMA))
    sh = frame.with_columns(
        (pl.col("diluted_shares__q") / pl.col("diluted_shares__q_1y")).alias("share_ratio"),
        pl.Series(
            "split_in_window",
            [
                t is not None and a is not None and b is not None
                and index.split_between(t, a, b) is not None
                for t, a, b in frame.select("primary_ticker", "q_1y_end", "q_end").iter_rows()
            ],
        ),
    )  # fmt: skip
    r = pl.col("share_ratio")
    lim = cfg["share_count_jump_max_ratio"]
    out["share_count_jump"] = _top(
        sh, ((r > lim) | (r < 1 / lim)) & r.is_not_nan() & ~pl.col("split_in_window"),
        pl.max_horizontal(r, 1 / r),
        ["diluted_shares__q", "diluted_shares__q_1y", "q_end", "q_1y_end"], top,
    )  # fmt: skip
    pair = (
        fin.filter((pl.col("line_item") == "revenue") & (pl.col("basis") == "ttm"))
        .select("cik", "period_end", pl.col("value").alias("revenue_ttm_at_fy_end"))
        .join(
            fin.filter((pl.col("line_item") == "revenue") & (pl.col("basis") == "fy")).select(
                "cik", "period_end", pl.col("value").alias("revenue_fy")
            ),
            on=["cik", "period_end"],
        )
        .with_columns(
            (pl.col("revenue_ttm_at_fy_end") / pl.col("revenue_fy") - 1).abs().alias("gap")
        )
    )
    hits = pair.filter(pl.col("gap").is_finite() & (pl.col("gap") > cfg["ttm_vs_fy_tolerance"]))
    out["ttm_vs_fy"] = (
        hits.join(frame.select(*ID_COLS), on="cik")
        .sort(["gap", "cik"], descending=[True, False])
        .select(
            *ID_COLS,
            "period_end",
            "revenue_ttm_at_fy_end",
            "revenue_fy",
            pl.col("gap").alias("severity"),
        )
        .head(top)
    )
    return out


def distribution(frame: pl.DataFrame, metric_ids: list[str]) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    n_all = frame.height
    for mid in metric_ids:
        col = frame[mid]
        vals = col.drop_nulls().cast(pl.Float64)
        codes = frame.filter(pl.col(mid).is_null())[f"{mid}__code"].value_counts()
        by_code = dict(zip(codes[f"{mid}__code"].to_list(), codes["count"].to_list(), strict=True))
        row: dict[str, Any] = {"metric_id": mid, "n": vals.len()}
        for q in QUANTILES:
            row[f"p{round(q * 100)}"] = vals.quantile(q, "nearest") if vals.len() else None
        row["null_share"] = (n_all - vals.len()) / n_all if n_all else None
        for c in NULL_CODES:
            row[f"null_{c}"] = by_code.get(c, 0) / n_all if n_all else 0.0
        rows.append(row)
    return pl.DataFrame(rows)


def extremes(frame: pl.DataFrame, metric_id: str, top: int) -> pl.DataFrame:
    """The `top` values furthest from the median (both tails), with the company."""
    med = frame[metric_id].cast(pl.Float64).median()
    if med is None:
        return frame.head(0).select(*ID_COLS, metric_id)
    return (
        frame.filter(pl.col(metric_id).is_not_null())
        .with_columns((pl.col(metric_id).cast(pl.Float64) - med).abs().alias("_d"))
        .sort(["_d", "cik"], descending=[True, False])
        .select(*ID_COLS, metric_id)
        .head(top)
    )


def null_rates(frame: pl.DataFrame, metric_ids: list[str]) -> pl.DataFrame:
    n = frame.height
    return pl.DataFrame(
        [
            {"metric_id": m, "n": n, "null_share": frame[m].null_count() / n if n else None}
            for m in metric_ids
        ]
    )
