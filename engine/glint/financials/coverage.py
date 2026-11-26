"""Gaps with reasons per company, and coverage per line item across many companies. Pure.

A gap is a line item with no value at the company's latest period for a basis. Every gap has a
reason code (§2.4): NOT_APPLICABLE_SECTOR (n/m by design, e.g. a bank's gross profit),
INSUFFICIENT_HISTORY (no 4 contiguous quarters, or a fiscal-year change), or MISSING_INPUT
(nothing tagged or derivable for that period; the message names the tags tried).
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from glint.contracts.enums import Basis, LineItem, NoteCode, PeriodKind, Sector
from glint.financials.concepts import ConceptMap
from glint.financials.instants import one_year_before
from glint.financials.normalize import CompanyFinancials


class Group(StrEnum):
    """Coverage report columns (WT-03 step 9)."""

    DOMESTIC = "domestic non-financial"
    FINANCIAL = "financial"
    FOREIGN = "foreign"


@dataclass(frozen=True, slots=True)
class Gap:
    item: LineItem
    code: NoteCode
    message: str


def latest_end(cf: CompanyFinancials, basis: Basis) -> date | None:
    """The company's latest period end for a basis, across every line item."""
    if basis is Basis.FY:
        return cf.fy_ends[-1] if cf.fy_ends else None
    if basis is Basis.MRQ:
        return cf.balance_sheet_date
    source = cf.ttm if basis is Basis.TTM else cf.q
    return max((e for s in source.values() for e in s), default=None)


def _flow_basis(concepts: ConceptMap, item: LineItem, basis: Basis) -> Basis:
    """Instants are read at MRQ when flows are read at TTM/Q; FY stays FY. The share count is
    a cover-page figure dated after the balance sheet, so it's always read at MRQ."""
    if item is LineItem.SHARES_OUTSTANDING:
        return Basis.MRQ
    if concepts[item].kind is PeriodKind.INSTANT and basis is not Basis.FY:
        return Basis.MRQ
    return basis


def _end_for(cf: CompanyFinancials, item: LineItem, basis: Basis) -> date | None:
    """The period end a current value must have. The share count is current at its own latest
    date unless it's stale; everything else at the company's latest end for the basis."""
    if item is LineItem.SHARES_OUTSTANDING:
        v = cf.latest(item, Basis.MRQ)
        return v.period.end if v is not None and not cf.shares_stale else latest_end(cf, basis)
    return latest_end(cf, basis)


def gaps(
    cf: CompanyFinancials,
    concepts: ConceptMap,
    items: Iterable[LineItem],
    basis: Basis,
    sector: Sector | None = None,
) -> dict[LineItem, Gap]:
    """Items without a value at the latest period for `basis` (instants: MRQ unless FY)."""
    out: dict[LineItem, Gap] = {}
    for item in items:
        b = _flow_basis(concepts, item, basis)
        end = _end_for(cf, item, b)
        series = cf.series(item, b)
        if end is not None and end in series:
            continue
        c = concepts[item]
        if sector is not None and sector in c.not_applicable:
            out[item] = Gap(item, NoteCode.NOT_APPLICABLE_SECTOR, f"{item} is n/a for {sector}")
        elif end is None:
            out[item] = Gap(item, NoteCode.INSUFFICIENT_HISTORY, f"{item}: no {b} period filed yet")
        elif b is Basis.TTM and _reported_within_a_year(cf, item, end):
            why = (
                f"fiscal-year change (transition {cf.fy_changes[-1].transition.label()})"
                if cf.fy_changes
                else "no 4 contiguous quarters"
            )
            out[item] = Gap(item, NoteCode.INSUFFICIENT_HISTORY, f"{item}: {why} to {end}")
        else:
            out[item] = Gap(item, NoteCode.MISSING_INPUT, _missing_message(cf, concepts, item, end))
    return out


def _reported_within_a_year(cf: CompanyFinancials, item: LineItem, end: date) -> bool:
    since = one_year_before(end)
    return any(e > since for b in (Basis.FY, Basis.Q) for e in cf.series(item, b))


def _missing_message(cf: CompanyFinancials, concepts: ConceptMap, item: LineItem, end: date) -> str:
    c = concepts[item]
    tags = [t for _, t in c.tags_for(cf.taxonomy)]
    tried = ", ".join(tags) if tags else "no tags"
    if c.derive is not None:
        tried += f"; derive {c.derive}"
    known = [e for b in (Basis.FY, Basis.Q, Basis.TTM, Basis.MRQ) for e in cf.series(item, b)]
    last = f"; latest value {max(known)}" if known else ""
    note = f". {c.note}" if c.note else ""
    return f"{item}: nothing for {end} ({tried}{last}){note}"


@dataclass
class CoverageReport:
    """% of companies with a value, per line item and group."""

    basis: Basis
    companies: Counter[Group] = field(default_factory=Counter[Group])
    present: dict[LineItem, Counter[Group]] = field(default_factory=dict[LineItem, Counter[Group]])
    tags: dict[LineItem, Counter[str]] = field(default_factory=dict[LineItem, Counter[str]])

    def share(self, item: LineItem, group: Group) -> float | None:
        n = self.companies[group]
        return self.present.get(item, Counter[Group]())[group] / n if n else None

    def core_share(self, core: Iterable[LineItem], group: Group) -> float | None:
        """Mean coverage over the core items."""
        shares = [s for i in core if (s := self.share(i, group)) is not None]
        return sum(shares) / len(shares) if shares else None


def add_company(
    report: CoverageReport, group: Group, cf: CompanyFinancials, concepts: ConceptMap
) -> None:
    """Count one company into `report` (so a universe build never holds every company)."""
    report.companies[group] += 1
    for item in concepts.concepts:
        b = _flow_basis(concepts, item, report.basis)
        end = _end_for(cf, item, b)
        v = cf.series(item, b).get(end) if end else None
        if v is not None:
            report.present.setdefault(item, Counter())[group] += 1
            # Summed TTMs carry no single tag: attribute the latest FY (or MRQ) value's tag.
            src = v if v.source_tag or v.derived else cf.latest(item, Basis.FY) or v
            report.tags.setdefault(item, Counter())[src.source_tag or "derived"] += 1


def coverage(
    companies: Iterable[tuple[Group, CompanyFinancials]],
    concepts: ConceptMap,
    basis: Basis = Basis.TTM,
) -> CoverageReport:
    report = CoverageReport(basis=basis)
    for group, cf in companies:
        add_company(report, group, cf, concepts)
    return report
