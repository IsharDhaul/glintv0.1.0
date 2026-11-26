"""Separately listed share classes from a filing's cover page (WT-01). Pure.

A multi-class company whose classes each trade under their own symbol (HEI/HEI.A, LEN/LEN.B,
BRK.A/BRK.B) has one market cap per listing; the company's is their sum, each class priced at its
own close. The cover page of the latest 10-K/10-Q states every class's shares
(`dei:EntityCommonStockSharesOutstanding` by `StatementClassOfStockAxis`) and its symbol
(`dei:TradingSymbol` on the same member), so no person needs to key them.

Rule: 2+ common classes (`upc.common_classes`) with shares > 0, and every one of them has a
trading symbol on the cover. An unlisted class (GOOGL's Class B, META's Class B) may not be
economic, and pricing it at a listed close would assume it is, so the company gets nothing unless
config/share_classes.yaml `unlisted_economic` names that class with the filing's own words that it
has the same dividend and liquidation rights as the listed one (votes and conversion aside). Then
the unlisted class is a record too, priced at the listed class it converts into (`priced_at`,
symbol ""), and its count is the cover's, so it never goes stale. The listed classes of such a
company take their own cover symbol, or the cover's one undimensioned `dei:TradingSymbol` when
exactly one listed class has none (META, HUBG tag the symbol without a class). A named member
missing from the cover, a class neither listed nor named, or a `priced_at` that isn't one of the
listed classes: no records (logged), and the single count stays. `non_economic` members (SHOP's
Founder Share) are left out of the sum, with the filing's words. Up-Cs get nothing either
(`is_up_c` wins; their count is the summed cover classes).

Some covers give no class a symbol Glint reads (NC and RPC tag `dei:TradingSymbol` only by
listing exchange, TAP by class and exchange, and `parse_instance` keeps symbols on the class axis
alone): `cover_symbols` in config/share_classes.yaml gives each class's symbol from the 10-K
cover's "Title of each class / Trading Symbol(s)" table, quoted verbatim. A class the cover tags
no symbol for takes the configured one; the cover's own tag always wins, and this comes before
the undimensioned-symbol fallback above. A configured member that isn't on the cover is logged
(`cover_symbols_member_missing`) and ignored, and the rules above decide as usual. A configured
symbol only says which class is listed: an unlisted class still needs its `unlisted_economic`
quote, so NC (Class A listed, Class B not) needs both, and RPC, with only the symbol, keeps its
single count. TAP is `cover_excluded`: its cover misses the exchangeable shares.

The cover's symbol is matched to one of the company's own SEC tickers so it meets the price
data: the canonical spelling first (CRD-A → CRD.A), else the one ticker equal to it with the
punctuation removed (Brown-Forman's cover says BFA/BFB, SEC lists BF.A/BF.B).

Some registrants list things that aren't classes of one equity (separate commodity funds, debt,
operating-partnership unit series): `cover_excluded` in config/share_classes.yaml names them with
the evidence, and wins.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from glint.core.log import get_logger, log_event
from glint.core.settings import REPO_ROOT
from glint.ingest.sec.covers import Cover
from glint.universe.tickers import canonical_symbol
from glint.universe.upc import common_classes

log = get_logger(__name__)

SHARE_CLASSES_PATH = REPO_ROOT / "config" / "share_classes.yaml"
EXCLUDED_KEY = "cover_excluded"
UNLISTED_KEY = "unlisted_economic"
SYMBOLS_KEY = "cover_symbols"
NON_COMMON_KEY = "non_common_symbols"
_PUNCT = re.compile(r"[^A-Z0-9]")


class ListedClassExclude(BaseModel):
    """A registrant whose cover-listed classes must never be summed into one market cap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    ticker: str
    reason: str  # what the listings are, with the filing it comes from


def load_exclusions(path: Path = SHARE_CLASSES_PATH) -> dict[str, ListedClassExclude]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    raw: list[Any] = doc.get(EXCLUDED_KEY) or []
    entries = [ListedClassExclude.model_validate(e) for e in raw]
    return {e.cik: e for e in entries}


class UnlistedMember(BaseModel):
    """An unlisted cover class and the listed ticker it is priced at (the class it converts into,
    per the filing)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    member: str  # StatementClassOfStockAxis member, e.g. us-gaap:CommonClassBMember
    priced_at: str  # one of the company's listed tickers


class NonEconomicMember(BaseModel):
    """A cover class with no economic rights (votes only): never summed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    member: str
    quote: str  # the filing's words


