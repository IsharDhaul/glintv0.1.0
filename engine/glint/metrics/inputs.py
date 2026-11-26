"""The inputs frame (WT-06 step 1): one row per company, every value a metric reads. Pure polars.

Period rules (§2.4 basis, §4.3 rule 7, WT-03 hand-off):

- **One TTM end per company** (`ttm_end`): the latest TTM end across all line items, so ratios
  that combine flows never mix periods. An item with no TTM at that end is null with a reason.
- **One MRQ date** (`mrq_end`): the latest balance-sheet date (the share count excluded: cover
  pages are dated after the balance sheet).
- **Year ago**: the company's TTM end / balance-sheet date nearest the same calendar day a year
  earlier, within ±`year_ago_window_days` (ties → the earlier date).
- **Fiscal years**: `fy0` is the latest FY end on any flow; `fyK` is the FY end nearest K years
  before it (same window), so a skipped year is a gap, never a silent shift.
- **Share count**: the latest `shares_outstanding` at its own date (`shares_as_of`).

Each value column `<item>__<slot>` has a sibling `<item>__<slot>__d` (derived input, §4.3 rule 9).
Null reasons are built lazily by `glint.metrics.frame` from the `__last*` columns kept here.
"""

from dataclasses import dataclass
from datetime import date

import polars as pl

from glint.contracts.enums import Basis, LineItem, PeriodKind
from glint.financials.concepts import ConceptMap

FY_DEPTH = 5  # fy0 … fy5 (revenue_cagr_5y needs FY−5)


@dataclass(frozen=True)
class Slot:
    """Where a value is read: a basis and which company-level end."""

    name: str  # column suffix
    basis: Basis
    end_col: str  # column of the inputs frame holding the period end


TTM = Slot("ttm", Basis.TTM, "ttm_end")
TTM_1Y = Slot("ttm_1y", Basis.TTM, "ttm_1y_end")
MRQ = Slot("mrq", Basis.MRQ, "mrq_end")
MRQ_1Y = Slot("mrq_1y", Basis.MRQ, "mrq_1y_end")
MRQ_2Y = Slot("mrq_2y", Basis.MRQ, "mrq_2y_end")  # only for the "tagged a year earlier" check
Q = Slot("q", Basis.Q, "q_end")
Q_1Y = Slot("q_1y", Basis.Q, "q_1y_end")
FY = tuple(Slot(f"fy{k}", Basis.FY, f"fy{k}_end") for k in range(FY_DEPTH + 1))

SHARES_NOW = Slot("now", Basis.MRQ, "shares_as_of")  # the share count at its own date

FLOW_SLOTS = (TTM, TTM_1Y, Q, Q_1Y, *FY)
INSTANT_SLOTS = (MRQ, MRQ_1Y, MRQ_2Y, *FY)

PRICE_COLUMNS = (
    "close",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_12m",
    "momentum_12_1",
    "high_52w",
    "pct_from_52w_high",
    "volatility_1y",
    "avg_dollar_volume_3m",
)


def col_name(item: LineItem | str, slot: Slot) -> str:
    return f"{item}__{slot.name}"


