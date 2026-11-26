"""Where a filer presents its finance-lease liability, in its own words (ASC 842). Pure.

Since ASC 842, a filer tags `FinanceLeaseLiability{,Current,Noncurrent}StatementOfFinancial
PositionExtensibleList`, naming the balance-sheet line(s) that hold the lease liability (e.g.
`us-gaap:OtherLiabilitiesNoncurrent`, or `us-gaap:LongTermDebtNoncurrent` when it sits inside
debt). WT-03 adds a finance lease to total_debt only where that line isn't the debt tag it
picked, so it is never counted twice; when no filing says, the lease isn't added (WT-06 notes
it). Read from the latest 10-K/10-Q's cover cache (ingest/sec/covers.py), else the latest 10-K's:
most 10-Qs leave the declaration out.
"""

from dataclasses import dataclass
from datetime import date

from glint.ingest.sec.covers import Cover

LEASE_LIABILITY_TAGS = frozenset({
    "us-gaap:FinanceLeaseLiability",
    "us-gaap:FinanceLeaseLiabilityCurrent",
    "us-gaap:FinanceLeaseLiabilityNoncurrent",
})  # fmt: skip
_SUFFIX = "StatementOfFinancialPositionExtensibleList"
COMPONENTS = {  # declaration concept → which part of the lease liability it places
    f"FinanceLeaseLiability{_SUFFIX}": "total",
    f"FinanceLeaseLiabilityCurrent{_SUFFIX}": "current",
    f"FinanceLeaseLiabilityNoncurrent{_SUFFIX}": "noncurrent",
}


@dataclass(frozen=True)
class LeasePresentation:
    status: str  # "stated" | "not_stated"
    lines: dict[str, list[str]]  # component ("current", "noncurrent", "total") → named lines
    accn: str | None  # the filing that names the lines (None when not stated)
    as_of: date | None  # its balance-sheet date
    evidence: str
    since: date | None = None  # earliest date that filing names the same lines for (comparatives)


def _balance_date(cover: Cover) -> date | None:
    """The cover's own balance-sheet date: the latest date any kept fact or declaration has."""
    ends = [f.end for f in cover.balance_facts] + [x.end for x in cover.lease_lines]
    return max(ends) if ends else None


def _declared(cover: Cover) -> tuple[date, date, dict[str, list[str]]] | None:
    """(latest date, earliest date with the same lines, lines) for the finance-lease liability
    lines a filing names. A 10-K declares for its comparative column too."""
    decl = [x for x in cover.lease_lines if x.concept in COMPONENTS and not x.dims]
    if not decl:
        return None
    by_end: dict[date, dict[str, list[str]]] = {}
    for x in sorted(decl, key=lambda x: (x.end, x.concept)):
        part = by_end.setdefault(x.end, {}).setdefault(COMPONENTS[x.concept], [])
        part.extend(line for line in x.lines if line not in part)
    end = max(by_end)
    since = min(d for d, lines in by_end.items() if lines == by_end[end])
    return end, since, by_end[end]


def _describe(lines: dict[str, list[str]]) -> str:
    order = ("current", "noncurrent", "total")
    return "; ".join(f"{k} in {', '.join(lines[k])}" for k in order if k in lines)


def finance_lease_presentation(
    latest: Cover | None, annual: Cover | None = None
) -> LeasePresentation | None:
    """None when the latest filing tags no finance-lease liability at its balance-sheet date.
    Otherwise "stated" with the lines the latest filing (else the latest 10-K) names, or
    "not_stated"."""
    if latest is None:
        return None
    bs = _balance_date(latest)
    lease = [
        f for f in latest.balance_facts
        if f.concept in LEASE_LIABILITY_TAGS and not f.dims and f.end == bs and f.value > 0
    ]  # fmt: skip
    if not lease:
        return None
    for cover in (latest, annual):
        if cover is None:
            continue
        found = _declared(cover)
        if found is not None:
            end, since, lines = found
            evidence = f"{cover.form} {cover.accn} ({end}): finance lease {_describe(lines)}"
            return LeasePresentation("stated", lines, cover.accn, end, evidence, since)
    amount = max(lease, key=lambda f: f.value)
    looked = ", ".join(f"{c.form} {c.accn}" for c in (latest, annual) if c is not None)
    evidence = (
        f"{amount.concept.removeprefix('us-gaap:')} {amount.value:,.0f} at {bs}; "
        f"no filing names its balance-sheet line ({looked})"
    )
    return LeasePresentation("not_stated", {}, None, None, evidence)
