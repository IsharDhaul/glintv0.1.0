"""Finance leases in total_debt, on the filing's own word (ASC 842). Pure.

WT-01 records the balance-sheet line(s) the latest 10-Q (else 10-K) names for the finance-lease
liability (`companies.parquet` `finance_lease_lines_*`). A part of the lease (current,
non-current, or the undivided total) is added to total_debt only when **every** line named for it
is outside debt: other liabilities, accrued liabilities, or a lease line of its own. When a named
line is debt-like (a debt line item's tag, an evidence debt tag, or a name that says debt,
borrowings, notes, loans, credit or capital lease), the lease is taken to be in the debt Glint
already counts, so it is never added twice; the error, if any, understates debt. A part is also
skipped when Glint's own pick for that debt component is a `…CapitalLease…` tag, which includes
finance leases by definition. Unstated leases aren't added at all (WT-06 notes it).

Applied from `since` (the earliest date the declaring filing names the same lines for) onward,
to dates where total_debt exists: a lease never creates a debt figure on its own.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date

from glint.contracts.enums import LineItem, Taxonomy
from glint.financials.facts import Fact
from glint.financials.periods import Period
from glint.financials.select import Value

LEASE_TAGS = {  # part → the undimensioned us-gaap tag holding that part of the lease liability
    "current": "FinanceLeaseLiabilityCurrent",
    "noncurrent": "FinanceLeaseLiabilityNoncurrent",
    "total": "FinanceLeaseLiability",
}
_OWN_LINE = re.compile(r"^(FinanceLeaseLiability|CapitalLeaseObligations)(Current|Noncurrent)?$")
_DEBT_NAME = re.compile(r"Debt|Borrowing|Notes|Loan|Credit|CapitalLease|CommercialPaper")
_COMPONENT = {"current": LineItem.DEBT_CURRENT, "noncurrent": LineItem.DEBT_NONCURRENT}


@dataclass(frozen=True)
class LeaseDeclaration:
    """WT-01's record of where the filing presents its finance-lease liability."""

    lines: dict[str, tuple[str, ...]]  # part → named lines, e.g. "us-gaap:OtherLiabilitiesCurrent"
    since: date
    accn: str


def outside_debt(line: str, debt_tags: frozenset[str]) -> bool:
    """A named balance-sheet line that isn't debt: a lease line of its own, or any line whose
    tag isn't a debt tag and whose name doesn't say debt."""
    local = line.split(":", 1)[-1]
    if _OWN_LINE.match(local):
        return True
    return local not in debt_tags and not _DEBT_NAME.search(local)


def parts_to_add(decl: LeaseDeclaration, debt_tags: frozenset[str]) -> list[str]:
    """The parts of the lease to add: every line named for them is outside debt. An undivided
    `total` counts only when neither the current nor the non-current part is named."""
    out = [p for p in ("current", "noncurrent") if decl.lines.get(p)
           and all(outside_debt(x, debt_tags) for x in decl.lines[p])]  # fmt: skip
    named_split = "current" in decl.lines or "noncurrent" in decl.lines
    total = decl.lines.get("total")
    if not named_split and total and all(outside_debt(x, debt_tags) for x in total):
        out.append("total")
    return out


def _lease_values(facts: Iterable[Fact], currency: str) -> dict[tuple[str, date], Fact]:
    """(tag, date) → the latest-filed undimensioned us-gaap lease fact in the reporting currency."""
    wanted = set(LEASE_TAGS.values())
    out: dict[tuple[str, date], Fact] = {}
    for f in facts:
        if f.taxonomy is not Taxonomy.US_GAAP or f.tag not in wanted or f.start is not None:
            continue
        if f.unit != currency:
            continue
        key = (f.tag, f.end)
        if key not in out or (f.filed, f.accn) > (out[key].filed, out[key].accn):
            out[key] = f
    return out


def apply_finance_leases(
    selected: dict[LineItem, dict[Period, Value]],
    facts: Iterable[Fact],
    decl: LeaseDeclaration | None,
    debt_tags: frozenset[str],
    currency: str | None,
) -> list[str]:
    """Add the finance-lease parts the filing presents outside debt to total_debt. Returns
    warnings (a declared part with no lease value at a date is left out, never estimated)."""
    debt = selected.get(LineItem.TOTAL_DEBT, {})
    if decl is None or currency is None or not debt:
        return []
    parts = parts_to_add(decl, debt_tags)
    if not parts:
        return []
    leases = _lease_values(facts, currency)
    warnings: list[str] = []
    out = dict(debt)
    for period, v in debt.items():
        if period.end < decl.since:
            continue
        if v.source_tag and "CapitalLease" in v.source_tag:  # the filer's total includes leases
            continue
        eligible = [p for p in parts if not _pick_includes_leases(selected, p, period)]
        found = {p: _part_facts(leases, p, period.end) for p in eligible}
        whole = leases.get((LEASE_TAGS["total"], period.end))
        added: list[tuple[str, Fact]] = []
        if set(eligible) == {"current", "noncurrent"} and not all(found.values()) and whole:
            # Both parts sit outside debt, but this filing tags only the undivided total (10-Qs
            # often do): the total is exactly those two parts.
            added = [("current", whole), ("noncurrent", whole)]
        else:
            for part in eligible:
                if not found[part]:
                    warnings.append(f"total_debt: finance lease ({part}) not tagged at "
                                    f"{period.end}; not added")  # fmt: skip
                added += [(part, f) for f in found[part]]
        if not added:
            continue
        named = dict.fromkeys(p for p, _ in added)
        added = list({id(f): (p, f) for p, f in added}.values())  # one fact counted once
        where = "; ".join(f"{p} in {', '.join(decl.lines[p])}" for p in named)
        out[period] = replace(
            v,
            value=v.value + sum(f.val for _, f in added),
            source_tag=None,
            derived=True,
            first_filed_value=None,
            first_filed_date=None,
            inputs=(*v.inputs, *(f"+ finance lease ({f.tag}, {f.accn})" for _, f in added),
                    f"finance lease presented outside debt: {where} ({decl.accn})"),
            lineage=f"{v.tag_key}+lease[{'+'.join(f.tag for _, f in added)}]",
        )  # fmt: skip
    selected[LineItem.TOTAL_DEBT] = out
    return warnings


def _pick_includes_leases(
    selected: dict[LineItem, dict[Period, Value]], part: str, period: Period
) -> bool:
    """Glint's own pick for this debt component is a `…CapitalLease…` tag (leases included)."""
    component = _COMPONENT.get(part)
    pick = selected.get(component, {}).get(period) if component else None
    return pick is not None and pick.source_tag is not None and "CapitalLease" in pick.source_tag


def _part_facts(leases: dict[tuple[str, date], Fact], part: str, end: date) -> list[Fact]:
    """The fact(s) for one part at a date. An undivided total not tagged as such is its current
    and non-current parts, when both are tagged."""
    f = leases.get((LEASE_TAGS[part], end))
    if f is not None:
        return [f]
    if part != "total":
        return []
    split = [leases.get((LEASE_TAGS[p], end)) for p in ("current", "noncurrent")]
    return [x for x in split if x is not None] if all(split) else []
