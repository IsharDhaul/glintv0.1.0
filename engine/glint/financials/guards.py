"""Two narrow rules that can't be plain tag precedence. Pure.

**Guarded short-term borrowings.** `NotesAndLoansPayable` is the short-term borrowings line for some
filers (KO: commercial paper + other short-term loans), but across filers it is often a total of
all notes (≥ long-term debt in 113 of 248 cases since 2023) or equal to the current maturities of
long-term debt (24 of 107: a double count). It replaces the `short_term` pick for a period only if
it is ≥ that pick (so ≥ commercial paper), long-term debt is tagged and larger, and it differs from
the current maturities. `debt_current` is then rebuilt as current maturities + it, unless a total
(`DebtCurrent`) was tagged.

**Per-CIK component sums.** Some lines exist only as components in XBRL. A sum is applied only for a
CIK listed in concepts.yaml (`cik_sums`) with the filing line it reproduces, keyed by a person
(principle 1), and only where the period's value came from one of the components or was missing,
never over a tagged line.
"""

from collections.abc import Mapping

from glint.contracts.enums import LineItem
from glint.financials.concepts import CikSum
from glint.financials.derive import combine
from glint.financials.periods import Period
from glint.financials.select import Value

Series = Mapping[Period, Value]


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * abs(b)


def apply_notes_and_loans(
    debt_current: Series,
    short_term: Series,
    current_ltd: Series,
    notes: Series,
    noncurrent: Series,
    *,
    tolerance: float,
) -> tuple[dict[Period, Value], dict[Period, Value]]:
    """(debt_current, short_term) with the guarded NotesAndLoansPayable applied."""
    dc, st = dict(debt_current), dict(short_term)
    for p, n in notes.items():
        pick, cur, ltd = short_term.get(p), current_ltd.get(p), noncurrent.get(p)
        if pick is not None and n.value < pick.value:
            continue
        if ltd is None or n.value >= ltd.value:
            continue
        if cur is not None and _close(n.value, cur.value, tolerance):
            continue
        st[p] = n
        existing = debt_current.get(p)
        if existing is not None and existing.source_tag is not None:
            continue  # a tagged total (DebtCurrent) wins
        dc[p] = combine(LineItem.DEBT_CURRENT, p, [(1, x) for x in (cur, n) if x is not None])
    return dict(sorted(dc.items())), dict(sorted(st.items()))


def apply_cik_sum(
    item: LineItem, selected: Series, parts: Mapping[str, Series], rule: CikSum
) -> dict[Period, Value]:
    """`selected` with Σ components wherever every component is tagged and the period's value
    is missing or came from one of the components."""
    out = dict(selected)
    periods: set[Period] = set(parts.get(rule.tags[0], {})) if rule.tags else set()
    for t in rule.tags[1:]:
        periods &= set(parts.get(t, {}))
    for p in sorted(periods):
        current = selected.get(p)
        if current is not None and current.source_tag not in rule.tags:
            continue
        out[p] = combine(item, p, [(1, parts[t][p]) for t in rule.tags])
    return dict(sorted(out.items()))
