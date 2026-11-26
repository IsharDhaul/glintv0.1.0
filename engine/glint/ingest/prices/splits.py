"""Split adjustment at read time, and the split check WT-06 uses for share-count safety.

A split takes effect at the open of its `execution_date`, so it adjusts every bar *before* that
date: adjusted close = close ÷ (product of ratios of later splits), adjusted volume = volume × the
same. Splits dated after `as_of` (announced, not yet effective) are ignored.
"""

from bisect import bisect_right
from collections import defaultdict
from datetime import date

import polars as pl


def adjust_for_splits(bars: pl.DataFrame, splits: pl.DataFrame, as_of: date) -> pl.DataFrame:
    """Add `adj_close`, `adj_volume` and `split_factor` to unadjusted `bars`."""
    effective = (
        splits.filter(pl.col("execution_date") <= as_of)
        .select(
            "ticker",
            "execution_date",
            (pl.col("split_to") / pl.col("split_from")).alias("ratio"),
        )
        .filter(pl.col("ticker").is_in(bars["ticker"].unique().to_list()))
    )
    factors = (
        bars.select("ticker", "date")
        .join(effective, on="ticker", how="inner")
        .filter(pl.col("date") < pl.col("execution_date"))
        .group_by("ticker", "date")
        .agg(pl.col("ratio").product().alias("split_factor"))
    )
    return (
        bars.join(factors, on=["ticker", "date"], how="left")
        .with_columns(pl.col("split_factor").fill_null(1.0))
        .with_columns(
            (pl.col("close") / pl.col("split_factor")).alias("adj_close"),
            (pl.col("volume") * pl.col("split_factor")).alias("adj_volume"),
        )
        .sort(["ticker", "date"])
    )


class SplitIndex:
    """Fast `split_between` lookups over the splits table."""

    def __init__(self, splits: pl.DataFrame) -> None:
        by_ticker: dict[str, list[tuple[date, float]]] = defaultdict(list)
        for ticker, day, s_from, s_to in splits.select(
            "ticker", "execution_date", "split_from", "split_to"
        ).rows():
            by_ticker[ticker].append((day, s_to / s_from))
        self._dates: dict[str, list[date]] = {}
        self._ratios: dict[str, list[float]] = {}
        for ticker, rows in by_ticker.items():
            rows.sort()
            self._dates[ticker] = [d for d, _ in rows]
            self._ratios[ticker] = [r for _, r in rows]

    def split_between(self, ticker: str, d1: date, d2: date) -> float | None:
        """Combined ratio of splits effective in (d1, d2], or None if there were none.

        Shares counted at the end of `d1` × ratio = the same holding in shares at `d2`'s close.
        A split effective *on* `d1` is already in the `d1` count, so it is excluded.
        """
        dates = self._dates.get(ticker)
        if not dates or d2 <= d1:
            return None
        lo, hi = bisect_right(dates, d1), bisect_right(dates, d2)
        if lo == hi:
            return None
        ratio = 1.0
        for r in self._ratios[ticker][lo:hi]:
            ratio *= r
        return ratio


def split_between(splits: pl.DataFrame, ticker: str, d1: date, d2: date) -> float | None:
    """One-off form of `SplitIndex.split_between`."""
    return SplitIndex(splits.filter(pl.col("ticker") == ticker)).split_between(ticker, d1, d2)