class UnlistedEconomic(BaseModel):
    """A company whose unlisted class(es) the filing says share the listed class's economics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    ticker: str
    source: str  # filing, form and section the quote comes from
    accn: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    quote: str = Field(min_length=40)  # verbatim: same dividend/liquidation rights, votes aside
    conversion: str | None = None  # verbatim, when the filing states one; never invented
    classes: list[UnlistedMember] = Field(min_length=1)
    non_economic: list[NonEconomicMember] = []
    checked_by: str

    @model_validator(mode="after")
    def _members_once(self) -> "UnlistedEconomic":
        members = [c.member for c in self.classes] + [c.member for c in self.non_economic]
        if len(set(members)) < len(members):
            raise ValueError(f"{self.ticker}: a member is named twice")
        return self


def load_unlisted_economic(path: Path = SHARE_CLASSES_PATH) -> dict[str, UnlistedEconomic]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    raw: list[Any] = doc.get(UNLISTED_KEY) or []
    entries = [UnlistedEconomic.model_validate(e) for e in raw]
    out = {e.cik: e for e in entries}
    if len(out) < len(entries):
        raise ValueError(f"{path.name}: one `{UNLISTED_KEY}` entry per CIK")
    return out


@cache
def _configured_unlisted() -> dict[str, UnlistedEconomic]:
    return load_unlisted_economic()


class CoverSymbols(BaseModel):
    """A company whose cover XBRL tags no trading symbol on its classes: each class's symbol from
    the 10-K cover's "Title of each class / Trading Symbol(s)" table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    ticker: str
    accn: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    source: str  # filing and section the quote comes from
    quote: str = Field(min_length=20)  # verbatim rows of the cover's registered-securities table
    symbols: dict[str, str] = Field(min_length=1)  # StatementClassOfStockAxis member -> symbol
    checked_by: str

    @model_validator(mode="after")
    def _one_symbol_per_member(self) -> "CoverSymbols":
        values = [v.strip() for v in self.symbols.values()]
        if not all(values) or not all(m.strip() for m in self.symbols):
            raise ValueError(f"{self.ticker}: a blank member or symbol")
        if len(set(values)) < len(values):
            raise ValueError(f"{self.ticker}: two members on one symbol")
        return self


def load_cover_symbols(path: Path = SHARE_CLASSES_PATH) -> dict[str, CoverSymbols]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    raw: list[Any] = doc.get(SYMBOLS_KEY) or []
    entries = [CoverSymbols.model_validate(e) for e in raw]
    out = {e.cik: e for e in entries}
    if len(out) < len(entries):
        raise ValueError(f"{path.name}: one `{SYMBOLS_KEY}` entry per CIK")
    return out


@cache
def _configured_symbols() -> dict[str, CoverSymbols]:
    return load_cover_symbols()


