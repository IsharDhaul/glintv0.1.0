"""Flag rules (§2.10): questions, not verdicts, each with the evidence that raised it. Pure polars.

Thresholds and question text come from `config/thresholds.yaml` (`flags`). A rule fires only on
present values: a null input never raises a flag and never counts against the company. `{x}` in a
question is filled with the evidence value formatted with its unit.
"""

import json
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import cache
from typing import Any

import polars as pl

from glint.contracts.enums import FlagId
from glint.metrics.inputs import FY, MRQ, MRQ_1Y, TTM, TTM_1Y, Slot, col_name
from glint.metrics.params import load_thresholds

F = FlagId


@dataclass(frozen=True)
class Rule:
    flag_id: FlagId
    when: pl.Expr
    evidence: dict[str, pl.Expr]
    x: Callable[[dict[str, Any]], str] | None = None  # fills `{x}` from the evidence


def _pct(v: float) -> str:
    return f"{v:.1%}"


RECENT_ADV = "avg_dollar_volume_recent"
"""Frame column for `market_cap_implausible`: mean daily dollar volume over the last
`flags.market_cap_implausible.adv_sessions` market sessions (see `recent_dollar_volume`)."""


def recent_dollar_volume(bars: pl.DataFrame, sessions: list[date]) -> pl.DataFrame:
    """ticker, avg_dollar_volume_recent: mean(unadjusted close × volume) over `sessions` (the last
    N market sessions on disk). Null unless the ticker has a bar with a volume on every one of
    them, so a halted or thinly traded name never gets an average over fewer days. Unadjusted is
    right here: close × volume is the dollars that actually traded, unchanged by a split."""
    n = len(sessions)
    schema = {"ticker": pl.String, RECENT_ADV: pl.Float64}
    if n == 0 or bars.is_empty():
        return pl.DataFrame(schema=schema)
    dv = (
        bars.filter(pl.col("date").is_in(sessions) & pl.col("volume").is_not_null())
        .group_by("ticker")
        .agg(
            pl.col("date").n_unique().alias("_n"),
            (pl.col("close") * pl.col("volume")).mean().alias(RECENT_ADV),
        )
    )
    return (
        dv.with_columns(pl.when(pl.col("_n") == n).then(pl.col(RECENT_ADV)).alias(RECENT_ADV))
        .select("ticker", pl.col(RECENT_ADV).cast(pl.Float64))
        .sort("ticker")
    )


class _Keys(dict[str, Any]):
    """The flag's own keys for its question; `{x}` stays for the evidence value."""

    def __missing__(self, key: str) -> str:
        if key == "x":
            return "{x}"
        raise KeyError(f"question placeholder {{{key}}} is not one of the flag's keys")


def render_question(block: dict[str, Any]) -> str:
    """The question with `{key}` / `{key:spec}` filled from the flag's own thresholds, so the
    wording can't drift from the number (principle 8)."""
    return string.Formatter().vformat(str(block["question"]), (), _Keys(block))


@cache
def load_rules() -> dict[str, Any]:
    t = load_thresholds()
    flags: dict[str, Any] = dict(t["flags"])
    # One stale number for the flag and the universe's stale exclusion (principle 8).
    stale = int(t["freshness"]["stale_annual_report_months"])
    flags["stale_filing"] = {**flags["stale_filing"], "annual_report_age_months_gt": stale}
    return {k: {**v, "question": render_question(v)} for k, v in flags.items()}


