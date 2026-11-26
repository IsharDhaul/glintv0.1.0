"""Human labels for funnel steps and near misses. Display only; never used in SQL."""

from glint.contracts.enums import Unit
from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import (
    CATEGORICAL_FIELDS,
    PCT_RANK_CMPS,
    VS_MEDIAN_CMPS,
    Comparator,
    Condition,
    FilterValue,
    Group,
    LogicOp,
    Within,
)

_SYMBOLS = {
    Comparator.GT: ">",
    Comparator.GTE: "≥",
    Comparator.LT: "<",
    Comparator.LTE: "≤",
    Comparator.EQ: "=",
    Comparator.NEQ: "≠",
    Comparator.PCT_RANK_GTE: "≥",
    Comparator.PCT_RANK_LTE: "≤",
    Comparator.VS_SECTOR_MEDIAN_GTE: "≥",
    Comparator.VS_SECTOR_MEDIAN_LTE: "≤",
}


def format_value(value: FilterValue, unit: Unit) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        return ", ".join(format_value(v, unit) for v in value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return value
    if unit is Unit.FRAC:
        return f"{value * 100:.1f}%"
    if unit is Unit.PP:
        return f"{value * 100:+.1f} pp"
    if unit is Unit.X:
        return f"{value:.1f}x"
    if unit is Unit.USD:
        for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(value) >= size:
                return f"${value / size:.1f}{suffix}"
        return f"${value:,.0f}"
    if unit is Unit.DAYS:
        return f"{value:.0f} days"
    return f"{value:g}"


def _name_unit(metric: str, registry: MetricRegistry) -> tuple[str, Unit]:
    if metric in CATEGORICAL_FIELDS:
        return metric.capitalize(), CATEGORICAL_FIELDS[metric]
    m = registry.get(metric)
    return (m.name, m.unit) if m else (metric, Unit.SCORE)


def condition_label(cond: Condition, registry: MetricRegistry) -> str:
    name, unit = _name_unit(cond.metric, registry)
    c, v = cond.cmp, cond.value
    if c is Comparator.IS_NULL:
        return f"{name} is missing"
    if c is Comparator.NOT_NULL:
        return f"{name} is present"
    if c is Comparator.BETWEEN:
        assert isinstance(v, list)
        return f"{name} between {format_value(v[0], unit)} and {format_value(v[1], unit)}"
    if c is Comparator.IN:
        return f"{name} in [{format_value(v, unit)}]"
    if c in PCT_RANK_CMPS:
        scope = "sector" if cond.within is Within.SECTOR else "universe"
        assert isinstance(v, int | float)
        return f"{name} percentile {_SYMBOLS[c]} {v * 100:.0f} ({scope})"
    if c in VS_MEDIAN_CMPS:
        if unit in (Unit.FRAC, Unit.PP):
            assert isinstance(v, int | float)
            gap = f"{v * 100:+.1f} pp"
            return f"{name} {_SYMBOLS[c]} sector median {gap}"
        return f"{name} {_SYMBOLS[c]} {v:g}× sector median"
    return f"{name} {_SYMBOLS[c]} {format_value(v, unit)}"


def node_label(node: Condition | Group, registry: MetricRegistry) -> str:
    if isinstance(node, Condition):
        return condition_label(node, registry)
    word = "All of" if node.op is LogicOp.AND else "Any of"
    return f"{word}: " + "; ".join(node_label(c, registry) for c in node.children)
