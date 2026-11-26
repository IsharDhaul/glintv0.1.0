"""Ticker map from company_tickers_exchange.json (WT-01 step 4). Pure functions.

- Canonical symbols use a dot for classes (`BRK.B`); the SEC spelling (`BRK-B`) is kept as given.
- One row per CIK with every ticker, in SEC-file order.
- Provisional `primary_ticker`: the first common-stock ticker (not a preferred, warrant, unit or
  right) on the CIK's best exchange, in SEC-file order. WT-06 finalizes it by liquidity.
  With no common-stock ticker at all it falls back to the first ticker, and `has_common` is
  false: classify makes such a CIK `no_common_equity`.
- `exchange` is the primary ticker's exchange, normalized to the `Exchange` enum. Labels outside
  the enum give `exchange=None` and are kept in `sec_exchange`.
- OTC listings are kept (with their exchange); the default universe excludes them.
"""

import re
from dataclasses import dataclass
from typing import Any

from glint.contracts.enums import DEFAULT_EXCHANGES, Exchange

# Preferreds (-PA…-PZ, -P), warrants (-WS/-WT), units (-U/-UN), rights (-R/-RI/-RT).
NON_COMMON = re.compile(r"-(P[A-Z]?|WS|WT|U|UN|R|RI|RT)$")
NASDAQ_DERIVED_SUFFIX = frozenset("WURP")
_EXCHANGES = {e.value: e for e in Exchange}
# Lower is better when choosing the primary listing.
_RANK: dict[Exchange | None, int] = {
    **dict.fromkeys(DEFAULT_EXCHANGES, 0),
    Exchange.CBOE: 1,
    None: 2,
    Exchange.OTC: 3,
}


def canonical_symbol(sec_symbol: str) -> str:
    return sec_symbol.strip().upper().replace("-", ".")


def is_common(sec_symbol: str) -> bool:
    return NON_COMMON.search(sec_symbol.upper()) is None


def normalize_exchange(label: str | None) -> Exchange | None:
    return _EXCHANGES.get(label) if label else None


@dataclass(frozen=True)
class Listing:
    sec_symbol: str
    ticker: str
    exchange: Exchange | None
    sec_exchange: str | None


@dataclass(frozen=True)
class TickerInfo:
    cik: str
    sec_name: str
    listings: list[Listing]
    primary: Listing
    has_common: bool = True  # false: every ticker is a preferred, warrant, unit or right

    @property
    def tickers(self) -> list[str]:
        return [listing.ticker for listing in self.listings]

    @property
    def sec_symbols(self) -> list[str]:
        return [listing.sec_symbol for listing in self.listings]


def is_derived(sec_symbol: str, siblings: set[str]) -> bool:
    """Nasdaq style: another listing's symbol plus W/U/R/P (warrant, unit, right, preferred),
    e.g. ABLVW next to ABLV, AGNCP next to AGNC."""
    s = sec_symbol.upper()
    return len(s) >= 2 and s[-1] in NASDAQ_DERIVED_SUFFIX and s[:-1] in siblings


def common_listings(listings: list[Listing]) -> list[Listing]:
    symbols = {x.sec_symbol.upper() for x in listings}
    return [
        x for x in listings if is_common(x.sec_symbol) and not is_derived(x.sec_symbol, symbols)
    ]


def _pick_primary(listings: list[Listing]) -> Listing:
    common = common_listings(listings) or listings
    best = min(_RANK[x.exchange] for x in common)
    return next(x for x in common if _RANK[x.exchange] == best)


def build_ticker_map(doc: dict[str, Any]) -> dict[str, TickerInfo]:
    """company_tickers_exchange.json → TickerInfo by 10-digit CIK."""
    idx = {f: i for i, f in enumerate(doc["fields"])}
    rows: list[list[Any]] = doc["data"]
    grouped: dict[str, tuple[str, list[Listing]]] = {}
    for r in rows:
        cik = f"{int(r[idx['cik']]):010d}"
        sec_symbol = str(r[idx["ticker"]])
        label = r[idx["exchange"]]
        listing = Listing(
            sec_symbol=sec_symbol,
            ticker=canonical_symbol(sec_symbol),
            exchange=normalize_exchange(label),
            sec_exchange=str(label) if label else None,
        )
        _, listings = grouped.setdefault(cik, (str(r[idx["name"]]), []))
        if listing.ticker not in {x.ticker for x in listings}:
            listings.append(listing)
    return {
        cik: TickerInfo(
            cik=cik,
            sec_name=name,
            listings=listings,
            primary=_pick_primary(listings),
            has_common=bool(common_listings(listings)),
        )
        for cik, (name, listings) in grouped.items()
    }


def ticker_index(tmap: dict[str, TickerInfo]) -> dict[str, str]:
    """Canonical ticker → CIK (for lookups like `glint universe BRK.B`)."""
    return {t: info.cik for info in tmap.values() for t in info.tickers}
