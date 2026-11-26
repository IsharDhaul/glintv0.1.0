"""Dedupe and tag precedence (§4.3 rules 3, 4, 10): one value per (line item, period).

Pure. The same fact appears in many filings; the current view keeps the latest-filed value and
remembers the earliest. Per period, the highest-priority tag with a value wins; alternative tags
are never summed (only a line item's configured `sum_groups` add *distinct* components).
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import cast

from glint.contracts.enums import LineItem, PeriodKind, Taxonomy
from glint.financials.concepts import Concept, ConceptMap, DurationClass, UnitKind
from glint.financials.facts import Fact
from glint.financials.periods import Period

_ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Value:
    """One normalized number for a line item and period, with where it came from."""

    item: LineItem
    period: Period
    value: float
    unit: str
    source_tag: str | None  # None when derived
    source_accn: str | None
    filed: date
    first_filed_value: float | None
    first_filed_date: date | None
    derived: bool  # built by a rule-9 derivation or from sum-group components (DERIVED_INPUT)
    inputs: tuple[str, ...] = ()  # what a derived value was built from (for --sources)
    quarter_derived: bool = False  # a quarter computed from year-to-date values (§4.3 rule 5)
    lineage: str | None = None  # the tags behind the value; None = just `source_tag`

    @property
    def tag_key(self) -> str:
        """What the value is made of. Only values with the same key are subtracted: a Q4 from
        an FY under one tag and a 9M under another would mix alternative tags (rule 4)."""
        return self.lineage if self.lineage is not None else (self.source_tag or "")


@dataclass
class Rejections:
    """Facts dropped before selection, counted by reason."""

    counts: Counter[str] = field(default_factory=Counter[str])

    def add(self, reason: str) -> None:
        self.counts[reason] += 1


def is_currency(unit: str) -> bool:
    return bool(_ISO_CURRENCY.match(unit))


def company_taxonomy(facts: Iterable[Fact], concepts: ConceptMap) -> Taxonomy:
    """us-gaap or ifrs-full: whichever has more mapped facts (ties go to us-gaap)."""
    counts: Counter[Taxonomy] = Counter()
    tag_index = concepts.tag_index
    for f in facts:
        if f.taxonomy is not Taxonomy.DEI and (f.taxonomy, f.tag) in tag_index:
            counts[f.taxonomy] += 1
    if counts[Taxonomy.IFRS_FULL] > counts[Taxonomy.US_GAAP]:
        return Taxonomy.IFRS_FULL
    return Taxonomy.US_GAAP


def reporting_currency(facts: Iterable[Fact], concepts: ConceptMap) -> str | None:
    """The most common currency on revenue facts (§4.3 rule 10); else on any monetary fact."""
    revenue: Counter[str] = Counter()
    monetary: Counter[str] = Counter()
    tag_index = concepts.tag_index
    currencies: dict[str, bool] = {}  # unit → is_currency(unit); a company has a few units
    for f in facts:
        unit = f.unit
        cur = currencies.get(unit)
        if cur is None:
            cur = currencies[unit] = is_currency(unit)
        if not cur:
            continue
        item = tag_index.get((f.taxonomy, f.tag))
        if item is None:
            continue
        monetary[unit] += 1
        if item is LineItem.REVENUE:
            revenue[unit] += 1
    for counts in (revenue, monetary):
        if counts:
            # Most common; ties broken alphabetically so the choice is deterministic.
            return min(counts, key=lambda u: (-counts[u], u))
    return None


def expected_unit(concept: Concept, currency: str | None) -> str | None:
    match concept.unit:
        case UnitKind.CURRENCY:
            return currency
        case UnitKind.PER_SHARE:
            return f"{currency}/shares" if currency else None
        case UnitKind.SHARES:
            return "shares"


def usable_facts(
    facts: Iterable[Fact],
    concepts: ConceptMap,
    taxonomy: Taxonomy,
    currency: str | None,
    rejections: Rejections,
) -> dict[LineItem, list[Fact]]:
    """Facts that may feed a line item: right form, taxonomy, unit and period kind."""
    out: dict[LineItem, list[Fact]] = defaultdict(list)
    tag_index, forms, durations = concepts.tag_index, concepts.forms, concepts.durations
    # Per line item: (expected unit, counts are shares, is an instant). Hoisted out of the loop.
    rules: dict[LineItem, tuple[str | None, bool, bool]] = {}
    for f in facts:
        item = tag_index.get((f.taxonomy, f.tag))
        if item is None:
            continue
        if f.taxonomy is not taxonomy and f.taxonomy is not Taxonomy.DEI:
            rejections.add("other_taxonomy")
            continue
        if f.form not in forms:
            rejections.add("form")
            continue
        rule = rules.get(item)
        if rule is None:
            concept = concepts[item]
            rule = rules[item] = (
                expected_unit(concept, currency),
                concept.unit is UnitKind.SHARES,
                concept.kind is PeriodKind.INSTANT,
            )
        unit, shares, instant = rule
        if f.unit != unit:
            rejections.add("unit")
            continue
        if shares and f.val <= 0:
            # Multi-class and preferred-only filers tag 0 undimensioned; never a count.
            rejections.add("nonpositive_shares")
            continue
        start = f.start
        if instant != (start is None):
            rejections.add("period_kind")
            continue
        # = classify(period_of(f), durations), without building a Period per fact.
        if start is not None and durations.classify((f.end - start).days) is DurationClass.OTHER:
            rejections.add("duration_length")
            continue
        out[item].append(f)
    return dict(out)


@dataclass(frozen=True, slots=True)
class _TagValue:
    tag: str
    latest: Fact
    first: Fact


Deduped = Mapping[tuple[Period, str], _TagValue]


def _filing_order(f: Fact) -> tuple[date, str, float]:
    return (f.filed, f.accn, f.val)


def dedupe(facts: Iterable[Fact]) -> dict[tuple[Period, str], _TagValue]:
    """Per (period, tag): latest-filed fact is the value, earliest-filed is the first value.

    Ordered by (filed, accn, val); on a full tie the later fact in input order is the value and
    the earlier one the first value (what a stable sort gives). Keys are in first-seen order.
    Grouping is by plain (end, start, tag) tuples, so one Period is built per group, not per fact.
    """
    groups: dict[tuple[date, date | None, str], list[Fact]] = {}
    for f in facts:
        key = (f.end, f.start, f.tag)
        fs = groups.get(key)
        if fs is None:
            groups[key] = [f]
        else:
            fs.append(f)
    out: dict[tuple[Period, str], _TagValue] = {}
    for (end, start, tag), fs in groups.items():
        if len(fs) > 1:
            fs.sort(key=_filing_order)
        out[(Period(end=end, start=start), tag)] = _TagValue(tag=tag, latest=fs[-1], first=fs[0])
    return out


def _from_tag(item: LineItem, period: Period, tv: _TagValue) -> Value:
    return Value(
        item=item,
        period=period,
        value=tv.latest.val,
        unit=tv.latest.unit,
        source_tag=tv.tag,
        source_accn=tv.latest.accn,
        filed=tv.latest.filed,
        first_filed_value=tv.first.val,
        first_filed_date=tv.first.filed,
        derived=False,
    )


def _from_groups(item: LineItem, period: Period, parts: list[_TagValue]) -> Value:
    latest = max(parts, key=lambda p: (p.latest.filed, p.latest.accn))
    return Value(
        item=item,
        period=period,
        value=sum(p.latest.val for p in parts),
        unit=latest.latest.unit,
        source_tag=None,
        source_accn=latest.latest.accn,
        filed=latest.latest.filed,
        first_filed_value=sum(p.first.val for p in parts),
        first_filed_date=max(p.first.filed for p in parts),
        derived=True,
        inputs=tuple(p.tag for p in parts),
        lineage="+".join(sorted(p.tag for p in parts)),
    )


def _deduped(facts: Iterable[Fact] | Deduped) -> Deduped:
    return cast(Deduped, facts) if isinstance(facts, Mapping) else dedupe(facts)


def select_item(
    concept: Concept, taxonomy: Taxonomy, facts: Iterable[Fact] | Deduped
) -> dict[Period, Value]:
    """One value per period for one line item, by tag precedence. `facts` may be already
    deduped (`dedupe`), so one item's facts are grouped once for all its selections."""
    deduped = _deduped(facts)
    periods = sorted({p for p, _ in deduped})
    priority = [tag for _, tag in concept.tags_for(taxonomy)]
    total_tags = concept.total_tags
    totals = [t for t in priority if t in total_tags]
    groups = {
        name: [t for t in group if t in priority] for name, group in concept.sum_groups.items()
    }
    out: dict[Period, Value] = {}
    for period in periods:
        chosen = next((deduped[(period, t)] for t in totals if (period, t) in deduped), None)
        if chosen is not None:
            out[period] = _from_tag(concept.item, period, chosen)
            continue
        hits = {
            name: hit
            for name, group in groups.items()
            if (hit := next((deduped[(period, t)] for t in group if (period, t) in deduped), None))
        }
        if hits and concept.sum_requires <= hits.keys():
            out[period] = _from_groups(concept.item, period, list(hits.values()))
    return out