def rules(cfg: dict[str, Any]) -> list[Rule]:
    def c(i: str, slot: Slot) -> pl.Expr:
        return pl.col(col_name(i, slot))

    def pos(e: pl.Expr) -> pl.Expr:
        """A denominator: null unless > 0, so a ratio never becomes NaN or inf."""
        return pl.when(e > 0).then(e)

    rev_growth = c("revenue", TTM) / pos(c("revenue", TTM_1Y)) - 1
    dso_now = c("receivables", MRQ) / pos(c("revenue", TTM))
    dso_ago = c("receivables", MRQ_1Y) / pos(c("revenue", TTM_1Y))
    dso_change = dso_now / pos(dso_ago) - 1
    inv_minus_rev = (c("inventory", MRQ) / pos(c("inventory", MRQ_1Y)) - 1) - rev_growth
    years = cfg["earnings_without_cash"]["consecutive_fys"]
    no_cash = pl.all_horizontal(
        *((c("net_income", FY[k]) > 0) & (c("cfo", FY[k]) < 0) for k in range(years))
    )
    stale_months = cfg["stale_filing"]["annual_report_age_months_gt"]
    stale = pl.col("last_annual_date") < pl.col("as_of_fundamentals").dt.offset_by(
        f"-{stale_months}mo"
    )
    mci = cfg["market_cap_implausible"]
    cap_to_adv = pl.col("market_cap") / pos(pl.col(RECENT_ADV))
    return [
        Rule(
            F.DILUTION,
            pl.col("share_count_change_yoy") >= cfg["dilution"]["share_count_change_yoy_gte"],
            {"share_count_change_yoy": pl.col("share_count_change_yoy")},
            lambda ev: _pct(ev["share_count_change_yoy"]),
        ),
        Rule(
            F.EARNINGS_WITHOUT_CASH,
            no_cash,
            {
                f"{name}_fy{k}": c(item, FY[k])
                for k in range(years)
                for name, item in (("net_income", "net_income"), ("cfo", "cfo"))
            },
        ),
        Rule(
            F.RECEIVABLES_OUTPACING,
            (dso_change >= cfg["receivables_outpacing"]["dso_change_yoy_gte"])
            & (rev_growth < cfg["receivables_outpacing"]["revenue_growth_yoy_lt"]),
            {"dso_change_yoy": dso_change, "revenue_growth_yoy": rev_growth},
        ),
        Rule(
            F.INVENTORY_BUILD,
            inv_minus_rev >= cfg["inventory_build"]["inventory_minus_revenue_growth_gte"],
            {"inventory_minus_revenue_growth": inv_minus_rev},
        ),
        Rule(
            F.GOODWILL_HEAVY,
            pl.col("goodwill_to_assets") >= cfg["goodwill_heavy"]["goodwill_to_assets_gte"],
            {"goodwill_to_assets": pl.col("goodwill_to_assets")},
        ),
        Rule(
            F.THIN_COVERAGE,
            pl.col("interest_coverage") < cfg["thin_coverage"]["interest_coverage_lt"],
            {"interest_coverage": pl.col("interest_coverage")},
        ),
        Rule(
            F.STALE_FILING,
            stale,
            {"last_annual_date": pl.col("last_annual_date").cast(pl.String)},
        ),
        Rule(F.LATE_FILER, pl.col("nt_filing_12m"), {"nt_filing_12m": pl.col("nt_filing_12m")}),
        Rule(
            F.NEGATIVE_EQUITY,
            c("equity", MRQ) <= cfg["negative_equity"]["equity_lte"],
            {"equity_mrq": c("equity", MRQ)},
        ),
        Rule(
            F.HEAVY_SBC,
            pl.col("sbc_to_revenue") >= cfg["heavy_sbc"]["sbc_to_revenue_gte"],
            {"sbc_to_revenue": pl.col("sbc_to_revenue")},
        ),
        Rule(F.FY_CHANGE, pl.col("fy_end_changed"), {"fy_end_changed": pl.col("fy_end_changed")}),
        Rule(
            F.MARKET_CAP_IMPLAUSIBLE,
            cap_to_adv < mci["market_cap_to_adv_lt"],
            {
                "market_cap": pl.col("market_cap"),
                RECENT_ADV: pl.col(RECENT_ADV),
                "adv_sessions": pl.lit(int(mci["adv_sessions"])),
                "market_cap_to_adv": cap_to_adv,
                "shares_as_of": pl.col("shares_as_of").cast(pl.String),
                "price_as_of": pl.col("price_as_of").cast(pl.String),
            },
            lambda ev: _pct(ev["market_cap_to_adv"]),
        ),
    ]


def restatements(fin: pl.DataFrame, frame: pl.DataFrame, cfg: dict[str, Any]) -> pl.DataFrame:
    """`restated` (P1): a fiscal-year value of a watched item, in the latest `lookback_fys` FYs,
    differs from its first-filed value by more than `change_gt`. Evidence is the largest change."""
    r = cfg["restated"]
    ends = frame.select("cik", *(f"fy{k}_end" for k in range(r["lookback_fys"])))
    recent = ends.unpivot(index="cik", value_name="period_end").drop_nulls("period_end")
    rows = (
        fin.filter(
            (pl.col("basis") == "fy")
            & pl.col("line_item").is_in(r["items"])
            & (pl.col("first_filed_value") != 0)
        )
        .join(recent.select("cik", "period_end"), on=["cik", "period_end"])
        .with_columns(change=pl.col("value") / pl.col("first_filed_value") - 1)
        .filter(pl.col("change").abs() > r["change_gt"])
        .sort(["cik", pl.col("change").abs()], descending=[False, True])
        .group_by("cik", maintain_order=True)
        .first()
    )
    return rows.select(
        "cik",
        pl.lit(F.RESTATED.value).alias("flag_id"),
        pl.lit(r["question"]).alias("question"),
        pl.struct(
            "line_item",
            pl.col("period_end").cast(pl.String),
            "first_filed_value",
            "value",
            "change",
        )
        .struct.json_encode()
        .alias("evidence"),
    )


FLAG_SCHEMA = {"cik": pl.String, "flag_id": pl.String, "question": pl.String, "evidence": pl.String}


def _json_value(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def evaluate_flags(frame: pl.DataFrame, fin: pl.DataFrame, cfg: dict[str, Any]) -> pl.DataFrame:
    """One row per raised flag: cik, flag_id, question, evidence (JSON object)."""
    if RECENT_ADV not in frame.columns:  # no recent bars given: the rule can't fire (never guesses)
        frame = frame.with_columns(pl.lit(None, pl.Float64).alias(RECENT_ADV))
    out: list[dict[str, Any]] = []
    for rule in rules(cfg):
        names = list(rule.evidence)
        hits = frame.filter(rule.when.fill_null(False)).select(
            "cik", *(e.alias(n) for n, e in rule.evidence.items())
        )
        question: str = cfg[rule.flag_id.value]["question"]
        for row in hits.iter_rows(named=True):
            ev = {n: _json_value(row[n]) for n in names}
            q = question.replace("{x}", rule.x(ev)) if rule.x else question
            out.append({
                "cik": row["cik"], "flag_id": rule.flag_id.value, "question": q,
                "evidence": json.dumps(ev, sort_keys=False, allow_nan=False),
            })  # fmt: skip
    flags = pl.DataFrame(out, schema=FLAG_SCHEMA)
    flags = pl.concat([flags, restatements(fin, frame, cfg)])
    return flags.sort("cik", "flag_id")
