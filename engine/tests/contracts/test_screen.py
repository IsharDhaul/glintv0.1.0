from typing import Any

import pytest
from pydantic import ValidationError

from glint.contracts.enums import (
    Basis,
    Better,
    Category,
    Kind,
    MetricStatus,
    Priority,
    Tier,
    Unit,
)
from glint.contracts.metrics import MetricDefinition, MetricRegistry
from glint.contracts.screen import Group, Screen, Within, validate_against_registry

PLAN_EXAMPLE: dict[str, Any] = {
    "dsl_version": 1,
    "name": "Quality at a fair price",
    "universe": {
        "exchanges": ["NYSE", "Nasdaq", "NYSE American"],
        "sectors_include": [],
        "sectors_exclude": ["Banks", "Insurance"],
        "exclude_kinds": ["spac", "fund", "shell"],
        "include_foreign_filers": True,
        "include_stale": False,
        "market_cap_min": 300000000,
        "market_cap_max": None,
        "avg_dollar_volume_min": 1000000,
    },
    "filters": {
        "op": "and",
        "children": [
            {"metric": "roic", "cmp": "gte", "value": 0.15},
            {"metric": "fcf_yield", "cmp": "gte", "value": 0.05},
            {"metric": "net_debt_to_ebitda", "cmp": "lte", "value": 2.0, "missing": "pass"},
            {"metric": "gross_margin", "cmp": "pct_rank_gte", "value": 0.7, "within": "sector"},
            {
                "op": "or",
                "children": [
                    {"metric": "revenue_growth_yoy", "cmp": "gte", "value": 0.05},
                    {"metric": "operating_margin_change_yoy", "cmp": "gte", "value": 0.02},
                ],
            },
        ],
    },
    "rank": {
        "method": "percentile_composite",
        "within": "universe",
        "factors": [{"metric": "roic", "weight": 0.5}, {"metric": "fcf_yield", "weight": 0.5}],
        "min_factor_coverage": 0.7,
    },
    "columns": [
        "ticker",
        "name",
        "sector",
        "market_cap",
        "roic",
        "fcf_yield",
        "net_debt_to_ebitda",
    ],
    "sort": {"by": "rank_score", "dir": "desc"},
    "limit": 100,
    "near_misses": True,
}


def metric(mid: str, unit: Unit = Unit.FRAC, status: MetricStatus = MetricStatus.LIVE):
    return MetricDefinition(
        id=mid,
        name=mid,
        category=Category.PROFITABILITY,
        unit=unit,
        better=Better.HIGHER,
        tier=Tier.SEC,
        priority=Priority.P0,
        basis=Basis.TTM,
        definition="test",
        inputs=["revenue"],
        status=status,
    )


REGISTRY = MetricRegistry(
    [
        metric("roic"),
        metric("fcf_yield"),
        metric("net_debt_to_ebitda", Unit.X),
        metric("gross_margin"),
        metric("revenue_growth_yoy"),
        metric("operating_margin_change_yoy", Unit.PP),
        metric("market_cap", Unit.USD),
        metric("dps_no_cut_5y", Unit.BOOL),
        metric("altman_z", Unit.SCORE, MetricStatus.PLANNED),
    ]
)


def screen_with(*children: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"filters": {"op": "and", "children": list(children)}, **extra}


def test_plan_example_parses_and_validates() -> None:
    s = Screen.model_validate(PLAN_EXAMPLE)
    assert s.filters.depth() == 2
    assert len(s.filters.conditions()) == 6
    assert validate_against_registry(s, REGISTRY) == []


def test_roundtrips_through_json() -> None:
    s = Screen.model_validate(PLAN_EXAMPLE)
    assert Screen.model_validate_json(s.model_dump_json()) == s


def test_defaults() -> None:
    s = Screen()
    assert [e.value for e in s.universe.exchanges] == ["NYSE", "Nasdaq", "NYSE American", "TXSE"]
    assert s.universe.avg_dollar_volume_min == 1_000_000
    assert s.limit == 100
    assert s.sort is None
    assert [k.value for k in s.universe.exclude_kinds] == [
        "spac",
        "fund",
        "shell",
        "no_common_equity",
    ]


