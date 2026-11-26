"""Up-C detection from a filing's cover-page facts by class (WT-01). Pure.

In an Up-C (AVEX: listed Class A + voting-only Class B, each B share paired 1:1 with an LLC unit
exchangeable into Class A), the public company owns part of an operating LLC and consolidates
it, recording the rest as a noncontrolling interest. Its EPS and diluted share count cover the
listed class only, but every cover-page common class is an economic share (directly, or through
its paired unit), so market cap should count them all, priced at the listed class.

Rule (thresholds in config/sectors.yaml `up_c`): the filing reports 2+ common classes on its
cover page, and one class of at least `min_class_share` of the total has a share of the total
within `nci_tolerance` of a NCI ownership percentage the same filing tags
(`MinorityInterestOwnershipPercentageByNoncontrollingOwners`, latest date). AVEX: Class B
57,571,367 of 114,041,700 = 50.5%, tagged NCI 50.5%. An ordinary dual-class company (GOOGL, META,
BRK) tags no NCI percentage that matches a class. The minimum share drops coincidences with tiny
classes (ALIT, AMH, CHCI); 4% keeps PTLO (Class B 4.5%, NCI tagged on that class). Domestic filers
only: the caller passes covers from 10-K/10-Q filings.

The NCI percentage is also compared with the *rest* of the cover (1 − a class's share), for Up-Cs
with two unlisted classes paired with units (TWFG: Class B + Class C 76.2%, NCI 76.3%).

Some Up-Cs tag no usable NCI percentage (OWL, UTZ, VIRT, …); on the cover they look like DKNG,
whose Class B has no economics and no paired unit. Those are listed in `up_c.confirmed` with the
filing's own words on the 1:1 exchangeable units; the count is still the sum of the cover facts.
`up_c.excluded` lists multi-class filers that must never be summed (DKNG), and wins over both.
Two confirmed entries aren't classic Up-Cs but need the same count, named class by class: BLK
(common + subsidiary units exchangeable 1:1 into it, not its cover's fully diluted total) and SUN
(common + Class D units economically equivalent to them, not the Class C its subsidiaries hold).
"""

from dataclasses import dataclass
from datetime import date
from functools import cache

from pydantic import BaseModel, ConfigDict, Field, model_validator

from glint.ingest.sec.covers import Cover

_NOT_COMMON = ("Treasury", "Preferred", "Warrant", "Adr", "DepositaryShares")


class UpCExclude(BaseModel):
    """A multi-class filer whose extra class has no economics: never an Up-C."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    ticker: str
    source: str  # form, period and accession of the filing quoted
    quote: str  # the filing's own words


class UpCConfirm(UpCExclude):
    """An Up-C the NCI rule can't see (no usable NCI % tagged), confirmed from the filing's words.
    `classes` (cover-page class members, local names) restricts the sum; empty = every class.
    `structure` names what was confirmed when it isn't a classic Up-C (BLK's exchangeable
    subsidiary units, SUN's unlisted economically equivalent units); it goes in the evidence."""

    keyed_by: str
    classes: tuple[str, ...] = ()
    structure: str = "Up-C"


class UpCRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nci_tolerance: float = Field(gt=0, lt=1)
    min_class_share: float = Field(ge=0, lt=1)
    # review list only: the cover total must be at least this multiple of Glint's share count
    candidate_min_ratio: float = Field(gt=0)
    # a cover member within this fraction of the sum of 2+ other members is their total
    total_member_tolerance: float = Field(ge=0, lt=1)
    # review list only: a cover symbol on a member whose local name has one of these words
    # (case-insensitive) isn't a listed class (VGAS's warrant VGASW)
    non_equity_symbol_words: tuple[str, ...] = Field(min_length=1)
    confirmed: tuple[UpCConfirm, ...] = ()
    excluded: tuple[UpCExclude, ...] = ()

    @model_validator(mode="after")
    def _one_entry_per_cik(self) -> "UpCRule":
        ciks = [e.cik for e in (*self.confirmed, *self.excluded)]
        dupes = sorted({c for c in ciks if ciks.count(c) > 1})
        if dupes:
            raise ValueError(f"up_c: CIK listed more than once in confirmed/excluded: {dupes}")
        return self

    def confirmed_entry(self, cik: str) -> UpCConfirm | None:
        return next((e for e in self.confirmed if e.cik == cik), None)

    def is_excluded(self, cik: str) -> bool:
        return any(e.cik == cik for e in self.excluded)


