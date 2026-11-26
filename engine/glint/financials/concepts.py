"""Typed loader for `config/concepts.yaml`: line item → kind, unit, ordered tags, derivation."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from glint.contracts.enums import LineItem, PeriodKind, Sector, Taxonomy
from glint.core.errors import ContractError
from glint.core.settings import REPO_ROOT

DEFAULT_CONCEPTS_PATH = REPO_ROOT / "config" / "concepts.yaml"

_TERM_RE = re.compile(r"\s*([+-])?\s*([a-z_]+)\s*")


class UnitKind(StrEnum):
    CURRENCY = "currency"  # an ISO code: USD, TWD, EUR…
    PER_SHARE = "per_share"  # <currency>/shares
    SHARES = "shares"


class DurationClass(StrEnum):
    """§4.3 rule 2. `OTHER` durations are never used."""

    QUARTER = "quarter"
    HALF_YEAR = "half_year"
    NINE_MONTHS = "nine_months"
    FISCAL_YEAR = "fiscal_year"
    OTHER = "other"


@dataclass(frozen=True)
class Derivation:
    """`a - b + c`: signed terms over other line items."""

    terms: tuple[tuple[int, LineItem], ...]

    @classmethod
    def parse(cls, text: str) -> "Derivation":
        terms: list[tuple[int, LineItem]] = []
        pos = 0
        while pos < len(text):
            m = _TERM_RE.match(text, pos)
            if m is None or (terms and m.group(1) is None):
                raise ContractError(f"bad derivation {text!r}")
            sign = -1 if m.group(1) == "-" else 1
            name = m.group(2)
            if name not in LineItem.__members__.values():
                raise ContractError(f"derivation {text!r}: unknown line item {name!r}")
            terms.append((sign, LineItem(name)))
            pos = m.end()
        if not terms:
            raise ContractError("empty derivation")
        return cls(tuple(terms))

    @property
    def inputs(self) -> tuple[LineItem, ...]:
        return tuple(item for _, item in self.terms)

    def __str__(self) -> str:
        parts = [f"{'−' if s < 0 else '+'} {i.value}" for s, i in self.terms]
        return " ".join(parts).removeprefix("+ ")


class _ConceptFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: PeriodKind
    unit: UnitKind
    tags: dict[Taxonomy, list[str]] = Field(default_factory=dict[Taxonomy, list[str]])
    derive: str | None = None
    prefer_derived: bool = False  # the derivation wins; tags fill only periods it can't
    sign: Literal["positive_outflow"] | None = None
    additive: bool = True
    nonnegative: bool = False
    sum_groups: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    sum_requires: list[str] = Field(default_factory=list[str])
    includes_current: list[str] = Field(default_factory=list[str])
    not_applicable: list[Sector] = Field(default_factory=list[Sector])
    fallback: LineItem | None = None
    tag_notes: dict[str, str] = Field(default_factory=dict[str, str])
    verify: bool = False
    note: str | None = None
    guarded_short_term: list[str] = Field(default_factory=list[str])
    component_only: list[str] = Field(default_factory=list[str])
    cik_sums: dict[str, "_CikSumFile"] = Field(default_factory=dict[str, "_CikSumFile"])


class _CikSumFile(BaseModel):
    """A line that exists only as components for one company, reproduced from its filing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tags: list[str] = Field(min_length=2)
    evidence: str = Field(min_length=1)
    keyed_by: str = Field(min_length=1)