def test_screens_from_before_no_common_equity_still_validate() -> None:
    """A screen saved with the old three-kind list parses unchanged (no default is merged in);
    one that omits exclude_kinds gets the new default, and the new kind is a valid value."""
    old = Screen.model_validate(PLAN_EXAMPLE)
    assert [k.value for k in old.universe.exclude_kinds] == ["spac", "fund", "shell"]
    assert validate_against_registry(old, REGISTRY) == []
    universe = {k: v for k, v in PLAN_EXAMPLE["universe"].items() if k != "exclude_kinds"}
    omitted = Screen.model_validate({**PLAN_EXAMPLE, "universe": universe})
    assert Kind.NO_COMMON_EQUITY in omitted.universe.exclude_kinds
    kind_filter = screen_with({"metric": "kind", "cmp": "neq", "value": "no_common_equity"})
    assert validate_against_registry(Screen.model_validate(kind_filter), REGISTRY) == []


@pytest.mark.parametrize(
    "cond",
    [
        {"metric": "roic", "cmp": "between", "value": [0.2, 0.1]},
        {"metric": "roic", "cmp": "between", "value": [0.1]},
        {"metric": "roic", "cmp": "gte", "value": "high"},
        {"metric": "roic", "cmp": "is_null", "value": 1},
        {"metric": "roic", "cmp": "pct_rank_gte", "value": 70},
        {"metric": "roic", "cmp": "gte", "value": 0.1, "within": "sector"},
        {"metric": "sector", "cmp": "in", "value": []},
        {"metric": "roic", "cmp": "gte", "value": 0.1, "missing": "maybe"},
        {"metric": "roic", "cmp": "gte", "value": 0.1, "extra": 1},
    ],
)
def test_bad_conditions_rejected(cond: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Screen.model_validate(screen_with(cond))


def test_between_inclusive_equal_bounds_ok() -> None:
    Screen.model_validate(screen_with({"metric": "roic", "cmp": "between", "value": [0.1, 0.1]}))


def test_pct_rank_defaults_to_universe() -> None:
    s = Screen.model_validate(screen_with({"metric": "roic", "cmp": "pct_rank_gte", "value": 0.7}))
    cond = s.filters.conditions()[0]
    assert cond.within is Within.UNIVERSE


def leaf() -> dict[str, Any]:
    return {"metric": "roic", "cmp": "gte", "value": 0.1}


def test_depth_three_ok_four_rejected() -> None:
    three = {"op": "or", "children": [{"op": "and", "children": [leaf()]}]}
    s = Screen.model_validate(screen_with(three))
    assert s.filters.depth() == 3
    four = {
        "op": "or",
        "children": [{"op": "and", "children": [{"op": "or", "children": [leaf()]}]}],
    }
    with pytest.raises(ValidationError, match="at most 3 deep"):
        Screen.model_validate(screen_with(four))


def test_empty_nested_group_rejected() -> None:
    with pytest.raises(ValidationError):
        Screen.model_validate(screen_with({"op": "or", "children": []}))


@pytest.mark.parametrize("weight", [0, -1])
def test_weights_must_be_positive(weight: float) -> None:
    with pytest.raises(ValidationError):
        Screen.model_validate({"rank": {"factors": [{"metric": "roic", "weight": weight}]}})


@pytest.mark.parametrize("limit", [0, 1001])
def test_limit_bounds(limit: int) -> None:
    with pytest.raises(ValidationError):
        Screen.model_validate({"limit": limit})
    Screen.model_validate({"limit": 1000})


def test_dsl_version_fixed() -> None:
    with pytest.raises(ValidationError):
        Screen.model_validate({"dsl_version": 2})


def test_registry_rules() -> None:
    s = Screen.model_validate(
        screen_with(
            {"metric": "nope", "cmp": "gte", "value": 1},
            {"metric": "altman_z", "cmp": "gte", "value": 3},
            {"metric": "roic", "cmp": "in", "value": ["a"]},
            {"metric": "dps_no_cut_5y", "cmp": "pct_rank_gte", "value": 0.5},
            {"metric": "dps_no_cut_5y", "cmp": "eq", "value": True},
            {"metric": "sector", "cmp": "in", "value": ["Technology"]},
            {"metric": "sector", "cmp": "gte", "value": 1},
            columns=["ticker", "bogus"],
            sort={"by": "rank_score"},
        )
    )
    issues = {tuple(i.path): i.message for i in validate_against_registry(s, REGISTRY)}
    assert "unknown metric" in issues[("filters", "children", 0, "metric")]
    assert "not live" in issues[("filters", "children", 1, "metric")]
    assert ("filters", "children", 2, "cmp") in issues
    assert ("filters", "children", 3, "cmp") in issues
    assert ("filters", "children", 4, "cmp") not in issues
    assert ("filters", "children", 5, "cmp") not in issues
    assert ("filters", "children", 6, "cmp") in issues
    assert ("columns", 1) in issues
    assert ("sort", "by") in issues


def test_sort_then_is_additive() -> None:
    old = Screen.model_validate(screen_with(sort={"by": "roic", "dir": "asc"}))
    assert old.sort is not None and old.sort.then == []  # saved screens without `then` parse
    s = Screen.model_validate(
        screen_with(sort={"by": "roic", "then": [{"by": "sector", "dir": "asc"}, {"by": "name"}]})
    )
    assert s.sort is not None
    assert [(k.by, k.dir.value) for k in s.sort.all_keys()] == [
        ("roic", "desc"),
        ("sector", "asc"),
        ("name", "desc"),
    ]
    assert Screen.model_validate_json(s.model_dump_json()) == s


@pytest.mark.parametrize(
    ("then", "match"),
    [
        ([{"by": "sector"}, {"by": "name"}, {"by": "ticker"}], "at most 2"),
        ([{"by": "roic"}], "sort keys must be unique"),
        ([{"by": "sector", "then": "name"}], "Extra inputs"),
    ],
)
def test_sort_then_shape_rules(then: list[dict[str, Any]], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        Screen.model_validate(screen_with(sort={"by": "roic", "then": then}))


def test_sort_then_keys_are_checked_against_the_registry() -> None:
    s = Screen.model_validate(
        screen_with(sort={"by": "roic", "then": [{"by": "altman_z"}, {"by": "rank_score"}]})
    )
    issues = {tuple(i.path): i.message for i in validate_against_registry(s, REGISTRY)}
    assert ("sort", "by") not in issues
    assert "not live" in issues[("sort", "then", 0, "by")]
    assert "needs a rank block" in issues[("sort", "then", 1, "by")]


def test_treat_all_as_live() -> None:
    reg = MetricRegistry(list(REGISTRY), treat_all_as_live=True)
    s = Screen.model_validate(screen_with({"metric": "altman_z", "cmp": "gte", "value": 3}))
    assert validate_against_registry(s, reg) == []


def test_group_type_dispatch() -> None:
    s = Screen.model_validate(PLAN_EXAMPLE)
    assert isinstance(s.filters.children[4], Group)


@pytest.mark.parametrize(
    "cond",
    [
        {"metric": "dps_no_cut_5y", "cmp": "eq", "value": "yes"},
        {"metric": "sector", "cmp": "eq", "value": True},
        {"metric": "sector", "cmp": "in", "value": ["Bankz"]},
        {"metric": "exchange", "cmp": "eq", "value": "LSE"},
    ],
)
def test_registry_rejects_values_that_dont_suit_the_unit(cond: dict[str, Any]) -> None:
    s = Screen.model_validate(screen_with(cond))
    issues = validate_against_registry(s, REGISTRY)
    assert [i.path for i in issues] == [["filters", "children", 0, "value"]]


def test_known_categorical_values_pass() -> None:
    s = Screen.model_validate(
        screen_with(
            {"metric": "sector", "cmp": "in", "value": ["Banks", "Technology"]},
            {"metric": "kind", "cmp": "neq", "value": "spac"},
        )
    )
    assert validate_against_registry(s, REGISTRY) == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), [0.0, float("nan")]])
def test_non_finite_values_rejected(value: Any) -> None:
    cmp = "between" if isinstance(value, list) else "gte"
    with pytest.raises(ValidationError, match="finite"):
        Screen.model_validate(screen_with({"metric": "roic", "cmp": cmp, "value": value}))
