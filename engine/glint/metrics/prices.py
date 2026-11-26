"""Price-tier inputs: the primary ticker's `price_stats` row and the share count for market cap.

Null reasons, in order: no listed ticker or no bars (MISSING_INPUT); the ticker's last bar is more
than `price_stale_days` before the build's price date (STALE_DATA); too few sessions
(INSUFFICIENT_HISTORY, WT-02's `Windows.required()`); a missing volume in the ADV window
(MISSING_INPUT).
"""

from collections.abc import Iterable
from datetime import date
from typing import Any

import polars as pl

from glint.contracts.enums import LineItem, NoteCode
from glint.financials.concepts import load_concepts
from glint.ingest.prices.splits import SplitIndex
from glint.ingest.prices.stats import DEFAULT_WINDOWS
from glint.metrics.core import In, Info
from glint.metrics.inputs import (
    FILING_FIELDS,
    SHARES_NOW,
    SHARES_NOW_FILED,
    SHARES_NOW_TAG,
    basis_col,
)
from glint.metrics.params import Params

C = NoteCode
NEED = DEFAULT_WINDOWS.required()


def _s(e: pl.Expr) -> pl.Expr:
    return e.cast(pl.String)


def price_stale(p: Params) -> pl.Expr:
    return (pl.col("as_of_prices") - pl.col("price_as_of")).dt.total_days() > p.price_stale_days


def price_in(stat: str, p: Params, label: str | None = None) -> In:
    """A `price_stats` column of the primary ticker, with its null reason."""
    label = label or stat
    stale = price_stale(p)
    need = NEED[stat]
    no_ticker = pl.col("primary_ticker").is_null()
    not_common = pl.col("listing_kind").is_in(["preferred", "other"])
    no_bars = pl.col("price_as_of").is_null()
    short = pl.col("history_days") < need
    code = (
        pl.when(no_ticker).then(pl.lit(C.MISSING_INPUT.value))
        .when(not_common).then(pl.lit(C.MISSING_INPUT.value))
        .when(no_bars).then(pl.lit(C.MISSING_INPUT.value))
        .when(stale).then(pl.lit(C.STALE_DATA.value))
        .when(short).then(pl.lit(C.INSUFFICIENT_HISTORY.value))
        .otherwise(pl.lit(C.MISSING_INPUT.value))
    )  # fmt: skip
    days_old = (pl.col("as_of_prices") - pl.col("price_as_of")).dt.total_days()
    message = (
        pl.when(no_ticker).then(pl.lit(f"{label}: no listed ticker"))
        .when(not_common).then(pl.format(
            f"{label}: no common share listing (only {{}} {{}})",
            pl.when(pl.col("listing_kind") == "preferred").then(pl.lit("preferred"))
            .otherwise(pl.lit("non-common")), "primary_ticker"))
        .when(no_bars).then(pl.format(f"{label}: no price bars for {{}}", "primary_ticker"))
        .when(stale).then(pl.format(
            f"{label}: last close of {{}} is from {{}}, {{}} days before the build's price "
            "date {}",
            "primary_ticker", _s(pl.col("price_as_of")), days_old, _s(pl.col("as_of_prices"))))
        .when(short).then(pl.format(
            f"{label} needs {need} sessions of prices; {{}} has {{}}",
            "primary_ticker", "history_days"))
        .otherwise(pl.format(f"{label}: volume missing in the last {need} sessions of {{}}",
                             "primary_ticker"))
    )  # fmt: skip
    value = pl.when(stale | not_common).then(None).otherwise(pl.col(f"px__{stat}"))
    return In(label, value, code, message, pl.lit(False))


def shares_stale() -> pl.Expr:
    """The share count predates the latest balance sheet by more than WT-03's limit."""
    days = load_concepts().params.shares_stale_days
    return (pl.col("mrq_end") - pl.col("shares_as_of")).dt.total_days() > days


