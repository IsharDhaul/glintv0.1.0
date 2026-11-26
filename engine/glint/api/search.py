"""Ticker and name search (§5.5): exact ticker → ticker prefix → name prefix → fuzzy name.

Tickers compare on letters and digits only, so "brk b", "BRK-B" and "brk.b" all mean BRK.B.
Within a tier, larger companies come first (market cap, nulls last), then ticker A→Z.
"""

import re
from dataclasses import dataclass

import duckdb
from rapidfuzz import fuzz, process, utils

from glint.contracts.api import MatchType, SearchHit
from glint.contracts.enums import Exchange, Kind, Sector

MAX_RESULTS = 10
FUZZY_CUTOFF = 70.0  # rapidfuzz WRatio, 0–100; "appel" → "Apple Inc." scores 80
TIER_SCORES = {MatchType.EXACT: 100.0, MatchType.TICKER_PREFIX: 95.0, MatchType.NAME_PREFIX: 90.0}

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def ticker_key(text: str) -> str:
    return _NON_ALNUM.sub("", text.upper())


@dataclass(frozen=True)
class Entry:
    cik: str
    name: str
    name_key: str
    tickers: tuple[str, ...]
    ticker_keys: tuple[str, ...]
    primary_ticker: str | None
    exchange: Exchange | None
    sector: Sector
    kind: Kind
    market_cap: float | None

    @property
    def display_ticker(self) -> str:
        return self.primary_ticker or (self.tickers[0] if self.tickers else "")

    def hit(self, match: MatchType, score: float, ticker: str | None = None) -> SearchHit:
        return SearchHit(
            cik=self.cik,
            ticker=ticker or self.display_ticker,
            name=self.name,
            exchange=self.exchange,
            sector=self.sector,
            kind=self.kind,
            match=match,
            score=score,
        )


class SearchIndex:
    def __init__(self, entries: list[Entry]) -> None:
        # Bigger first, then ticker: the order every tier keeps.
        self.entries = sorted(
            entries, key=lambda e: (e.market_cap is None, -(e.market_cap or 0.0), e.display_ticker)
        )
        self._names = [e.name_key for e in self.entries]
        self._by_ticker: dict[str, list[tuple[Entry, str]]] = {}
        for e in self.entries:
            for t, k in zip(e.tickers, e.ticker_keys, strict=True):
                self._by_ticker.setdefault(k, []).append((e, t))

    @classmethod
    def from_connection(cls, con: duckdb.DuckDBPyConnection) -> "SearchIndex":
        rows = con.execute(
            "SELECT c.cik, c.name, c.tickers, c.primary_ticker, c.exchange, c.sector, c.kind, "
            "       s.market_cap "
            "FROM companies c LEFT JOIN metrics_snapshot s USING (cik)"
        ).fetchall()
        return cls(
            [
                Entry(
                    cik=cik,
                    name=name,
                    name_key=utils.default_process(name),
                    tickers=tuple(tickers),
                    ticker_keys=tuple(ticker_key(t) for t in tickers),
                    primary_ticker=primary,
                    exchange=Exchange(exchange) if exchange else None,
                    sector=Sector(sector),
                    kind=Kind(kind),
                    market_cap=market_cap,
                )
                for cik, name, tickers, primary, exchange, sector, kind, market_cap in rows
            ]
        )

    def lookup(self, ticker: str) -> tuple[Entry, str] | None:
        """The company listing `ticker` (any share class) and the ticker as stored. An exact
        stored ticker wins over a punctuation-insensitive match (`BRKB` vs `BRK.B`)."""
        found = self._by_ticker.get(ticker_key(ticker), [])
        wanted = ticker.strip().upper()
        exact = [(e, t) for e, t in found if t.upper() == wanted]
        return (exact or found or [None])[0]

    def search(self, query: str, limit: int = MAX_RESULTS) -> list[SearchHit]:
        q_ticker, q_name = ticker_key(query), utils.default_process(query)
        hits: list[SearchHit] = []
        seen: set[str] = set()

        def add(entry: Entry, match: MatchType, score: float, ticker: str | None = None) -> bool:
            if entry.cik not in seen:
                seen.add(entry.cik)
                hits.append(entry.hit(match, score, ticker))
            return len(hits) >= limit

        if q_ticker:
            wanted = query.strip().upper()
            exact = self._by_ticker.get(q_ticker, [])
            # A stored ticker typed exactly comes before one that only matches without punctuation.
            for e, t in sorted(exact, key=lambda et: et[1].upper() != wanted):
                if add(e, MatchType.EXACT, TIER_SCORES[MatchType.EXACT], t):
                    return hits
            for e in self.entries:
                prefixed = [
                    t
                    for t, k in zip(e.tickers, e.ticker_keys, strict=True)
                    if k.startswith(q_ticker) and k != q_ticker
                ]
                if prefixed and add(
                    e, MatchType.TICKER_PREFIX, TIER_SCORES[MatchType.TICKER_PREFIX], prefixed[0]
                ):
                    return hits
        if q_name:
            for e in self.entries:
                if e.name_key.startswith(q_name) and add(
                    e, MatchType.NAME_PREFIX, TIER_SCORES[MatchType.NAME_PREFIX]
                ):
                    return hits
            fuzzy = process.extract(
                q_name,
                self._names,
                scorer=fuzz.WRatio,
                processor=None,
                score_cutoff=FUZZY_CUTOFF,
                limit=None,
            )
            # Stable on ties: `self.entries` is already bigger-first.
            for _, score, i in sorted(fuzzy, key=lambda t: (-t[1], t[2])):
                if add(self.entries[i], MatchType.FUZZY, round(float(score), 1)):
                    return hits
        return hits