def shift_years(d: date, years: int) -> date:
    """The same calendar day `years` earlier (29 Feb → 28 Feb)."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def _years_back(end: pl.Expr, years: int) -> pl.Expr:
    return end.map_elements(lambda d: shift_years(d, years), return_dtype=pl.Date)


def _nearest_end(
    candidates: pl.DataFrame, targets: pl.DataFrame, target_col: str, out_col: str, window: int
) -> pl.DataFrame:
    """cik → the candidate `period_end` nearest `target_col` within ±window days (ties earlier)."""
    return (
        targets.select("cik", target_col)
        .drop_nulls()
        .join(candidates, on="cik")
        .with_columns(dist=(pl.col("period_end") - pl.col(target_col)).dt.total_days().abs())
        .filter(pl.col("dist") <= window)
        .sort(["cik", "dist", "period_end"])
        .group_by("cik", maintain_order=True)
        .first()
        .select("cik", pl.col("period_end").alias(out_col))
    )


def period_ends(fin: pl.DataFrame, concepts: ConceptMap, window: int) -> pl.DataFrame:
    """Per company: ttm_end, mrq_end, q_end, fy0_end…, their year-ago ends and shares_as_of."""
    flows = [i.value for i in LineItem if concepts[i].kind is PeriodKind.DURATION]
    shares = LineItem.SHARES_OUTSTANDING.value

    def distinct(basis: Basis, extra: pl.Expr | None = None) -> pl.DataFrame:
        f = fin.filter(pl.col("basis") == basis.value)
        if extra is not None:
            f = f.filter(extra)
        return f.select("cik", "period_end").unique()

    ttm = distinct(Basis.TTM)
    mrq = distinct(Basis.MRQ, pl.col("line_item") != shares)
    q = distinct(Basis.Q, pl.col("line_item") == LineItem.DILUTED_SHARES.value)
    fy = distinct(Basis.FY, pl.col("line_item").is_in(flows))
    ciks = fin.select("cik").unique()

    def latest(c: pl.DataFrame, name: str) -> pl.DataFrame:
        return c.group_by("cik").agg(pl.col("period_end").max().alias(name))

    out = ciks
    for frame, name in ((ttm, "ttm_end"), (mrq, "mrq_end"), (q, "q_end"), (fy, "fy0_end")):
        out = out.join(latest(frame, name), on="cik", how="left")
    out = out.join(
        fin.filter((pl.col("basis") == Basis.MRQ.value) & (pl.col("line_item") == shares))
        .group_by("cik")
        .agg(pl.col("period_end").max().alias("shares_as_of")),
        on="cik",
        how="left",
    )
    targets = out.with_columns(
        _years_back(pl.col("ttm_end"), 1).alias("_ttm_t"),
        _years_back(pl.col("mrq_end"), 1).alias("_mrq_t"),
        _years_back(pl.col("mrq_end"), 2).alias("_mrq2_t"),
        _years_back(pl.col("q_end"), 1).alias("_q_t"),
        *(_years_back(pl.col("fy0_end"), k).alias(f"_fy{k}_t") for k in range(1, FY_DEPTH + 1)),
    )
    for cand, t, name in ((ttm, "_ttm_t", "ttm_1y_end"), (mrq, "_mrq_t", "mrq_1y_end"),
                          (mrq, "_mrq2_t", "mrq_2y_end"), (q, "_q_t", "q_1y_end")):  # fmt: skip
        out = out.join(_nearest_end(cand, targets, t, name, window), on="cik", how="left")
    for k in range(1, FY_DEPTH + 1):
        out = out.join(
            _nearest_end(fy, targets, f"_fy{k}_t", f"fy{k}_end", window), on="cik", how="left"
        )
    return out.sort("cik")


def _slot_values(
    fin: pl.DataFrame, ends: pl.DataFrame, items: list[str], slot: Slot
) -> pl.DataFrame:
    rows = (
        fin.filter((pl.col("basis") == slot.basis.value) & pl.col("line_item").is_in(items))
        .join(ends.select("cik", slot.end_col), on="cik")
        .filter(pl.col("period_end") == pl.col(slot.end_col))
    )
    out = ends.select("cik")
    for item in items:
        r = rows.filter(pl.col("line_item") == item).select(
            "cik",
            pl.col("value").alias(col_name(item, slot)),
            pl.col("derived").alias(col_name(item, slot) + "__d"),
        )
        out = out.join(r, on="cik", how="left")
    return out


SHARES_NOW_TAG = "shares_outstanding__now__tag"
SHARES_NOW_FILED = "shares_outstanding__now__filed"


def _shares_now_source(fin: pl.DataFrame, ends: pl.DataFrame) -> pl.DataFrame:
    """The source tag and filing date of the share count at `shares_as_of`, for the share basis of
    the market-cap split adjustment (`prices.add_split_ratios`)."""
    shares = LineItem.SHARES_OUTSTANDING.value
    rows = fin.filter(
        (pl.col("basis") == SHARES_NOW.basis.value) & (pl.col("line_item") == shares)
    ).select("cik", "period_end", pl.col("source_tag").alias(SHARES_NOW_TAG),
             pl.col("filed").alias(SHARES_NOW_FILED))  # fmt: skip
    return (
        ends.select("cik", SHARES_NOW.end_col)
        .join(rows, left_on=["cik", SHARES_NOW.end_col], right_on=["cik", "period_end"])
        .select("cik", SHARES_NOW_TAG, SHARES_NOW_FILED)
        .unique("cik", keep="first", maintain_order=True)
    )


def _last_seen(fin: pl.DataFrame) -> pl.DataFrame:
    """Per (cik, item): the latest end on any basis, and on FY/Q (for null reasons)."""
    last = fin.group_by("cik", "line_item").agg(
        pl.col("period_end").max().alias("last_any"),
        pl.col("period_end")
        .filter(pl.col("basis").is_in([Basis.FY.value, Basis.Q.value]))
        .max()
        .alias("last_fyq"),
    )
    out = fin.select("cik").unique()
    for item in sorted(i.value for i in LineItem):
        r = last.filter(pl.col("line_item") == item).select(
            "cik",
            pl.col("last_any").alias(f"{item}__last"),
            pl.col("last_fyq").alias(f"{item}__lastfyq"),
        )
        out = out.join(r, on="cik", how="left")
    return out


COMPANY_COLUMNS = (
    "cik",
    "name",
    "tickers",
    "primary_ticker",
    "exchange",
    "sector",
    "kind",
    "is_foreign_filer",
    "is_reit",
    "has_facts",
    "taxonomy",
    "reporting_currency",
    "last_annual_date",
    "last_quarterly_date",
    "nt_filing_12m",
    "fy_end_changed",
)
OPTIONAL_COMPANY_COLUMNS = ("primary_ticker_provisional", "last_annual_form")
# Finance-lease presentation (contract #57): null-filled when a frame predates it.
LEASE_COLUMNS = ("finance_lease_status", "finance_lease_evidence")


def build_inputs(
    companies: pl.DataFrame,
    fin: pl.DataFrame,
    concepts: ConceptMap,
) -> pl.DataFrame:
    """Companies left-joined with every slot of every line item (prices are joined later, once
    the primary ticker is final)."""
    window = concepts.params.year_ago_window_days
    ends = period_ends(fin, concepts, window)
    extra = [c for c in OPTIONAL_COMPANY_COLUMNS if c in companies.columns]
    missing = [
        pl.lit(None, pl.String).alias(c) for c in LEASE_COLUMNS if c not in companies.columns
    ]
    companies = companies.with_columns(missing) if missing else companies
    base = companies.select(*COMPANY_COLUMNS, *extra, *LEASE_COLUMNS).join(
        ends, on="cik", how="left"
    )
    ends = base.select("cik", *(c for c in ends.columns if c != "cik"))
    flows = sorted(i.value for i in LineItem if concepts[i].kind is PeriodKind.DURATION)
    instants = sorted(
        i.value
        for i in LineItem
        if concepts[i].kind is PeriodKind.INSTANT and i is not LineItem.SHARES_OUTSTANDING
    )
    out = base
    for slot in FLOW_SLOTS:
        out = out.join(_slot_values(fin, ends, flows, slot), on="cik", how="left")
    for slot in INSTANT_SLOTS:
        out = out.join(_slot_values(fin, ends, instants, slot), on="cik", how="left")
    shares = LineItem.SHARES_OUTSTANDING.value
    out = out.join(
        _slot_values(fin, ends, [shares], SHARES_NOW),
        on="cik",
        how="left",
    )
    out = out.join(_shares_now_source(fin, ends), on="cik", how="left")
    out = out.join(_eps_shares(fin, ends), on="cik", how="left")
    out = out.join(_shares_basis(fin, ends), on="cik", how="left")
    out = out.join(_last_seen(fin), on="cik", how="left")
    return out.sort("cik")


def _eps_shares(fin: pl.DataFrame, ends: pl.DataFrame) -> pl.DataFrame:
    """`diluted_shares__ttmend` / `__ttmend_1y`: the diluted weighted count for the quarter ending
    at the TTM end, or the fiscal-year count when that end is a FY end (Q4 is never filed)."""
    item = [LineItem.DILUTED_SHARES.value]
    out = ends.select("cik")
    for suffix, end_col in (("ttmend", "ttm_end"), ("ttmend_1y", "ttm_1y_end")):
        q = _slot_values(fin, ends, item, Slot("_q", Basis.Q, end_col))
        fy = _slot_values(fin, ends, item, Slot("_fy", Basis.FY, end_col))
        name = f"diluted_shares__{suffix}"
        both = q.join(fy, on="cik")
        out = out.join(
            both.select(
                "cik",
                pl.coalesce("diluted_shares___q", "diluted_shares___fy").alias(name),
                pl.when(pl.col("diluted_shares___q").is_not_null())
                .then(pl.col("diluted_shares___q__d"))
                .otherwise(pl.col("diluted_shares___fy__d"))
                .alias(name + "__d"),
            ),
            on="cik",
            how="left",
        )
    return out


SHARE_BASIS_SLOTS = (Q, Q_1Y, FY[0], FY[1])
FILING_FIELDS = ("first", "filed", "factor")  # see `filing_exprs`


def basis_col(slot_name: str, field: str = "basis") -> str:
    """`diluted_shares__<slot>__<field>` for the diluted count at that slot: its share-basis date
    (`basis`, set by `prices.add_split_ratios`) or a `FILING_FIELDS` input to it."""
    return f"{LineItem.DILUTED_SHARES.value}__{slot_name}__{field}"


def filing_exprs() -> dict[str, pl.Expr]:
    """What a `financials` count's share basis is read from (`prices.share_basis`): its first and
    latest filing dates and the restatement factor (value ÷ first-filed value; exactly 1.0 when
    unchanged, since counts are whole numbers)."""
    return {
        "first": pl.col("first_filed_date"),
        "filed": pl.col("filed"),
        "factor": pl.col("value") / pl.when(pl.col("first_filed_value") > 0)
        .then(pl.col("first_filed_value")),
    }  # fmt: skip


def _shares_basis(fin: pl.DataFrame, ends: pl.DataFrame) -> pl.DataFrame:
    """`FILING_FIELDS` of each diluted count a share comparison reads (Q, Q_1Y, FY0, FY1 and the
    TTM-end counts of `_eps_shares`)."""
    item = LineItem.DILUTED_SHARES.value
    rows = fin.filter(pl.col("line_item") == item).select(
        "cik", "basis", "period_end", **filing_exprs()
    )

    def at(basis: Basis, end_col: str, name: str) -> pl.DataFrame:
        r = rows.filter(pl.col("basis") == basis.value).drop("basis")
        return (
            ends.select("cik", end_col)
            .join(r, left_on=["cik", end_col], right_on=["cik", "period_end"], how="left")
            .select("cik", *(pl.col(f).alias(basis_col(name, f)) for f in FILING_FIELDS))
        )

    out = ends.select("cik")
    for slot in SHARE_BASIS_SLOTS:
        out = out.join(at(slot.basis, slot.end_col, slot.name), on="cik", how="left")
    for suffix, end_col in (("ttmend", "ttm_end"), ("ttmend_1y", "ttm_1y_end")):
        q, fy = at(Basis.Q, end_col, "_q"), at(Basis.FY, end_col, "_fy")
        # same choice as `_eps_shares`: the quarter's count if filed, else the FY count
        both = q.join(fy, on="cik").join(
            _slot_values(fin, ends, [item], Slot("_q", Basis.Q, end_col)), on="cik"
        )
        has_q = pl.col(f"{item}___q").is_not_null()
        chosen = [
            pl.when(has_q).then(pl.col(basis_col("_q", f))).otherwise(pl.col(basis_col("_fy", f)))
            .alias(basis_col(suffix, f))
            for f in FILING_FIELDS
        ]  # fmt: skip
        out = out.join(both.select("cik", *chosen), on="cik", how="left")
    return out


def join_prices(inputs: pl.DataFrame, stats: pl.DataFrame) -> pl.DataFrame:
    """Price stats of each company's `primary_ticker`: `price_as_of`, `px__close`, …"""
    p = stats.select(
        pl.col("ticker").alias("primary_ticker"),
        pl.col("as_of").alias("price_as_of"),
        *(pl.col(c).alias(f"px__{c}") for c in PRICE_COLUMNS),
        "history_days",
    )
    return inputs.join(p, on="primary_ticker", how="left")