Alternatives = Mapping[Period, Mapping[str, Value]]


def select_alternatives(
    concept: Concept, taxonomy: Taxonomy, facts: Iterable[Fact] | Deduped
) -> Alternatives:
    """Every total tag's value per period, not just the winning one. Used only to subtract like
    from like: when FY and 9M won under different tags, the same tag may be filed for both."""
    deduped = _deduped(facts)
    totals = {t for _, t in concept.tags_for(taxonomy)} & concept.total_tags
    out: dict[Period, dict[str, Value]] = {}
    for (period, tag), tv in deduped.items():
        if tag in totals:
            out.setdefault(period, {})[tag] = _from_tag(concept.item, period, tv)
    return out


def as_lineage(v: Value, key: str, alternatives: Alternatives) -> Value | None:
    """`v`, or the same period's value under tag `key`, or None."""
    return v if v.tag_key == key else alternatives.get(v.period, {}).get(key)


def select_group(
    concept: Concept, taxonomy: Taxonomy, facts: Iterable[Fact] | Deduped, group: str
) -> dict[Period, Value]:
    """One sum-group component on its own: per period, the first tag in the group with a value."""
    return select_tags(concept, taxonomy, facts, concept.sum_groups.get(group, ()))


def select_tags(
    concept: Concept, taxonomy: Taxonomy, facts: Iterable[Fact] | Deduped, wanted: Iterable[str]
) -> dict[Period, Value]:
    """Per period, the first of `wanted` (in order) with a value, under its own tag."""
    deduped = _deduped(facts)
    allowed = {tag for _, tag in concept.tags_for(taxonomy)}
    tags = [t for t in wanted if t in allowed]
    out: dict[Period, Value] = {}
    for period in sorted({p for p, _ in deduped}):
        hit = next((deduped[(period, t)] for t in tags if (period, t) in deduped), None)
        if hit is not None:
            out[period] = _from_tag(concept.item, period, hit)
    return out


def select_all(
    usable: Mapping[LineItem, list[Fact]] | Mapping[LineItem, Deduped],
    concepts: ConceptMap,
    taxonomy: Taxonomy,
) -> dict[LineItem, dict[Period, Value]]:
    return {
        item: select_item(concepts[item], taxonomy, facts) for item, facts in sorted(usable.items())
    }
