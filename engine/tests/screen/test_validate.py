from typing import Any

import pytest
from pydantic import ValidationError

from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import Screen
from glint.screen.validate import InvalidScreenError, check_screen


def _screen(**overrides: Any) -> Screen:
    return Screen.model_validate(overrides)


def _cond(metric: str, cmp: str, value: Any = None, **kw: Any) -> dict[str, Any]:
    return {"metric": metric, "cmp": cmp, "value": value, **kw}


def test_valid_screen_has_no_warnings(live_registry: MetricRegistry) -> None:
    s = _screen(filters={"op": "and", "children": [_cond("roic", "gte", 0.15)]})
    assert check_screen(s, live_registry) == []


def test_unknown_metric_is_rejected(live_registry: MetricRegistry) -> None:
    s = _screen(filters={"op": "and", "children": [_cond("roic; DROP TABLE", "gte", 0.15)]})
    with pytest.raises(InvalidScreenError) as exc:
        check_screen(s, live_registry)
    assert exc.value.issues[0].path == ["filters", "children", 0, "metric"]
    assert "unknown metric" in exc.value.message


def test_planned_metric_is_rejected_unless_synthetic(
    live_registry: MetricRegistry, strict_registry: MetricRegistry
) -> None:
    s = _screen(filters={"op": "and", "children": [_cond("roic", "gte", 0.15)]})
    with pytest.raises(InvalidScreenError, match="not live"):
        check_screen(s, strict_registry)
    assert check_screen(s, live_registry) == []


def test_comparator_must_suit_unit(live_registry: MetricRegistry) -> None:
    s = _screen(filters={"op": "and", "children": [_cond("dps_no_cut_5y", "pct_rank_gte", 0.5)]})
    with pytest.raises(InvalidScreenError, match="not allowed"):
        check_screen(s, live_registry)


def test_between_order_weights_and_depth_are_shape_errors() -> None:
    with pytest.raises(ValidationError, match="lo ≤ hi"):
        _screen(filters={"op": "and", "children": [_cond("pe_ttm", "between", [20, 8])]})
    with pytest.raises(ValidationError):
        _screen(rank={"factors": [{"metric": "roic", "weight": 0}]})
    leaf = _cond("roic", "gte", 0.1)
    deep = {"op": "and", "children": [{"op": "or", "children": [
        {"op": "and", "children": [{"op": "or", "children": [leaf]}]}]}]}  # fmt: skip
    with pytest.raises(ValidationError, match="3 deep"):
        _screen(filters=deep)


def test_neutral_and_duplicate_rank_factors_are_rejected(live_registry: MetricRegistry) -> None:
    s = _screen(rank={"factors": [{"metric": "market_cap", "weight": 1}]})
    with pytest.raises(InvalidScreenError, match="no better direction"):
        check_screen(s, live_registry)
    s = _screen(
        rank={"factors": [{"metric": "roic", "weight": 1}, {"metric": "roic", "weight": 2}]}
    )
    with pytest.raises(InvalidScreenError, match="twice"):
        check_screen(s, live_registry)


def test_whole_number_percent_warns(live_registry: MetricRegistry) -> None:
    s = _screen(
        filters={
            "op": "and",
            "children": [
                _cond("roic", "gte", 15),
                _cond("pe_ttm", "lte", 15),  # a multiple: fine
                _cond("gross_margin", "between", [0.2, 40]),
            ],
        }
    )
    warnings = check_screen(s, live_registry)
    assert len(warnings) == 2
    assert "did you mean 0.15" in warnings[0]
    assert "filters.children.2" in warnings[1]


def test_rank_score_column_needs_a_rank(live_registry: MetricRegistry) -> None:
    with pytest.raises(InvalidScreenError, match="rank_score needs a rank block") as exc:
        check_screen(_screen(columns=["ticker", "rank_score"]), live_registry)
    assert exc.value.issues[0].path == ["columns", 1]


def test_rank_sum_within_sector_is_rejected(live_registry: MetricRegistry) -> None:
    s = _screen(
        rank={
            "method": "rank_sum",
            "within": "sector",
            "factors": [{"metric": "roic", "weight": 1}, {"metric": "fcf_yield", "weight": 1}],
        }
    )
    with pytest.raises(InvalidScreenError, match="percentile_composite"):
        check_screen(s, live_registry)


def test_empty_exchanges_is_rejected(live_registry: MetricRegistry) -> None:
    with pytest.raises(InvalidScreenError, match="at least one exchange"):
        check_screen(_screen(universe={"exchanges": []}), live_registry)