class _Normalize(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ttm_fy_tolerance: float = Field(gt=0, lt=1)
    match_tolerance: float = Field(gt=0, lt=1)
    quarter_gap_days: int = Field(ge=0)
    year_ago_window_days: int = Field(gt=0)
    fy_change_shift_days: int = Field(gt=0)
    shares_stale_days: int = Field(gt=0)
    shares_min_count: float = Field(gt=0)
    shares_placeholder_ratio: float = Field(gt=0, lt=1)
    shares_class_ratio: float = Field(gt=0, lt=1)
    shares_scale_band: float = Field(gt=0, lt=0.5)
    shares_scale_reject_ratio: float = Field(gt=1)
    shares_check_min_eps: float = Field(gt=0)
    shares_check_min_net_income: float = Field(gt=0)
    shares_same_filing_max_ratio: float = Field(gt=1)
    zero_debt_interest_lookback_days: int = Field(gt=0)
    zero_debt_max_lines: int = Field(gt=0, le=30)
    zero_debt_forms: list[str] = Field(min_length=1)
    keep: dict[Literal["fy", "q", "ttm", "instant"], int]


class _Core(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    flows: list[LineItem]
    instants: list[LineItem]


class _EvidenceGroups(BaseModel):
    """Tags kept as evidence only (`evidence_tags`), never a line item's value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    liability_lines: list[str] = Field(default_factory=list[str])
    debt_lines: list[str] = Field(default_factory=list[str])
    interest: list[str] = Field(default_factory=list[str])


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    core: _Core
    durations: dict[DurationClass, tuple[int, int]]
    forms: list[str]
    normalize: _Normalize
    dei_cover_tags: list[str]
    evidence_tags: dict[Taxonomy, _EvidenceGroups] = Field(
        default_factory=dict[Taxonomy, _EvidenceGroups]
    )
    liability_breakdowns: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    line_items: dict[LineItem, _ConceptFile]

    @model_validator(mode="after")
    def _complete(self) -> "_File":
        missing = set(LineItem) - set(self.line_items)
        if missing:
            raise ValueError(f"line items missing from concepts: {sorted(missing)}")
        wanted = set(DurationClass) - {DurationClass.OTHER}
        if set(self.durations) != wanted:
            raise ValueError(f"durations must define exactly {sorted(wanted)}")
        return self


@dataclass(frozen=True)
class CikSum:
    """A line that exists only as components for one company (`cik_sums`, guards.py)."""

    tags: tuple[str, ...]
    evidence: str
    keyed_by: str


@dataclass(frozen=True)
class Concept:
    item: LineItem
    kind: PeriodKind
    unit: UnitKind
    tags: Mapping[Taxonomy, tuple[str, ...]]
    derive: Derivation | None
    sign: str | None
    additive: bool
    sum_groups: Mapping[str, tuple[str, ...]]
    sum_requires: frozenset[str]
    includes_current: frozenset[str]
    not_applicable: frozenset[Sector]
    fallback: LineItem | None
    tag_notes: Mapping[str, str]
    note: str | None = None
    nonnegative: bool = False
    prefer_derived: bool = False  # `derive` wins over tags; tags fill only the rest
    guarded: frozenset[str] = frozenset()  # extracted, used only through guards.py rules
    component_only: frozenset[str] = frozenset()  # extracted, never a value on its own
    cik_sums: Mapping[str, CikSum] = field(default_factory=dict[str, CikSum])

    def tags_for(self, taxonomy: Taxonomy) -> tuple[tuple[Taxonomy, str], ...]:
        """Tags in priority order for a company reporting in `taxonomy`: dei cover tags first."""
        out = [(Taxonomy.DEI, t) for t in self.tags.get(Taxonomy.DEI, ())]
        if taxonomy is not Taxonomy.DEI:
            out += [(taxonomy, t) for t in self.tags.get(taxonomy, ())]
        return tuple(out)

    @property
    def total_tags(self) -> frozenset[str]:
        """Tags outside every sum group: complete values on their own."""
        grouped = {t for group in self.sum_groups.values() for t in group}
        grouped |= self.guarded | self.component_only
        return frozenset(t for tags in self.tags.values() for t in tags if t not in grouped)


@dataclass(frozen=True)
class DurationBounds:
    bounds: Mapping[DurationClass, tuple[int, int]]
    # days → class, filled on use: classify runs millions of times over a few hundred lengths.
    _seen: dict[int, DurationClass] = field(
        default_factory=dict[int, DurationClass], init=False, repr=False, compare=False
    )

    def classify(self, days: int) -> DurationClass:
        cls = self._seen.get(days)
        if cls is None:
            cls = self._seen[days] = self._classify(days)
        return cls

    def _classify(self, days: int) -> DurationClass:
        for cls, (lo, hi) in self.bounds.items():
            if lo <= days <= hi:
                return cls
        return DurationClass.OTHER


@dataclass(frozen=True, slots=True)
class ShareCheckParams:
    """Share-count plausibility thresholds (glint/financials/share_checks.py)."""

    min_count: float
    placeholder_ratio: float
    class_ratio: float
    scale_band: float
    scale_reject_ratio: float
    check_min_eps: float
    check_min_net_income: float
    same_filing_max_ratio: float


@dataclass(frozen=True, slots=True)
class ZeroDebtRule:
    """Positive evidence of zero total debt (glint/financials/zero_debt.py). us-gaap tags only."""

    liability_lines: frozenset[str]
    debt_lines: frozenset[str]  # evidence debt tags + every tag of the debt line items
    interest: frozenset[str]  # evidence interest tags + interest_expense's tags
    interest_lookback_days: int
    max_lines: int
    forms: frozenset[str]
    breakdowns: Mapping[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])


@dataclass(frozen=True)
class NormalizeParams:
    ttm_fy_tolerance: float
    match_tolerance: float
    quarter_gap_days: int
    year_ago_window_days: int
    fy_change_shift_days: int
    shares_stale_days: int
    share_checks: ShareCheckParams
    keep_fy: int
    keep_q: int
    keep_ttm: int
    keep_instant: int


@dataclass(frozen=True)
class ConceptMap:
    concepts: Mapping[LineItem, Concept]
    durations: DurationBounds
    forms: frozenset[str]
    params: NormalizeParams
    dei_cover_tags: tuple[str, ...]
    core: tuple[LineItem, ...] = ()
    zero_debt: ZeroDebtRule | None = None

    def __getitem__(self, item: LineItem) -> Concept:
        return self.concepts[item]

    @cached_property
    def tag_index(self) -> Mapping[tuple[Taxonomy, str], LineItem]:
        """(taxonomy, tag) → the one line item that uses it."""
        out: dict[tuple[Taxonomy, str], LineItem] = {}
        for item, c in self.concepts.items():
            for taxonomy, tags in c.tags.items():
                for tag in tags:
                    out[(taxonomy, tag)] = item
        return out


def _concept(item: LineItem, raw: _ConceptFile) -> Concept:
    tags = {tx: tuple(ts) for tx, ts in raw.tags.items()}
    all_tags = {t for ts in tags.values() for t in ts}
    for tx, ts in tags.items():
        if len(set(ts)) != len(ts):
            raise ContractError(f"{item}: duplicate tag under {tx}")
    derive = Derivation.parse(raw.derive) if raw.derive else None
    if not all_tags and derive is None:
        raise ContractError(f"{item}: needs tags or a derive rule")
    if derive and item in derive.inputs:
        raise ContractError(f"{item}: derivation refers to itself")
    if raw.prefer_derived and (derive is None or not all_tags):
        raise ContractError(f"{item}: prefer_derived needs both tags and a derive rule")
    groups = {name: tuple(ts) for name, ts in raw.sum_groups.items()}
    for name, ts in groups.items():
        stray = set(ts) - all_tags
        if stray:
            raise ContractError(f"{item}: sum group {name} uses unlisted tags {sorted(stray)}")
    unknown = set(raw.sum_requires) - set(groups)
    if unknown:
        raise ContractError(f"{item}: sum_requires names unknown groups {sorted(unknown)}")
    stray = set(raw.includes_current) - all_tags
    if stray:
        raise ContractError(f"{item}: includes_current uses unlisted tags {sorted(stray)}")
    for name, listed in (
        ("guarded_short_term", raw.guarded_short_term),
        ("component_only", raw.component_only),
        *((f"cik_sums[{k}]", r.tags) for k, r in raw.cik_sums.items()),
    ):
        stray = set(listed) - all_tags
        if stray:
            raise ContractError(f"{item}: {name} uses unlisted tags {sorted(stray)}")
    if not raw.additive and raw.kind is not PeriodKind.DURATION:
        raise ContractError(f"{item}: additive applies to durations only")
    return Concept(
        item=item,
        kind=raw.kind,
        unit=raw.unit,
        tags=tags,
        derive=derive,
        sign=raw.sign,
        additive=raw.additive,
        sum_groups=groups,
        sum_requires=frozenset(raw.sum_requires),
        includes_current=frozenset(raw.includes_current),
        not_applicable=frozenset(raw.not_applicable),
        fallback=raw.fallback,
        tag_notes=dict(raw.tag_notes),
        note=raw.note,
        guarded=frozenset(raw.guarded_short_term),
        component_only=frozenset(raw.component_only),
        cik_sums={
            k.zfill(10): CikSum(tuple(r.tags), r.evidence, r.keyed_by)
            for k, r in raw.cik_sums.items()
        },
        nonnegative=raw.nonnegative,
        prefer_derived=raw.prefer_derived,
    )


def parse_concepts(raw: object) -> ConceptMap:
    try:
        parsed = _File.model_validate(raw)
    except ValueError as e:
        raise ContractError(f"concepts.yaml: {e}") from e
    concepts = {item: _concept(item, c) for item, c in parsed.line_items.items()}
    seen: dict[tuple[Taxonomy, str], LineItem] = {}
    for item, c in concepts.items():
        for taxonomy, tags in c.tags.items():
            for tag in tags:
                other = seen.setdefault((taxonomy, tag), item)
                if other is not item:
                    raise ContractError(f"{taxonomy}:{tag} is used by both {other} and {item}")
        if c.derive:
            for dep in c.derive.inputs:
                if concepts[dep].kind is not c.kind:
                    raise ContractError(f"{item}: derivation mixes durations and instants")
        if c.fallback and concepts[c.fallback].unit is not c.unit:
            raise ContractError(f"{item}: fallback {c.fallback} has a different unit")
    for kind, items in (
        (PeriodKind.DURATION, parsed.core.flows),
        (PeriodKind.INSTANT, parsed.core.instants),
    ):
        wrong = [i.value for i in items if concepts[i].kind is not kind]
        if wrong:
            raise ContractError(f"core {kind.value} items of the wrong kind: {wrong}")
    graph = {i: set(c.derive.inputs) for i, c in concepts.items() if c.derive is not None}
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as e:
        raise ContractError(f"derivations form a cycle: {e.args[1]}") from e
    n = parsed.normalize
    params = NormalizeParams(
        ttm_fy_tolerance=n.ttm_fy_tolerance,
        match_tolerance=n.match_tolerance,
        quarter_gap_days=n.quarter_gap_days,
        year_ago_window_days=n.year_ago_window_days,
        fy_change_shift_days=n.fy_change_shift_days,
        shares_stale_days=n.shares_stale_days,
        share_checks=ShareCheckParams(
            min_count=n.shares_min_count,
            placeholder_ratio=n.shares_placeholder_ratio,
            class_ratio=n.shares_class_ratio,
            scale_band=n.shares_scale_band,
            scale_reject_ratio=n.shares_scale_reject_ratio,
            check_min_eps=n.shares_check_min_eps,
            check_min_net_income=n.shares_check_min_net_income,
            same_filing_max_ratio=n.shares_same_filing_max_ratio,
        ),
        keep_fy=n.keep["fy"],
        keep_q=n.keep["q"],
        keep_ttm=n.keep["ttm"],
        keep_instant=n.keep["instant"],
    )
    return ConceptMap(
        zero_debt=_zero_debt_rule(parsed, concepts),
        concepts=concepts,
        durations=DurationBounds(dict(parsed.durations)),
        forms=frozenset(parsed.forms),
        params=params,
        dei_cover_tags=tuple(parsed.dei_cover_tags),
        core=(*parsed.core.flows, *parsed.core.instants),
    )


DEBT_ITEMS = (LineItem.DEBT_CURRENT, LineItem.DEBT_NONCURRENT, LineItem.TOTAL_DEBT)


def _zero_debt_rule(parsed: _File, concepts: Mapping[LineItem, Concept]) -> ZeroDebtRule | None:
    ev = parsed.evidence_tags.get(Taxonomy.US_GAAP)
    if ev is None or not ev.liability_lines:
        return None
    groups = {"liability_lines": ev.liability_lines, "debt_lines": ev.debt_lines,
              "interest": ev.interest}  # fmt: skip
    seen: dict[str, str] = {}
    for name, tags in groups.items():
        for tag in tags:
            other = seen.setdefault(tag, name)
            if other != name or tags.count(tag) > 1:
                raise ContractError(f"evidence_tags: {tag} listed twice ({other}, {name})")

    def mapped(items: tuple[LineItem, ...]) -> set[str]:
        return {t for i in items for t in concepts[i].tags.get(Taxonomy.US_GAAP, ())}

    debt = set(ev.debt_lines) | mapped(DEBT_ITEMS)
    clash = set(ev.liability_lines) & debt
    if clash:
        raise ContractError(f"evidence_tags: debt tags listed as liability lines: {sorted(clash)}")
    for parent, children in parsed.liability_breakdowns.items():
        stray = {parent, *children} - set(ev.liability_lines)
        if stray:
            raise ContractError(f"liability_breakdowns: not liability_lines: {sorted(stray)}")
        if parent in children or len(set(children)) != len(children):
            raise ContractError(f"liability_breakdowns: {parent}: repeated or self child")
    n = parsed.normalize
    return ZeroDebtRule(
        breakdowns={p: tuple(c) for p, c in parsed.liability_breakdowns.items()},
        liability_lines=frozenset(ev.liability_lines),
        debt_lines=frozenset(debt),
        interest=frozenset(set(ev.interest) | mapped((LineItem.INTEREST_EXPENSE,))),
        interest_lookback_days=n.zero_debt_interest_lookback_days,
        max_lines=n.zero_debt_max_lines,
        forms=frozenset(n.zero_debt_forms),
    )


def load_concepts(path: Path = DEFAULT_CONCEPTS_PATH) -> ConceptMap:
    return parse_concepts(yaml.safe_load(path.read_text()))