@dataclass(frozen=True)
class UpC:
    economic_shares: float  # sum of the cover-page common classes
    as_of: date  # cover-page date
    accn: str
    filed: date
    evidence: str


def _label(member: str | None) -> str:
    if member is None:
        return "undimensioned"
    local = member.split(":")[-1]
    return local.removesuffix("Member")


def _combined(local: str, others: set[str]) -> bool:
    """`CommonClassAAndCommonClassB` when CommonClassA and CommonClassB are both present."""
    return any(f"{a}And{b}" == local for a in others for b in others if a != b)


@cache
def _configured_total_tolerance() -> float:
    from glint.universe.classify import load_rules  # noqa: PLC0415 (classify imports upc)

    return load_rules().up_c.total_member_tolerance


def _drop_total(by_member: dict[str | None, float], tolerance: float) -> None:
    """With 3+ class members, drop one whose shares equal the sum of all the others within
    `tolerance` (relative): it is their total (GCT's `CommonStockMember` = Class A + Class B)."""
    members = [m for m in by_member if m is not None]
    if len(members) < 3:
        return
    for m in members:
        rest = sum(by_member[k] for k in members if k != m)
        if rest > 0 and abs(by_member[m] - rest) <= tolerance * rest:
            by_member.pop(m)
            return


def common_classes(cover: Cover, total_tolerance: float | None = None) -> dict[str | None, float]:
    """Common classes on the cover page. With 2+ class members, an undimensioned count is a
    total (or a duplicate) and is left out; with one member it counts as another class. A member
    naming two other present members joined by "And" (ZETA's `CommonClassAAndCommonClassB`) is
    their total and is left out too, and so is a member whose shares equal the sum of 2+ other
    members within `total_tolerance` (GCT and KNSA tag `CommonStockMember` next to their classes;
    None: `up_c.total_member_tolerance` from config/sectors.yaml)."""
    by_member: dict[str | None, float] = {}
    for c in cover.classes:
        if c.member is not None and any(word in c.member for word in _NOT_COMMON):
            continue
        by_member[c.member] = max(c.shares, by_member.get(c.member, 0.0))
    members = [m for m in by_member if m is not None]
    if len(members) >= 2:
        by_member.pop(None, None)
    locals_ = {m: _label(m) for m in members}
    for m, local in locals_.items():
        if _combined(local, {v for k, v in locals_.items() if k != m}):
            by_member.pop(m)
    tolerance = _configured_total_tolerance() if total_tolerance is None else total_tolerance
    _drop_total(by_member, tolerance)
    return by_member


def _parts(classes: dict[str | None, float]) -> str:
    return " + ".join(f"{_label(m)} {v:,.0f}" for m, v in classes.items())


def _as_of(cover: Cover, classes: dict[str | None, float]) -> date:
    return max(c.as_of for c in cover.classes if c.member in classes)


def detect_up_c(cover: Cover, rule: UpCRule) -> UpC | None:
    classes = common_classes(cover, rule.total_member_tolerance)
    total = sum(classes.values())
    if len(classes) < 2 or total <= 0 or not cover.nci:
        return None
    latest = max(n.end for n in cover.nci)
    tagged = [n.value for n in cover.nci if n.end == latest and 0 < n.value < 1]
    # (gap, member, matched share, NCI %, complement?): a class's share, or the rest of the cover
    candidates: list[tuple[float, str | None, float, float, bool]] = []
    for v in tagged:
        for member, shares in classes.items():
            share = shares / total
            if share >= rule.min_class_share:
                candidates.append((abs(v - share), member, share, v, False))
            if len(classes) > 2 and 1 - share >= rule.min_class_share:
                candidates.append((abs(v - (1 - share)), member, 1 - share, v, True))
    if not candidates:
        return None
    gap, member, matched, nci, rest = min(candidates, key=lambda x: (x[0], x[4], str(x[1])))
    if gap > rule.nci_tolerance:
        return None
    as_of = _as_of(cover, classes)
    which = (
        f"the classes other than {_label(member)} are {matched:.1%}"
        if rest
        else f"{_label(member)} is {matched:.1%}"
    )
    evidence = (
        f"{cover.form} {cover.accn}: cover page {_parts(classes)} = {total:,.0f} shares at "
        f"{as_of}; {which} of the total and the filing tags NCI ownership {nci:.1%} at {latest} "
        f"(MinorityInterestOwnershipPercentageByNoncontrollingOwners)"
    )
    return UpC(total, as_of, cover.accn, cover.filed, evidence)


