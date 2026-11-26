"""Provider symbol ↔ Glint canonical symbol.

Canonical form (shared with WT-01): upper case, suffixes after a dot.

| Listing        | Canonical | Massive  | Yahoo     | SEC (`company_tickers_exchange`) |
|----------------|-----------|----------|-----------|----------------------------------|
| common / class | `BRK.B`   | `BRK.B`  | `BRK-B`   | `BRK-B`                          |
| warrant        | `AAC.WS`  | `AAC.WS` | `AAC-WT`  | `AAC-WT`                         |
| unit           | `AAC.U`   | `AAC.U`  | `AAC-UN`  | `AAC-UN`                         |
| right          | `SOUL.R`  | `SOULr`  | `SOUL-R`  | `SOUL-RI`                        |
| preferred      | `ABR.PD`  | `ABRpD`  | `ABR-PD`  | `ABR-PD`                         |

(Conventions as observed in real responses on 2026-10-28/29.) Nasdaq also marks non-common
lines with a fifth letter (`BANFP`, `BCTXZ`); those keep their symbol and are recognised by
`is_common_listing`.
"""

import re

_MASSIVE_LOWER = re.compile(r"^([A-Z]+)(p|r|w)([A-Z]?)$")
_SEC_SUFFIX = {"WT": "WS", "WS": "WS", "UN": "U", "U": "U", "RI": "R", "RT": "R", "R": "R"}
_YAHOO_SUFFIX = {"WS": "WT", "U": "UN"}
_NON_COMMON_SUFFIX = re.compile(r"\.(WS|WT[A-Z]?|WI|U|R|W|P[A-Z]?)$")
_NASDAQ_FIFTH_LETTER = frozenset("WURPZ")


def canonical_from_massive(symbol: str) -> str:
    s = symbol.strip()
    m = _MASSIVE_LOWER.match(s)
    if m is None:
        return s
    base, mark, series = m.groups()
    suffix = {"p": "P", "r": "R", "w": "W"}[mark] + series  # w = when issued
    return f"{base}.{suffix}"


def to_massive(canonical: str) -> str:
    base, _, suffix = canonical.partition(".")
    if suffix.startswith("P") and len(suffix) <= 2:
        return f"{base}p{suffix[1:]}"
    if suffix in ("R", "W"):
        return f"{base}{suffix.lower()}"
    return canonical


def _dash_to_canonical(symbol: str) -> str:
    s = symbol.strip().upper()
    base, sep, suffix = s.partition("-")
    if not sep:
        return s
    return f"{base}.{_SEC_SUFFIX.get(suffix, suffix)}"


def canonical_from_yahoo(symbol: str) -> str:
    return _dash_to_canonical(symbol)


def to_yahoo(canonical: str) -> str:
    base, sep, suffix = canonical.partition(".")
    if not sep:
        return canonical
    return f"{base}-{_YAHOO_SUFFIX.get(suffix, suffix)}"


def canonical_from_sec(symbol: str) -> str:
    return _dash_to_canonical(symbol)


def is_common_listing(canonical: str, exchange: str | None = None) -> bool:
    """False for warrants, units, rights, when-issued lines and preferreds (share classes pass)."""
    if _NON_COMMON_SUFFIX.search(canonical):
        return False
    return not (
        exchange == "Nasdaq"
        and len(canonical) == 5
        and canonical.isalpha()
        and canonical[-1] in _NASDAQ_FIFTH_LETTER
    )