class NonCommonSymbol(BaseModel):
    """A symbol the cover lists on a preferred or note row, with no suffix that marks it as one
    (Strive's SATS): never the primary ticker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    ticker: str  # the company's common listing
    symbol: str
    accn: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    source: str
    quote: str = Field(min_length=20)  # the cover's registered-securities row, verbatim
    checked_by: str

    @model_validator(mode="after")
    def _quote_names_symbol(self) -> "NonCommonSymbol":
        if self.symbol == self.ticker or self.symbol not in self.quote:
            raise ValueError(f"{self.ticker}: {self.symbol} must differ and appear in the quote")
        return self


def load_non_common_symbols(path: Path = SHARE_CLASSES_PATH) -> dict[str, frozenset[str]]:
    """CIK -> symbols that are never its primary ticker (canonical form)."""
    doc: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    raw: list[Any] = doc.get(NON_COMMON_KEY) or []
    entries = [NonCommonSymbol.model_validate(e) for e in raw]
    out: dict[str, set[str]] = {}
    for e in entries:
        sym = canonical_symbol(e.symbol)
        if sym in out.get(e.cik, set()):
            raise ValueError(f"{path.name}: {e.symbol} listed twice in `{NON_COMMON_KEY}`")
        out.setdefault(e.cik, set()).add(sym)
    return {cik: frozenset(s) for cik, s in out.items()}


@dataclass(frozen=True)
class ListedClass:
    ticker: str  # one of the company's SEC tickers when the symbol matches one
    symbol: str  # as the cover states it; "" for an unlisted class priced at `ticker`
    member: str  # StatementClassOfStockAxis member
    shares: float
    as_of: date  # cover-page date of this class's count
    accn: str
    form: str


def match_ticker(symbol: str, tickers: list[str]) -> str:
    """The company's ticker for a cover symbol: canonical spelling, else the unique ticker equal
    to it without punctuation, else the canonical spelling (it then finds no price)."""
    canon = canonical_symbol(symbol)
    if canon in tickers:
        return canon
    bare = _PUNCT.sub("", canon)
    hits = [t for t in tickers if _PUNCT.sub("", t.upper()) == bare]
    return hits[0] if len(hits) == 1 else canon


def listed_classes(
    cover: Cover,
    tickers: list[str],
    *,
    is_up_c: bool,
    excluded: frozenset[str] = frozenset(),
    unlisted: Mapping[str, UnlistedEconomic] | None = None,
    cover_symbols: Mapping[str, CoverSymbols] | None = None,
) -> list[ListedClass]:
    """One record per cover class when every common class with shares is separately listed or is
    named in `unlisted` (default: config/share_classes.yaml `unlisted_economic`); otherwise none.
    A class the cover tags no symbol for takes its `cover_symbols` one (default: the same yaml).
    The caller passes the latest 10-K/10-Q cover of a domestic filer."""
    if is_up_c or cover.cik in excluded:
        return []
    entry = (_configured_unlisted() if unlisted is None else unlisted).get(cover.cik)
    skip: set[str] = {n.member for n in entry.non_economic} if entry else set()
    classes = {m: v for m, v in common_classes(cover).items() if v > 0 and m not in skip}
    if len(classes) < 2 or None in classes:
        return []
    named = {u.member: u for u in entry.classes} if entry else {}
    if missing := [m for m in named if m not in classes]:
        return _no_entry(cover, entry, "named member not on the latest cover", missing)
    members = [m for m in classes if m is not None]
    symbols = {m: (cover.symbols.get(m) or "").strip() for m in members if m not in named}
    keyed = (_configured_symbols() if cover_symbols is None else cover_symbols).get(cover.cik)
    if keyed is not None:  # the 10-K cover table's symbol, for a class the XBRL tags none for
        symbols = {m: sym or keyed.symbols.get(m, "").strip() for m, sym in symbols.items()}
        on_cover = {c.member for c in cover.classes}
        if off := [m for m in keyed.symbols if m not in on_cover]:
            log_event(log, "cover_symbols_member_missing", cik=cover.cik, ticker=keyed.ticker,
                      accn=cover.accn, members=off)  # fmt: skip
    blank = [m for m, sym in symbols.items() if not sym]
    shared = (cover.symbols.get("") or "").strip()
    if entry and len(blank) == 1 and shared and shared not in symbols.values():
        symbols[blank[0]] = shared  # the cover's one symbol, tagged without a class
        blank = []
    if blank:
        return _no_entry(cover, entry, "a class is neither listed nor named", blank)
    if not symbols:
        return _no_entry(cover, entry, "no listed class to price at", list(named))
    as_of: dict[str | None, date] = {}
    for c in cover.classes:  # the date of the count common_classes kept (the largest)
        if c.member in classes and c.shares == classes[c.member]:
            as_of[c.member] = max(c.as_of, as_of.get(c.member, c.as_of))

    def record(m: str, ticker: str, symbol: str) -> ListedClass:
        return ListedClass(ticker, symbol, m, classes[m], as_of[m], cover.accn, cover.form)

    listed = [record(m, match_ticker(sym, tickers), sym) for m, sym in symbols.items()]
    if len({c.ticker for c in listed}) < len(listed):  # two classes on one symbol: not separate
        return []
    at = {c.ticker for c in listed}
    priced = {m: match_ticker(u.priced_at, tickers) for m, u in named.items()}
    if wrong := [m for m, t in priced.items() if t not in at]:
        return _no_entry(cover, entry, "priced_at is not a listed class on the cover", wrong)
    return listed + [record(m, priced[m], "") for m in named]


def _no_entry(
    cover: Cover, entry: UnlistedEconomic | None, reason: str, members: list[Any]
) -> list[ListedClass]:
    """No records; for a configured company, say why (its single count stays)."""
    if entry is not None:
        log_event(log, "unlisted_economic_skipped", cik=cover.cik, ticker=entry.ticker,
                  accn=cover.accn, reason=reason, members=members)  # fmt: skip
    return []