def shares_in() -> tuple[In, Info]:
    """Shares outstanding for market cap (§4.3 rules 11–12), adjusted for splits between the
    count's share basis (`SHARES_BASIS`) and the price date. The Info notes the adjustment
    (DERIVED_INPUT)."""
    raw = pl.col("shares_outstanding__now")
    stale = shares_stale()
    value = pl.when(stale).then(None).otherwise(raw * pl.col("split_ratio").fill_null(1.0))
    code = (
        pl.when(raw.is_null()).then(pl.lit(C.MISSING_INPUT.value))
        .otherwise(pl.lit(C.STALE_DATA.value))
    )  # fmt: skip
    message = (
        pl.when(raw.is_null())
        .then(pl.lit("shares_outstanding: no cover-page, balance-sheet or diluted count"))
        .otherwise(pl.format(
            "shares_outstanding: latest count is from {}, more than a year before the latest "
            "balance sheet ({})", _s(pl.col("shares_as_of")), _s(pl.col("mrq_end"))))
    )  # fmt: skip
    shares = In(
        "shares_outstanding",
        value,
        code,
        message,
        pl.col("shares_outstanding__now__d").fill_null(False),
        item=LineItem.SHARES_OUTSTANDING,
        slot=SHARES_NOW,
    )
    split = Info(
        pl.col("split_ratio").is_not_null(),
        C.DERIVED_INPUT,
        pl.when(pl.col(SHARES_BASIS) == pl.col("shares_as_of"))
        .then(
            pl.format(
                "shares_outstanding × {} for a split between the share count ({}) and the "
                "price ({})",
                pl.col("split_ratio").round(6),
                _s(pl.col("shares_as_of")),
                _s(pl.col("price_as_of")),
            )
        )
        .otherwise(
            pl.format(
                "shares_outstanding × {} for a split between the filing the share count ({}) is "
                "from ({}) and the price ({})",
                pl.col("split_ratio").round(6),
                _s(pl.col("shares_as_of")),
                _s(pl.col(SHARES_BASIS)),
                _s(pl.col("price_as_of")),
            )
        ),
    )
    return shares, split


SHARES_BASIS = "shares_outstanding__now__basis"


def shares_basis() -> pl.Expr:
    """The date the market-cap share count's basis is on. A cover-page count (`dei_cover_tags`)
    is the number outstanding on its own date (`shares_as_of`). A count from the financial
    statements (balance sheet, or the diluted fallback) is presented on the basis of the day its
    filing was issued: statements give retroactive effect to a split made after the period ends
    but before they're issued (SAB Topic 4C, ASC 260-10-55-12). So a split between the period
    end and the filing is already in the count (MYPS, ENHA) and isn't applied again."""
    cover = list(load_concepts().dei_cover_tags)
    return (
        pl.when(pl.col(SHARES_NOW_TAG).is_in(cover) | pl.col(SHARES_NOW_FILED).is_null())
        .then(pl.col("shares_as_of"))
        .otherwise(pl.max_horizontal("shares_as_of", SHARES_NOW_FILED))
    )


def share_split_ratios(index: SplitIndex, rows: Iterable[tuple[Any, Any, Any]]) -> pl.Series:
    out: list[float | None] = []
    for ticker, d1, d2 in rows:
        ok = isinstance(ticker, str) and isinstance(d1, date) and isinstance(d2, date)
        out.append(index.split_between(str(ticker), d1, d2) if ok else None)
    return pl.Series(out, dtype=pl.Float64)


def share_basis(index: SplitIndex, count: tuple[Any, ...], tolerance: float) -> date | None:
    """The date whose share basis a count is on, or None when that can't be told. `count`: (ticker,
    then `inputs.FILING_FIELDS`: first filing, latest filing, restatement factor). A weighted count
    is restated for splits before its filing is issued (ASC 260), but filers don't always restate
    the comparatives they re-file, so the count's own history decides (splits: `index`, the
    confirmed ones):

    - unchanged since its first filing (factor exactly 1): that filing's basis (`first`);
    - changed, with no split between its first and latest filing: a correction; `filed`;
    - changed by about the splits between them (within `tolerance`): restated; `filed`;
    - changed by another factor across a split: unknown (None), so it isn't adjusted.
    """
    ticker, first, filed, factor = count
    if not isinstance(filed, date):
        return None
    if not isinstance(first, date) or not isinstance(factor, float):
        return filed
    if factor == 1.0:
        return first
    ratio = index.split_between(str(ticker), first, filed) if isinstance(ticker, str) else None
    if ratio is None or abs(factor / ratio - 1) <= tolerance:
        return filed
    return None


def add_split_ratios(
    frame: pl.DataFrame, splits: pl.DataFrame, fin: pl.DataFrame, tolerance: float
) -> pl.DataFrame:
    """`split_ratio`: product of splits effective in (`SHARES_BASIS`, price_as_of] for the primary
    ticker (WT-02's `split_between`), or null when there were none. Also, for diluted-share
    comparisons, from the splits the filings confirm (`confirmed_splits`): each count's share-basis
    date (`basis_col(slot)`, `share_basis`) and the ratios between them (`SHARE_SPLITS`)."""
    frame = frame.with_columns(shares_basis().alias(SHARES_BASIS))
    rows = frame.select("primary_ticker", SHARES_BASIS, "price_as_of").iter_rows()
    frame = frame.with_columns(share_split_ratios(SplitIndex(splits), rows).alias("split_ratio"))
    tickers = frame.select("cik", "primary_ticker")
    index = SplitIndex(confirmed_splits(splits, fin, tickers, tolerance))
    slots = sorted({s for pair in SHARE_SPLIT_SLOTS.values() for s in pair})
    frame = frame.with_columns(
        pl.Series(
            basis_col(s),
            [
                share_basis(index, r, tolerance)
                for r in frame.select(
                    "primary_ticker", *(basis_col(s, f) for f in FILING_FIELDS)
                ).iter_rows()
            ],
            dtype=pl.Date,
        )
        for s in slots
    )
    return frame.with_columns(
        share_split_ratios(index, frame.select("primary_ticker", ago, now).iter_rows()).alias(name)
        for name, (ago, now) in SHARE_SPLITS.items()
    )