def confirmed_up_c(cover: Cover, entry: UpCConfirm) -> UpC | None:
    """A confirmed Up-C's economic count: the sum of its cover-page common classes (only the
    named ones when `entry.classes` is set). None when the cover has fewer than 2 common classes
    or lacks a named class: a changed cover needs a person to look again, not a partial sum."""
    classes = common_classes(cover)
    if entry.classes:
        by_label = {_label(m): m for m in classes}
        if any(c not in by_label for c in entry.classes):
            return None
        classes = {by_label[c]: classes[by_label[c]] for c in entry.classes}
    total = sum(classes.values())
    if len(classes) < 2 or total <= 0:
        return None
    as_of = _as_of(cover, classes)
    evidence = (
        f"{cover.form} {cover.accn}: cover page {_parts(classes)} = {total:,.0f} shares at "
        f"{as_of}; confirmed {entry.structure} (config/sectors.yaml up_c.confirmed), "
        f"{entry.source}: "
        f"\u201c{entry.quote}\u201d"
    )
    return UpC(total, as_of, cover.accn, cover.filed, evidence)


def listed_class_symbols(cover: Cover, rule: UpCRule) -> set[str]:
    """The cover's trading symbols, less those on a member whose local name contains one of
    `rule.non_equity_symbol_words` (case-insensitive): a warrant, right, preferred, depositary
    share or note symbol is not a listed common class. An undimensioned symbol always counts."""
    words = [w.lower() for w in rule.non_equity_symbol_words]
    return {
        sym
        for member, sym in cover.symbols.items()
        if sym and not any(w in member.split(":")[-1].lower() for w in words)
    }


def review_candidate(cover: Cover, rule: UpCRule, glint_shares: float | None) -> str | None:
    """A multi-class cover the Up-C logic leaves alone that a person should look at: 2+ common
    classes of at least `min_class_share` each, at most one of them listed, and neither detected,
    confirmed nor excluded. Up-Cs with no NCI tag look like this, and so do voting-only classes
    (DKNG) and ordinary dual-class companies with an unlisted class (META), so it's a list to
    read, not a rule. `glint_shares` is Glint's latest `shares_outstanding` (None: no count):
    when the cover total is under `candidate_min_ratio` × that count, Glint's count already
    includes the other classes, so summing the cover would change nothing worth reviewing.
    Symbols on warrants and other non-equity members don't count as listed classes
    (`listed_class_symbols`). Returns what the cover shows, or None."""
    if rule.is_excluded(cover.cik) or rule.confirmed_entry(cover.cik) is not None:
        return None
    classes = common_classes(cover, rule.total_member_tolerance)
    total = sum(classes.values())
    if total <= 0 or sum(v / total >= rule.min_class_share for v in classes.values()) < 2:
        return None
    if glint_shares is not None and total < rule.candidate_min_ratio * glint_shares:
        return None
    if len(listed_class_symbols(cover, rule)) > 1 or detect_up_c(cover, rule) is not None:
        return None
    shares = ", ".join(f"{_label(m)} {v / total:.1%}" for m, v in classes.items())
    nci = sorted({n.value for n in cover.nci if 0 < n.value < 1})
    tagged = ", ".join(f"{v:.1%}" for v in nci) if nci else "none tagged"
    return f"{cover.form} {cover.accn}: {shares} of {total:,.0f}; NCI % {tagged}"
