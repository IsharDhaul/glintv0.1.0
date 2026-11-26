"""Zero total debt from positive evidence on the balance sheet. Pure.

A missing debt tag is never evidence of no debt (principle 3). `total_debt` = 0 is derived for a
balance-sheet date only when the filing that first reported that date proves it:

1. the filing is a 10-K/10-Q (`zero_debt_forms`) and tags undimensioned `Liabilities`, and no
   other filing reports a different `Liabilities` for that date (a restatement);
2. no debt tag (a debt line item's, or an `evidence_tags.debt_lines` tag such as notes payable,
   convertible notes, credit lines, finance leases, maturity schedules) has a nonzero value at that
   date in any filing or unit;
3. **every** non-debt liability line the filing tags at that date (`evidence_tags.liability_lines`)
   is counted, and together they add up exactly to `Liabilities`. When `LiabilitiesCurrent` is
   tagged, the lines tagged `…Current` plus some of the lines without a current/non-current suffix
   add up exactly to it;
4. no interest expense was reported (nonzero) for a period ending in the year before (debt repaid
   shortly before the date, or a facility in use, would show there).

companyfacts carries no custom-extension or dimensional facts. A debt line tagged that way (GM's
dimensional debt, PCAR's custom tags) is absent, so the lines fall short of `Liabilities`: no
proof. Because every line counts, a footnote breakdown tagged next to its balance-sheet line
(salaries and bonuses inside accrued liabilities) makes the sum overshoot: no proof either. No
line is ever left out to make the sum work. The one exception is structural: a total `X` tagged
next to its own `XCurrent` / `XNoncurrent` parts (by tag name) is counted once, through its parts,
and only when it equals them; and a configured footnote breakdown (`liability_breakdowns`:
accrued liabilities → employee, professional fees, other accrued…) is not counted again when all
of its children tagged in the filing are together at most the parent (all of them, never a
subset; dropping only lowers the sum, so it can't stand in for a missing debt line).

Residual risk, recorded in docs/decisions/WT-03.md: a catch-all line (`OtherLiabilitiesCurrent`…)
could hold an immaterial note; S-X 5-02 requires borrowings to be stated separately on the face
of the balance sheet, so material debt has its own line.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from itertools import combinations

from glint.contracts.enums import LineItem, Taxonomy
from glint.financials.concepts import ZeroDebtRule
from glint.financials.facts import Fact
from glint.financials.periods import Period
from glint.financials.select import Value

Line = tuple[str, int]
_MIXED = "CurrentAndNoncurrent"
MAX_FREE = 12  # unsuffixed lines to place on the current side (2^12 subsets at most)


def is_current(tag: str) -> bool:
    return tag.endswith("Current") and not tag.endswith(("Noncurrent", _MIXED))


def is_unsuffixed(tag: str) -> bool:
    """Neither `…Current` nor `…Noncurrent` (or both: `…CurrentAndNoncurrent`): either side."""
    return not tag.endswith(("Current", "Noncurrent")) or tag.endswith(_MIXED)


def _stem(tag: str) -> str | None:
    """`X` of a total that may be tagged next to `XCurrent` / `XNoncurrent`."""
    if tag.endswith(_MIXED):
        return tag.removesuffix(_MIXED)
    return None if tag.endswith(("Current", "Noncurrent")) else tag


def merge_rollups(lines: Sequence[Line]) -> list[Line] | None:
    """Count a total `X` once when its `XCurrent` / `XNoncurrent` parts are tagged too.

    The total is dropped only if it equals its tagged parts; a total that disagrees with its parts
    means the lines can't be trusted (None)."""
    values = dict(lines)
    out: list[Line] = []
    for tag, value in lines:
        stem = _stem(tag)
        parts = [values[p] for p in (f"{stem}Current", f"{stem}Noncurrent") if p in values]
        if stem is None or not parts:
            out.append((tag, value))
        elif sum(parts) != value:
            return None
    return out


