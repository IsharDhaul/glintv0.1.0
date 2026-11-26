"""The Screen DSL (v1, §5.4).

Shape-level rules are enforced by the pydantic models. Rules that need the metric registry
(ids exist and are live, comparator suits the unit) live in `validate_against_registry`, which
WT-04 calls before compiling a screen. All percentages are fractions.
"""

import math
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)

from glint.contracts.enums import (
    DEFAULT_EXCHANGES,
    NUMERIC_UNITS,
    Exchange,
    Kind,
    Sector,
    Unit,
)
from glint.contracts.metrics import MetricRegistry

DSL_VERSION = 1
MAX_GROUP_DEPTH = 3
MAX_LIMIT = 1000
MAX_SORT_THEN = 2  # secondary sort keys after the primary one


class Comparator(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"
    PCT_RANK_GTE = "pct_rank_gte"
    PCT_RANK_LTE = "pct_rank_lte"
    VS_SECTOR_MEDIAN_GTE = "vs_sector_median_gte"
    VS_SECTOR_MEDIAN_LTE = "vs_sector_median_lte"


NUMERIC_CMPS = frozenset({Comparator.GT, Comparator.GTE, Comparator.LT, Comparator.LTE})
PCT_RANK_CMPS = frozenset({Comparator.PCT_RANK_GTE, Comparator.PCT_RANK_LTE})
VS_MEDIAN_CMPS = frozenset({Comparator.VS_SECTOR_MEDIAN_GTE, Comparator.VS_SECTOR_MEDIAN_LTE})
NULL_CMPS = frozenset({Comparator.IS_NULL, Comparator.NOT_NULL})
CATEGORICAL_CMPS = frozenset({Comparator.EQ, Comparator.NEQ, Comparator.IN})

ALLOWED_CMPS: dict[Unit, frozenset[Comparator]] = {
    **{
        u: NUMERIC_CMPS | {Comparator.BETWEEN} | PCT_RANK_CMPS | VS_MEDIAN_CMPS | NULL_CMPS
        for u in NUMERIC_UNITS
    },
    Unit.BOOL: frozenset({Comparator.EQ, Comparator.NEQ}) | NULL_CMPS,
    Unit.TEXT: CATEGORICAL_CMPS | NULL_CMPS,
}

# Non-metric fields that screens may filter on, show as columns, or sort by.
CATEGORICAL_FIELDS: dict[str, Unit] = {
    "ticker": Unit.TEXT,
    "name": Unit.TEXT,
    "sector": Unit.TEXT,
    "exchange": Unit.TEXT,
    "kind": Unit.TEXT,
}
SPECIAL_COLUMNS = frozenset({"rank_score"})


class LogicOp(StrEnum):
    AND = "and"
    OR = "or"


class MissingPolicy(StrEnum):
    FAIL = "fail"
    PASS = "pass"


class Within(StrEnum):
    UNIVERSE = "universe"
    SECTOR = "sector"


class RankMethod(StrEnum):
    PERCENTILE_COMPOSITE = "percentile_composite"
    RANK_SUM = "rank_sum"


class SortDir(StrEnum):
    ASC = "asc"
    DESC = "desc"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Universe(_Strict):
    exchanges: list[Exchange] = Field(default_factory=lambda: list(DEFAULT_EXCHANGES))
    sectors_include: list[Sector] = Field(default_factory=list[Sector])
    sectors_exclude: list[Sector] = Field(default_factory=list[Sector])
    exclude_kinds: list[Kind] = Field(
        default_factory=lambda: [Kind.SPAC, Kind.FUND, Kind.SHELL, Kind.NO_COMMON_EQUITY]
    )
    include_foreign_filers: bool = True
    include_stale: bool = False
    include_no_facts: bool = False  # CIKs with tickers but no XBRL facts (§2.3)
    market_cap_min: float | None = Field(default=None, ge=0)
    market_cap_max: float | None = Field(default=None, ge=0)
    avg_dollar_volume_min: float | None = Field(default=1_000_000, ge=0)
    max_days_since_filing: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _bands(self) -> Self:
        if (
            self.market_cap_min is not None
            and self.market_cap_max is not None
            and self.market_cap_min > self.market_cap_max
        ):
            raise ValueError("market_cap_min must be ≤ market_cap_max")
        if overlap := set(self.sectors_include) & set(self.sectors_exclude):
            raise ValueError(f"sectors both included and excluded: {sorted(overlap)}")
        return self


Scalar = float | bool | str
FilterValue = Scalar | list[Scalar] | None


class Condition(_Strict):
    metric: str
    cmp: Comparator
    value: FilterValue = None
    within: Within | None = None
    missing: MissingPolicy = MissingPolicy.FAIL

    @model_validator(mode="after")
    def _value_shape(self) -> Self:
        c, v = self.cmp, self.value
        is_number = isinstance(v, int | float) and not isinstance(v, bool)
        numbers = v if isinstance(v, list) else [v]
        if any(isinstance(x, float) and not math.isfinite(x) for x in numbers):
            raise ValueError("values must be finite numbers (no NaN or infinity)")
        if c in NULL_CMPS:
            if v is not None:
                raise ValueError(f"{c} takes no value")
        elif c is Comparator.BETWEEN:
            if not (
                isinstance(v, list)
                and len(v) == 2
                and all(isinstance(x, int | float) and not isinstance(x, bool) for x in v)
            ):
                raise ValueError("between takes [lo, hi]")
            lo, hi = v
            if lo > hi:  # type: ignore[operator]
                raise ValueError("between takes [lo, hi] with lo ≤ hi")
        elif c is Comparator.IN:
            if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
                raise ValueError("in takes a non-empty list of strings")
        elif c in {Comparator.EQ, Comparator.NEQ}:
            if not isinstance(v, str | bool):
                raise ValueError(f"{c} takes a string or boolean")
        elif c in PCT_RANK_CMPS:
            if not (is_number and 0 <= v <= 1):  # type: ignore[operator]
                raise ValueError(f"{c} takes a percentile as a fraction in [0, 1]")
        elif not is_number:
            raise ValueError(f"{c} takes a number")

        if c in PCT_RANK_CMPS:
            if self.within is None:
                self.within = Within.UNIVERSE
        elif self.within is not None:
            raise ValueError("within applies only to pct_rank comparators")
        return self


def _node_kind(value: Any) -> str:
    if isinstance(value, dict):
        return "group" if "op" in value else "condition"
    return "group" if isinstance(value, Group) else "condition"


FilterNode = Annotated[
    Annotated[Condition, Tag("condition")] | Annotated["Group", Tag("group")],
    Discriminator(_node_kind),
]


class Group(_Strict):
    op: LogicOp
    children: list[FilterNode] = Field(default_factory=list[FilterNode])

    def depth(self) -> int:
        return 1 + max((c.depth() for c in self.children if isinstance(c, Group)), default=0)

    def conditions(self) -> list[Condition]:
        out: list[Condition] = []
        for c in self.children:
            out.extend(c.conditions() if isinstance(c, Group) else [c])
        return out


class Factor(_Strict):
    metric: str
    weight: float = Field(gt=0)


class Rank(_Strict):
    method: RankMethod = RankMethod.PERCENTILE_COMPOSITE
    within: Within = Within.UNIVERSE
    factors: list[Factor] = Field(min_length=1)
    min_factor_coverage: float = Field(default=0.7, gt=0, le=1)


class SortKey(_Strict):
    by: str
    dir: SortDir = SortDir.DESC


class Sort(SortKey):
    then: list[SortKey] = Field(
        default_factory=list[SortKey],
        max_length=MAX_SORT_THEN,
        description="Tie-breakers after `by`, in order; ticker ascending always breaks what's "
        "left. Nulls sort last for every key.",
    )

    def all_keys(self) -> list[SortKey]:
        """`by` first, then each `then` key."""
        return [SortKey(by=self.by, dir=self.dir), *self.then]

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        bys = [k.by for k in self.all_keys()]
        if len(set(bys)) != len(bys):
            raise ValueError("sort keys must be unique")
        return self


DEFAULT_COLUMNS = ["ticker", "name", "sector", "market_cap"]


class Screen(_Strict):
    dsl_version: Literal[1] = DSL_VERSION
    name: str = "Untitled screen"
    universe: Universe = Field(default_factory=Universe)
    filters: Group = Field(default_factory=lambda: Group(op=LogicOp.AND))
    rank: Rank | None = None
    columns: list[str] = Field(default_factory=lambda: list(DEFAULT_COLUMNS), min_length=1)
    sort: Sort | None = Field(
        default=None, description="Omitted: rank_score desc when ranked, else ticker asc"
    )
    limit: int = Field(default=100, ge=1, le=MAX_LIMIT)
    near_misses: bool = True

    @field_validator("columns")
    @classmethod
    def _unique_columns(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("columns must be unique")
        return value

    @model_validator(mode="after")
    def _structure(self) -> Self:
        if self.filters.depth() > MAX_GROUP_DEPTH:
            raise ValueError(f"filter groups nest at most {MAX_GROUP_DEPTH} deep")
        _require_non_empty_nested(self.filters)
        return self


def _require_non_empty_nested(group: Group) -> None:
    for child in group.children:
        if isinstance(child, Group):
            if not child.children:
                raise ValueError("nested filter groups need at least one child")
            _require_non_empty_nested(child)


class ScreenIssue(BaseModel):
    """One semantic problem with a screen; `path` locates it (for 422 INVALID_SCREEN)."""

    path: list[str | int]
    message: str


def _field_unit(field: str, registry: MetricRegistry) -> Unit | None:
    if field in CATEGORICAL_FIELDS:
        return CATEGORICAL_FIELDS[field]
    m = registry.get(field)
    return m.unit if m else None


def _check_metric(
    metric_id: str, path: list[str | int], registry: MetricRegistry, issues: list[ScreenIssue]
) -> Unit | None:
    if metric_id in CATEGORICAL_FIELDS:
        return CATEGORICAL_FIELDS[metric_id]
    if metric_id not in registry:
        issues.append(ScreenIssue(path=path, message=f"unknown metric {metric_id!r}"))
        return None
    if not registry.is_live(metric_id):
        issues.append(ScreenIssue(path=path, message=f"metric {metric_id!r} is not live yet"))
        return None
    return _field_unit(metric_id, registry)


def _walk(
    group: Group, path: list[str | int], registry: MetricRegistry, issues: list[ScreenIssue]
) -> None:
    for i, child in enumerate(group.children):
        child_path = [*path, "children", i]
        if isinstance(child, Group):
            _walk(child, child_path, registry, issues)
            continue
        unit = _check_metric(child.metric, [*child_path, "metric"], registry, issues)
        if unit is None:
            continue
        if child.cmp not in ALLOWED_CMPS[unit]:
            issues.append(
                ScreenIssue(
                    path=[*child_path, "cmp"],
                    message=f"{child.cmp} is not allowed for {child.metric!r} (unit {unit})",
                )
            )
            continue
        if problem := _value_problem(child, unit):
            issues.append(ScreenIssue(path=[*child_path, "value"], message=problem))


# Allowed values for categorical fields that have a closed vocabulary.
CATEGORICAL_VALUES: dict[str, frozenset[str]] = {
    "sector": frozenset(s.value for s in Sector),
    "exchange": frozenset(e.value for e in Exchange),
    "kind": frozenset(k.value for k in Kind),
}


def _value_problem(cond: Condition, unit: Unit) -> str | None:
    """The value must suit the field's unit (the model already checked its shape)."""
    if cond.cmp in NULL_CMPS:
        return None
    values = cond.value if isinstance(cond.value, list) else [cond.value]
    if unit is Unit.BOOL and not all(isinstance(x, bool) for x in values):
        return f"{cond.metric!r} is bool: compare with true or false"
    if unit is Unit.TEXT:
        if not all(isinstance(x, str) for x in values):
            return f"{cond.metric!r} is text: compare with strings"
        allowed = CATEGORICAL_VALUES.get(cond.metric)
        if allowed is not None and (bad := sorted(str(x) for x in values if x not in allowed)):
            return f"unknown {cond.metric} value(s): {bad}"
    return None


def validate_against_registry(screen: Screen, registry: MetricRegistry) -> list[ScreenIssue]:
    """Rules needing the registry: metric ids exist and are live; comparators suit units;
    rank factors are numeric; columns and sort keys are known. Empty list = valid."""
    issues: list[ScreenIssue] = []
    _walk(screen.filters, ["filters"], registry, issues)
    if screen.rank is not None:
        for i, f in enumerate(screen.rank.factors):
            path: list[str | int] = ["rank", "factors", i, "metric"]
            unit = _check_metric(f.metric, path, registry, issues)
            if unit is not None and unit not in NUMERIC_UNITS:
                issues.append(ScreenIssue(path=path, message=f"{f.metric!r} is not numeric"))
    for i, col in enumerate(screen.columns):
        if col not in SPECIAL_COLUMNS:
            _check_metric(col, ["columns", i], registry, issues)
    if screen.sort is not None:
        for i, key in enumerate(screen.sort.all_keys()):
            path: list[str | int] = ["sort", "by"] if i == 0 else ["sort", "then", i - 1, "by"]
            if key.by not in SPECIAL_COLUMNS:
                _check_metric(key.by, path, registry, issues)
            elif screen.rank is None:
                issues.append(ScreenIssue(path=path, message="rank_score needs a rank block"))
    return issues
