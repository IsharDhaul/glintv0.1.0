"""Raw facts for one company → FY / Q / TTM / instant series per line item, with sources."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from glint.contracts.enums import Basis, LineItem, PeriodKind, Taxonomy
from glint.financials.concepts import ConceptMap, DurationClass, NormalizeParams
from glint.financials.derive import derive_items
from glint.financials.facts import Fact
from glint.financials.fychange import FiscalYearChange, detect_changes
from glint.financials.guards import apply_cik_sum, apply_notes_and_loans
from glint.financials.instants import last_n, latest
from glint.financials.leases import LeaseDeclaration, apply_finance_leases
from glint.financials.periods import Period, classify
from glint.financials.quarters import discrete_quarters, fiscal_years
from glint.financials.select import (
    Rejections,
    Value,
    company_taxonomy,
    dedupe,
    reporting_currency,
    select_all,
    select_alternatives,
    select_group,
    select_tags,
    usable_facts,
)
from glint.financials.share_checks import (
    ScaleResult,
    check_diluted_scale,
    class_only_reason,
    drop_placeholder_counts,
    same_filing_diluted,
)
from glint.financials.shares import share_count
from glint.financials.ttm import ttm_series
from glint.financials.zero_debt import zero_debt

Series = dict[date, Value]


@dataclass(frozen=True, slots=True)
class FinancialRow:
    """One row of the `financials` table (contracts/db.py)."""

    cik: str
    line_item: str
    basis: str
    period_end: date
    period_start: date | None
    value: float
    unit: str
    source_tag: str | None
    source_accn: str | None
    filed: date | None
    first_filed_value: float | None
    first_filed_date: date | None
    derived: bool


@dataclass
class CompanyFinancials:
    cik: str
    taxonomy: Taxonomy
    currency: str | None
    fy: dict[LineItem, Series] = field(default_factory=dict[LineItem, Series])
    q: dict[LineItem, Series] = field(default_factory=dict[LineItem, Series])
    ttm: dict[LineItem, Series] = field(default_factory=dict[LineItem, Series])
    instants: dict[LineItem, Series] = field(default_factory=dict[LineItem, Series])
    fy_changes: list[FiscalYearChange] = field(default_factory=list[FiscalYearChange])
    shares_stale: bool = False  # the share count predates the balance sheet by > shares_stale_days
    warnings: list[str] = field(default_factory=list[str])
    rejections: Rejections = field(default_factory=Rejections)

    @property
    def shares_as_of(self) -> date | None:
        """Date of the share count used for market cap (cover page, balance sheet or diluted)."""
        v = self.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
        return v.period.end if v else None

    @property
    def balance_sheet_date(self) -> date | None:
        """The latest balance-sheet date (MRQ). Cover-page share dates don't count."""
        return max(
            (
                e
                for i, s in self.instants.items()
                if i is not LineItem.SHARES_OUTSTANDING
                for e in s
            ),
            default=None,
        )

    @property
    def fy_ends(self) -> tuple[date, ...]:
        """Every fiscal year end seen on any flow, oldest first."""
        return tuple(sorted({e for s in self.fy.values() for e in s}))

    def series(self, item: LineItem, basis: Basis) -> Series:
        """FY / Q / TTM for flows; FY-end or every balance-sheet date (MRQ) for instants."""
        if item in self.instants:
            inst = self.instants[item]
            if basis is Basis.FY:
                ends = set(self.fy_ends)
                return {e: v for e, v in inst.items() if e in ends}
            return inst if basis is Basis.MRQ else {}
        by_basis = {Basis.FY: self.fy, Basis.Q: self.q, Basis.TTM: self.ttm}
        return by_basis.get(basis, {}).get(item, {})

    def latest(self, item: LineItem, basis: Basis) -> Value | None:
        return latest(self.series(item, basis))

    def rows(self, keep: Mapping[Basis, int]) -> list[FinancialRow]:
        """Rows for the `financials` table, keeping the latest `keep[basis]` periods per series."""
        out: list[FinancialRow] = []
        items = sorted({*self.fy, *self.q, *self.ttm, *self.instants})
        for item in items:
            for basis, n in keep.items():
                for v in last_n(self.series(item, basis), n).values():
                    derived = v.derived or (basis is Basis.Q and v.quarter_derived)
                    out.append(_row(self.cik, basis, v, derived))
        return out


