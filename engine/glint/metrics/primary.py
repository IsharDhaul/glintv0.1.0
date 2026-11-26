"""Final `primary_ticker` (WT-06 step 1): the common share class with the highest
`avg_dollar_volume_3m`. Pure polars.

Candidates are the company's tickers that are common listings (WT-02's `is_common_listing`, and not
a sibling's symbol plus W/U/R/P, WT-01's `is_derived`). Ties and missing volumes keep WT-01's
provisional choice, which comes first. A company with no priced candidate keeps it too.
A symbol in `config/share_classes.yaml` `non_common_symbols` (a preferred with no suffix, Strive's
SATS) is never a candidate.
"""

import re
from collections.abc import Mapping

import polars as pl

from glint.ingest.prices.symbols import is_common_listing
from glint.universe.tickers import is_derived

NonCommon = Mapping[str, frozenset[str]]  # CIK -> symbols that are never its primary ticker


def _candidates(
    tickers: list[str], exchange: str | None, not_common: frozenset[str] = frozenset()
) -> list[str]:
    symbols = {t.upper() for t in tickers}
    return [
        t
        for t in tickers
        if is_common_listing(t, exchange) and not is_derived(t, symbols) and t not in not_common
    ]


def finalize_primary(
    companies: pl.DataFrame, stats: pl.DataFrame, non_common: NonCommon | None = None
) -> pl.DataFrame:
    """`companies` with `primary_ticker` replaced and `primary_ticker_provisional` kept."""
    non_common = non_common or {}
    adv = dict(zip(stats["ticker"].to_list(), stats["avg_dollar_volume_3m"].to_list(), strict=True))
    picked: list[str | None] = []
    for cik, tickers, exchange, provisional in companies.select(
        "cik", "tickers", "exchange", "primary_ticker"
    ).iter_rows():
        cands = _candidates(list(tickers or []), exchange, non_common.get(cik, frozenset()))
        if provisional in cands:  # provisional first, so it wins ties
            cands = [provisional, *(t for t in cands if t != provisional)]
        priced = [(t, adv[t]) for t in cands if adv.get(t) is not None]
        if not priced:  # a configured non-common provisional gives way to an unpriced common one
            keep = provisional in cands or not cands
            picked.append(provisional if keep else cands[0])
            continue
        best = max(v for _, v in priced)
        picked.append(next(t for t, v in priced if v == best))
    return companies.with_columns(
        pl.col("primary_ticker").alias("primary_ticker_provisional"),
        pl.Series("primary_ticker", picked, dtype=pl.String),
    )


PREFERRED = re.compile(r"\.P[A-Z]?$")


def listing_kind(
    ticker: str | None,
    siblings: list[str],
    exchange: str | None,
    not_common: frozenset[str] = frozenset(),
) -> str | None:
    """'common', 'preferred' or 'other' for the primary ticker (price metrics need 'common')."""
    if ticker is None:
        return None
    if ticker in _candidates(siblings or [ticker], exchange, not_common):
        return "common"
    return "preferred" if PREFERRED.search(ticker) else "other"


def with_listing_kind(frame: pl.DataFrame, non_common: NonCommon | None = None) -> pl.DataFrame:
    non_common = non_common or {}
    rows = frame.select("cik", "primary_ticker", "tickers", "exchange").iter_rows()
    kinds = [
        listing_kind(t, list(ts or []), e, non_common.get(cik, frozenset()))
        for cik, t, ts, e in rows
    ]
    return frame.with_columns(pl.Series("listing_kind", kinds, dtype=pl.String))
