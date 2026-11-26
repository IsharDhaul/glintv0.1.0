"""Semantic validation on top of the pydantic model (step 1).

The contract's `validate_against_registry` covers ids, liveness, comparator/unit and value
types. This adds the rules the engine needs before it compiles anything, and the warnings that
don't block a screen (a ROIC threshold of `15` is almost certainly meant as 15%).
"""

from glint.contracts.enums import Better, Unit
from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import (
    NUMERIC_CMPS,
    SPECIAL_COLUMNS,
    VS_MEDIAN_CMPS,
    Comparator,
    Condition,
    FilterValue,
    Group,
    RankMethod,
    Screen,
    ScreenIssue,
    Within,
    validate_against_registry,
)
from glint.core.errors import ContractError

# A `frac` or `pp` threshold above this in absolute value is probably a whole-number percent.
FRACTION_WARN_ABS = 2

RANK_SCORE = "rank_score"
assert RANK_SCORE in SPECIAL_COLUMNS
_FRACTION_UNITS = frozenset({Unit.FRAC, Unit.PP})
_FRACTION_CMPS = NUMERIC_CMPS | VS_MEDIAN_CMPS | {Comparator.BETWEEN}


class InvalidScreenError(ContractError):
    """The screen is well-formed JSON but can't run against this registry (422)."""

    code = "INVALID_SCREEN"

    def __init__(self, issues: list[ScreenIssue]) -> None:
        first = issues[0]
        where = ".".join(str(p) for p in first.path)
        more = f" (+{len(issues) - 1} more)" if len(issues) > 1 else ""
        super().__init__(f"{where}: {first.message}{more}")
        self.issues = issues


def _leaves(group: Group, path: list[str | int]) -> list[tuple[list[str | int], Condition]]:
    out: list[tuple[list[str | int], Condition]] = []
    for i, child in enumerate(group.children):
        child_path = [*path, "children", i]
        if isinstance(child, Group):
            out.extend(_leaves(child, child_path))
        else:
            out.append((child_path, child))
    return out


def _universe_issues(screen: Screen) -> list[ScreenIssue]:
    if not screen.universe.exchanges:
        # An empty list would silently empty the universe (an empty sectors_include means
        # "all sectors", so "none" here would read inconsistently).
        return [ScreenIssue(path=["universe", "exchanges"], message="pick at least one exchange")]
    return []


def _rank_issues(screen: Screen, registry: MetricRegistry) -> list[ScreenIssue]:
    if screen.rank is None:
        if RANK_SCORE in screen.columns:
            i = screen.columns.index(RANK_SCORE)
            return [ScreenIssue(path=["columns", i], message="rank_score needs a rank block")]
        return []
    issues: list[ScreenIssue] = []
    if screen.rank.method is RankMethod.RANK_SUM and screen.rank.within is Within.SECTOR:
        # Ordinal ranks within sectors aren't comparable across sectors of different sizes
        # (a 9-company sector can't rank worse than 9). Percentiles are; use those.
        issues.append(
            ScreenIssue(
                path=["rank", "within"],
                message="rank_sum ranks aren't comparable across sectors; "
                "use percentile_composite for within: sector",
            )
        )
    seen: set[str] = set()
    for i, f in enumerate(screen.rank.factors):
        path: list[str | int] = ["rank", "factors", i, "metric"]
        if f.metric in seen:
            issues.append(ScreenIssue(path=path, message=f"factor {f.metric!r} appears twice"))
        seen.add(f.metric)
        m = registry.get(f.metric)
        if m is not None and m.better is Better.NEUTRAL:
            issues.append(
                ScreenIssue(
                    path=path,
                    message=f"{f.metric!r} has no better direction, so it can't be a rank factor",
                )
            )
    return issues


def _fraction_warnings(screen: Screen, registry: MetricRegistry) -> list[str]:
    warnings: list[str] = []
    for path, cond in _leaves(screen.filters, ["filters"]):
        m = registry.get(cond.metric)
        if m is None or m.unit not in _FRACTION_UNITS or cond.cmp not in _FRACTION_CMPS:
            continue
        values = cond.value if isinstance(cond.value, list) else [cond.value]
        if any(isinstance(v, int | float) and abs(v) > FRACTION_WARN_ABS for v in values):
            where = ".".join(str(p) for p in path)
            warnings.append(
                f"{where}: {cond.metric} is a fraction (0.15 = 15%) but the threshold is "
                f"{cond.value}; did you mean {_as_fraction(cond.value)}?"
            )
    return warnings


def _as_fraction(value: FilterValue) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_as_fraction(v) for v in value) + "]"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{value / 100:g}"
    return str(value)


def check_screen(screen: Screen, registry: MetricRegistry) -> list[str]:
    """Raise InvalidScreenError if the screen can't run; otherwise return its warnings."""
    issues = (
        validate_against_registry(screen, registry)
        + _universe_issues(screen)
        + _rank_issues(screen, registry)
    )
    if issues:
        raise InvalidScreenError(issues)
    return _fraction_warnings(screen, registry)