def _row(cik: str, basis: Basis, v: Value, derived: bool) -> FinancialRow:
    return FinancialRow(
        cik=cik,
        line_item=v.item.value,
        basis=basis.value,
        period_end=v.period.end,
        period_start=v.period.start,
        value=v.value,
        unit=v.unit,
        source_tag=v.source_tag,
        source_accn=v.source_accn,
        filed=v.filed,
        first_filed_value=v.first_filed_value,
        first_filed_date=v.first_filed_date,
        derived=derived,
    )


def keep_from(concepts: ConceptMap) -> dict[Basis, int]:
    p = concepts.params
    return {
        Basis.FY: p.keep_fy,
        Basis.Q: p.keep_q,
        Basis.TTM: p.keep_ttm,
        Basis.MRQ: p.keep_instant,
    }


def normalize_company(
    cik: str,
    facts: Iterable[Fact],
    concepts: ConceptMap,
    lease: LeaseDeclaration | None = None,
) -> CompanyFinancials:
    facts = list(facts)
    taxonomy = company_taxonomy(facts, concepts)
    currency = reporting_currency(facts, concepts)
    out = CompanyFinancials(cik=cik, taxonomy=taxonomy, currency=currency)
    usable = usable_facts(facts, concepts, taxonomy, currency, out.rejections)
    # Each item's facts grouped once, shared by every selection below (same result as passing
    # the facts each time).
    deduped = {item: dedupe(fs) for item, fs in usable.items()}
    selected: dict[LineItem, dict[Period, Value]] = select_all(deduped, concepts, taxonomy)
    dc = concepts[LineItem.DEBT_CURRENT]
    dc_facts = deduped.get(LineItem.DEBT_CURRENT, {})
    short_term = select_group(dc, taxonomy, dc_facts, "short_term")
    if dc.guarded:
        selected[LineItem.DEBT_CURRENT], short_term = apply_notes_and_loans(
            selected.get(LineItem.DEBT_CURRENT, {}),
            short_term,
            select_group(dc, taxonomy, dc_facts, "current_ltd"),
            select_tags(dc, taxonomy, dc_facts, sorted(dc.guarded)),
            selected.get(LineItem.DEBT_NONCURRENT, {}),
            tolerance=concepts.params.match_tolerance,
        )
    for item, concept in concepts.concepts.items():
        rule = concept.cik_sums.get(cik)
        if rule is None:
            continue
        item_facts = deduped.get(item, {})
        parts = {t: select_tags(concept, taxonomy, item_facts, [t]) for t in rule.tags}
        selected[item] = apply_cik_sum(item, selected.get(item, {}), parts, rule)
    selected = derive_items(selected, concepts, short_term)
    if taxonomy is Taxonomy.US_GAAP:  # the evidence tags are us-gaap
        _add_zero_debt(selected, facts, concepts, currency)
        out.warnings += apply_finance_leases(selected, facts, lease, debt_tags(concepts), currency)

    params = concepts.params
    scale = check_diluted_scale(
        selected.get(LineItem.DILUTED_SHARES, {}),
        selected.get(LineItem.NET_INCOME, {}),
        selected.get(LineItem.EPS_DILUTED, {}),
        params.share_checks,
        params.shares_stale_days,
    )
    if LineItem.DILUTED_SHARES in selected:
        selected[LineItem.DILUTED_SHARES] = scale.values
    out.warnings += scale.warnings
    durations = {i: v for i, v in selected.items() if concepts[i].kind is PeriodKind.DURATION}
    fy_periods = {
        p
        for values in durations.values()
        for p in values
        if classify(p, concepts.durations) is DurationClass.FISCAL_YEAR
    }
    out.fy_changes = detect_changes(
        facts, fy_periods, concepts.durations, params.fy_change_shift_days
    )
    breaks = [b for ch in out.fy_changes for b in ch.breaks]

    for item, values in selected.items():
        c = concepts[item]
        if c.kind is PeriodKind.INSTANT:
            out.instants[item] = {p.end: v for p, v in sorted(values.items())}
            continue
        fys = fiscal_years(values, concepts.durations)
        alts = select_alternatives(c, taxonomy, deduped.get(item, {}))
        qs = discrete_quarters(
            values,
            concepts.durations,
            additive=c.additive,
            gap_days=params.quarter_gap_days,
            alternatives=alts,
        )
        ttm = ttm_series(
            fys,
            qs,
            concepts.durations,
            additive=c.additive,
            gap_days=params.quarter_gap_days,
            tolerance=params.ttm_fy_tolerance,
            breaks=breaks,
            ytd=values,
            alternatives=alts,
        )
        out.fy[item], out.q[item], out.ttm[item] = fys, qs, ttm.values
        out.warnings += ttm.warnings
        if c.nonnegative:
            out.warnings += [
                f"{item}: derived quarter {q.period.label()} is negative ({q.value:,.0f}); "
                "check the year-to-date facts behind it"
                for q in qs.values()
                if q.quarter_derived and q.value < 0
            ]
            out.warnings += [
                f"{item}: TTM {t.period.label()} (FY + YTD − prior YTD) is negative "
                f"({t.value:,.0f}); check the year-to-date facts behind it"
                for t in ttm.values.values()
                if t.inputs[:1] and t.inputs[0].startswith("FY ") and t.value < 0
            ]

    _set_share_count(
        out, scale, params, same_filing_diluted(usable.get(LineItem.DILUTED_SHARES, []))
    )
    return out


