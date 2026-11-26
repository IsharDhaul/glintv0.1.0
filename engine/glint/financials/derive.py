"""Derived line items (§4.3 rule 9), computed per exact period before quarters and TTM. Pure.

A derivation fills only periods where the item has no tagged value and every input has a value
for that same `(start, end)`. Every derived value carries `derived=True`.

`total_debt` has its own rule: debt_current + debt_noncurrent, except that when debt_noncurrent
comes from a tag that already includes the current portion (`LongTermDebt`), only the short-term
borrowings component of debt_current is added. Without a non-current value there's no total: a
missing long-term side is more often an unmapped tag than no long-term debt, and adding only the
current side would understate debt. A missing current side means nothing is due within a year.
Operating leases are never debt. Finance leases are added afterwards, only where the filing
presents them outside debt (financials/leases.py).
"""

from collections.abc import Mapping
from graphlib import TopologicalSorter

from glint.contracts.enums import LineItem
from glint.financials.concepts import ConceptMap, Derivation
from glint.financials.periods import Period
from glint.financials.select import Value

SelectedItems = dict[LineItem, dict[Period, Value]]


def _describe(sign: int, v: Value) -> str:
    return f"{'−' if sign < 0 else '+'} {v.item.value} ({v.source_tag or 'derived'})"


def combine(item: LineItem, period: Period, terms: list[tuple[int, Value]]) -> Value:
    """Σ sign·value over `terms`, with filing provenance from the latest input."""
    vals = [v for _, v in terms]
    latest = max(vals, key=lambda v: (v.filed, v.source_accn or ""))
    has_first = all(v.first_filed_value is not None for v in vals)
    return Value(
        item=item,
        period=period,
        value=sum(s * v.value for s, v in terms),
        unit=vals[0].unit,
        source_tag=None,
        source_accn=latest.source_accn,
        filed=latest.filed,
        first_filed_value=(
            sum(s * (v.first_filed_value or 0.0) for s, v in terms) if has_first else None
        ),
        first_filed_date=(max(v.first_filed_date or v.filed for v in vals) if has_first else None),
        derived=True,
        inputs=tuple(_describe(s, v) for s, v in terms),
        lineage=" ".join(f"{'−' if s < 0 else '+'}{v.item.value}[{v.tag_key}]" for s, v in terms),
    )


def _generic(item: LineItem, rule: Derivation, selected: SelectedItems) -> dict[Period, Value]:
    inputs = [selected.get(dep, {}) for dep in rule.inputs]
    periods = set(inputs[0]).intersection(*inputs[1:]) if inputs else set[Period]()
    return {
        p: combine(item, p, [(s, selected[dep][p]) for s, dep in rule.terms])
        for p in sorted(periods)
    }


def total_debt(
    selected: SelectedItems,
    short_term: Mapping[Period, Value],
    includes_current: frozenset[str],
) -> dict[Period, Value]:
    current = selected.get(LineItem.DEBT_CURRENT, {})
    noncurrent = selected.get(LineItem.DEBT_NONCURRENT, {})
    out: dict[Period, Value] = {}
    for p in sorted(noncurrent):
        n, c = noncurrent[p], current.get(p)
        if n.source_tag in includes_current:
            parts = [n] + ([short_term[p]] if p in short_term else [])
        else:
            parts = [x for x in (c, n) if x is not None]
        out[p] = combine(LineItem.TOTAL_DEBT, p, [(1, x) for x in parts])
    return out


def derive_items(
    selected: SelectedItems,
    concepts: ConceptMap,
    short_term: Mapping[Period, Value] | None = None,
) -> SelectedItems:
    """`selected` plus derived values for every item with a `derive` rule. Tagged values win,
    unless the item is `prefer_derived` (total_debt: a filer's own combined-debt total fills only
    periods where debt_current + debt_noncurrent can't be built)."""
    out: SelectedItems = dict(selected)
    rules = {i: c.derive for i, c in concepts.concepts.items() if c.derive is not None}
    order = TopologicalSorter({i: set(r.inputs) for i, r in rules.items()}).static_order()
    for item in order:
        rule = rules.get(item)
        if rule is None:
            continue
        if item is LineItem.TOTAL_DEBT:
            includes = concepts[LineItem.DEBT_NONCURRENT].includes_current
            derived = total_debt(out, short_term or {}, includes)
        else:
            derived = _generic(item, rule, out)
        tagged = out.get(item, {})
        merged = {**tagged, **derived} if concepts[item].prefer_derived else {**derived, **tagged}
        if merged:
            out[item] = dict(sorted(merged.items()))
    return out