def merge_breakdowns(lines: Sequence[Line], breakdowns: Mapping[str, Sequence[str]]) -> list[Line]:
    """Drop a parent's footnote children, in config order: all children still present, when
    together they are at most the parent (a footnote inside the line). Never a chosen subset."""
    values = dict(lines)
    for parent, children in breakdowns.items():
        present = [c for c in children if c in values]
        if parent in values and present and sum(values[c] for c in present) <= values[parent]:
            for c in present:
                del values[c]
    return [x for x in lines if x[0] in values]


def subset_sums_to(lines: Sequence[Line], target: int) -> bool:
    """Whether some subset of `lines` adds up exactly to `target`."""
    return any(
        sum(v for _, v in combo) == target
        for r in range(len(lines) + 1)
        for combo in combinations(lines, r)
    )


def itemize(
    lines: Sequence[Line],
    total: int,
    current_total: int | None,
    max_lines: int,
    breakdowns: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, ...] | None:
    """All the lines, when together they are the balance sheet's liabilities; else None."""
    if len(lines) > max_lines:
        return None
    merged = merge_rollups(merge_breakdowns([x for x in lines if x[1] != 0], breakdowns or {}))
    if not merged or sum(v for _, v in merged) != total:
        return None
    if current_total is not None:
        current = sum(v for t, v in merged if is_current(t))
        free = [x for x in merged if is_unsuffixed(x[0])]
        if len(free) > MAX_FREE or not subset_sums_to(free, current_total - current):
            return None
    return tuple(t for t, _ in merged)


def zero_debt(facts: Iterable[Fact], at: date, currency: str, rule: ZeroDebtRule) -> Value | None:
    """`total_debt` = 0 at `at` (derived), with the balance-sheet lines that prove it; else None."""
    gaap = [f for f in facts if f.taxonomy is Taxonomy.US_GAAP]
    instants = [f for f in gaap if f.start is None and f.end == at]
    if any(f.tag in rule.debt_lines and f.val != 0 for f in instants):  # any unit
        return None
    since = at - timedelta(days=rule.interest_lookback_days)
    if any(
        f.tag in rule.interest and f.start is not None and since < f.end <= at and f.val != 0
        for f in gaap
    ):
        return None
    instants = [f for f in instants if f.unit == currency]
    liab = [f for f in instants if f.tag == "Liabilities"]
    if len({round(f.val) for f in liab}) != 1:  # none, or restated
        return None
    filed = [f for f in liab if f.form in rule.forms]
    if not filed:
        return None
    first = min(filed, key=lambda f: (f.filed, f.accn))
    vals: dict[str, int] = {}
    for f in instants:
        if f.accn != first.accn:
            continue
        v = round(f.val)
        if vals.setdefault(f.tag, v) != v:  # one filing, two values for a tag: no proof
            return None
    total, current = vals["Liabilities"], vals.get("LiabilitiesCurrent")
    if total <= 0:
        return None
    lines = [(t, v) for t, v in sorted(vals.items()) if t in rule.liability_lines]
    found = itemize(lines, total, current, rule.max_lines, rule.breakdowns)
    if found is None:
        return None
    shown = " + ".join(f"{t} {vals[t]:,}" for t in found)
    current_note = f"; LiabilitiesCurrent {current:,}" if current is not None else ""
    evidence = (
        f"no debt: Liabilities {total:,}{current_note} = {shown} (every liability line tagged), "
        f"no debt tag and no interest expense in the year to {at} ({first.form} {first.accn})"
    )
    return Value(
        item=LineItem.TOTAL_DEBT,
        period=Period(end=at),
        value=0.0,
        unit=currency,
        source_tag=None,
        source_accn=first.accn,
        filed=first.filed,
        first_filed_value=0.0,
        first_filed_date=first.filed,
        derived=True,
        inputs=(evidence,),
        lineage="zero_debt",
    )