def debt_tags(concepts: ConceptMap) -> frozenset[str]:
    """Every us-gaap tag that names debt: the debt line items' tags and the evidence debt tags."""
    items = (LineItem.DEBT_CURRENT, LineItem.DEBT_NONCURRENT, LineItem.TOTAL_DEBT)
    tags = {t for i in items for ts in concepts[i].tags.values() for t in ts}
    if concepts.zero_debt is not None:
        tags |= concepts.zero_debt.debt_lines
    return frozenset(tags)


def _add_zero_debt(
    selected: dict[LineItem, dict[Period, Value]],
    facts: list[Fact],
    concepts: ConceptMap,
    currency: str | None,
) -> None:
    """total_debt = 0 at the latest balance sheet when its filing proves it (zero_debt.py)."""
    rule = concepts.zero_debt
    if rule is None or currency is None:
        return
    ends = [
        p.end
        for i, values in selected.items()
        if concepts[i].kind is PeriodKind.INSTANT and i is not LineItem.SHARES_OUTSTANDING
        for p in values
    ]
    if not ends:
        return
    at = Period(end=max(ends))
    debt = selected.get(LineItem.TOTAL_DEBT, {})
    if at in debt:
        return
    v = zero_debt(facts, at.end, currency, rule)
    if v is not None:
        selected[LineItem.TOTAL_DEBT] = dict(sorted({**debt, at: v}.items()))


def _set_share_count(
    out: CompanyFinancials,
    scale: ScaleResult,
    params: NormalizeParams,
    filed_diluted: Mapping[tuple[str, date], tuple[Period, float]],
) -> None:
    """The count used for market cap (§4.3 rule 11), after dropping placeholder and class-only
    counts."""
    filed = out.instants.get(LineItem.SHARES_OUTSTANDING, {})
    p = params.share_checks
    shares, dropped = drop_placeholder_counts(filed, scale.values, scale.checked, p, filed_diluted)
    out.warnings += dropped
    diluted = {
        **out.fy.get(LineItem.DILUTED_SHARES, {}),
        **out.q.get(LineItem.DILUTED_SHARES, {}),
    }
    # A class-only count after every kept one: older counts may predate a split its filing
    # restated, so only the diluted count of that date or later can stand in (or nothing).
    cut = max(
        (
            d
            for d, v in filed.items()
            if d not in shares
            and class_only_reason(v, filed_diluted, scale.values, scale.checked, p)
        ),
        default=None,
    )
    if cut is not None and (not shares or max(shares) < cut):
        diluted = {e: v for e, v in diluted.items() if e >= cut}
        if not diluted:
            out.warnings.append(
                f"shares_outstanding: the count at {cut} is one class and no diluted count "
                f"is dated on or after it; {len(shares)} older count(s) not used"
            )
            shares = {}
        count = share_count({}, diluted, params.shares_stale_days)
    else:
        count = share_count(shares, diluted, params.shares_stale_days)
    if shares:
        out.instants[LineItem.SHARES_OUTSTANDING] = shares
    else:
        out.instants.pop(LineItem.SHARES_OUTSTANDING, None)
    if count is not None and count.derived:
        out.instants[LineItem.SHARES_OUTSTANDING] = {**shares, count.period.end: count}
    last_balance = out.balance_sheet_date
    if count is not None and last_balance is not None:
        age = (last_balance - count.period.end).days
        if age > params.shares_stale_days:
            out.shares_stale = True
            out.warnings.append(
                f"shares_outstanding: latest count is from {count.period.end}, "
                f"{age} days before the latest balance sheet ({last_balance})"
            )