EVIDENCE_ITEMS = (LineItem.DILUTED_SHARES.value, LineItem.SHARES_OUTSTANDING.value)


def confirmed_splits(
    splits: pl.DataFrame, fin: pl.DataFrame, tickers: pl.DataFrame, tolerance: float
) -> pl.DataFrame:
    """The rows of WT-02's split table that the company's own filings confirm, for diluted-share
    comparisons. The price provider's table also holds events that don't change the share counts
    in the filings (an ADR ratio change, one leg of an odd-lot reverse/forward pair, a 1.001 row),
    so a split counts only when a later filing restated a share count by about its ratio: a
    `financials` diluted or outstanding count whose value differs from its first-filed value by a
    factor within `tolerance` of the split's ratio, or of the product of every split between that
    count's first and latest filing (both ways round: a later count re-filed on the new basis).
    A factor within `tolerance` of 1 is a correction, not evidence, so a split whose ratio is that
    close to 1 is never confirmed. `tickers`: cik → primary_ticker.
    """
    if splits.is_empty():
        return splits
    ev = (
        fin.filter(
            pl.col("line_item").is_in(EVIDENCE_ITEMS)
            & (pl.col("value") > 0) & (pl.col("first_filed_value") > 0)
            & (pl.col("value") != pl.col("first_filed_value"))
            & (pl.col("filed") > pl.col("first_filed_date"))
        )
        .join(tickers.drop_nulls("primary_ticker"), on="cik")
        .select(
            pl.col("primary_ticker").alias("ticker"),
            "first_filed_date",
            "filed",
            (pl.col("value") / pl.col("first_filed_value")).alias("factor"),
        )
        .filter((pl.col("factor") - 1).abs() > tolerance)
        .unique()
    )  # fmt: skip
    by_ticker: dict[str, list[tuple[date, float]]] = {}
    for t, d, s_from, s_to in splits.select(
        "ticker", "execution_date", "split_from", "split_to"
    ).iter_rows():
        by_ticker.setdefault(t, []).append((d, s_to / s_from))

    def near(factor: float, ratio: float) -> bool:
        return abs(factor / ratio - 1) <= tolerance

    confirmed: set[tuple[str, date]] = set()
    for t, first, last, factor in ev.filter(pl.col("ticker").is_in(list(by_ticker))).iter_rows():
        window = [(d, r) for d, r in by_ticker[t] if first < d <= last]
        if not window:
            continue
        product = 1.0
        for _, r in window:
            product *= r
        if near(factor, product):
            confirmed.update((t, d) for d, _ in window)
        else:
            confirmed.update((t, d) for d, r in window if near(factor, r))
    keep = [(t, d) in confirmed for t, d in splits.select("ticker", "execution_date").iter_rows()]
    return splits.filter(pl.Series(keep, dtype=pl.Boolean))


# Split ratio column → (slot of the earlier diluted count, of the later one)
SHARE_SPLIT_SLOTS = {
    "share_split__q": ("q_1y", "q"),
    "share_split__ttmend": ("ttmend_1y", "ttmend"),
    "share_split__fy": ("fy1", "fy0"),
}
# … → (share-basis date column of the earlier count, of the later one)
SHARE_SPLITS = {k: (basis_col(a), basis_col(b)) for k, (a, b) in SHARE_SPLIT_SLOTS.items()}


def split_adjusted(ago: In, now: In, ratio_col: str) -> tuple[In, Info]:
    """The earlier diluted count `ago` restated to the share basis of `now`: × the splits effective
    between the two counts' share-basis dates (`share_basis`). A count the filer
    already restated in a later filing is on that filing's basis and gets no second adjustment;
    one re-filed unchanged stays on its first filing's basis. The Info notes the adjustment
    (DERIVED_INPUT)."""
    ratio = pl.col(ratio_col)
    ago_filed, now_filed = SHARE_SPLITS[ratio_col]
    adjusted = In(
        ago.label, ago.value * ratio.fill_null(1.0), ago.code, ago.message, ago.derived,
        ago.note, ago.item, ago.slot, ago.metric_id,
    )  # fmt: skip
    info = Info(
        ratio.is_not_null() & ago.value.is_not_null() & now.value.is_not_null(),
        C.DERIVED_INPUT,
        pl.format(
            f"{ago.label} × {{}} for a split between the filing its count is from ({{}}) and "
            f"{now.label}'s ({{}})",
            ratio.round(6), _s(pl.col(ago_filed)), _s(pl.col(now_filed)),
        ),
    )  # fmt: skip
    return adjusted, info
