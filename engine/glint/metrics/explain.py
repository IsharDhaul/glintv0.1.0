"""`glint metrics TICKER --explain ID`: the formula, every input with its value, period, source tag
and accession, and the result. The company is recomputed from the build's own tables with the
same functions the stage ran, so the explanation can't drift from the stored value."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

from glint.contracts.enums import LineItem, Unit
from glint.contracts.metrics import MetricDefinition, MetricRegistry
from glint.metrics.core import REGISTRY, In
from glint.metrics.inputs import MRQ, MRQ_1Y, Slot
from glint.metrics.params import Params


@dataclass(frozen=True)
class InputLine:
    label: str
    value: Any
    period: str
    source: str
    note: str | None = None


def fmt_value(v: Any, unit: Unit | None = None) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, date):
        return v.isoformat()
    x = float(v)
    match unit:
        case Unit.FRAC:
            return f"{x:.1%}"
        case Unit.PP:
            return f"{x * 100:+.1f} pp"
        case Unit.X:
            return f"{x:,.2f}x"
        case Unit.DAYS:
            return f"{x:,.0f} days"
        case Unit.SCORE:
            return f"{x:,.2f}".rstrip("0").rstrip(".")
        case _:
            return f"{x / 1e6:,.1f}M" if abs(x) >= 1e5 else f"{x:,.4g}"


def _source(fin: pl.DataFrame, item: LineItem, basis: str, end: date | None) -> tuple[str, str]:
    if end is None:
        return "—", "no period"
    at = fin.filter((pl.col("line_item") == item.value) & (pl.col("period_end") == end))
    hit = at.filter(pl.col("basis") == basis)
    if hit.is_empty() and basis == "q":  # a fiscal year end: Q4 isn't filed, the FY row is used
        hit, basis = at.filter(pl.col("basis") == "fy"), "fy"
    if hit.is_empty():
        return f"{basis.upper()} {end}", "not in the filings for this period"
    r = hit.row(0, named=True)
    start = f"{r['period_start']}..{end}" if r["period_start"] else str(end)
    period = f"{basis.upper()} {start}"
    if r["source_tag"]:
        src = f"{r['source_tag']} · {r['source_accn']}"
    elif r["derived"]:
        src = f"derived (§4.3 rule 9) · latest {r['source_accn']}"
    else:
        src = f"Σ quarters or FY + YTD bridge · latest {r['source_accn']}"
    return period, src


def input_lines(i: In, row: pl.DataFrame, fin: pl.DataFrame) -> list[InputLine]:
    value = row.select(i.value).item()
    note = None if value is not None else row.select(i.message).item()
    r = row.row(0, named=True)
    if i.metric_id is not None:
        code, msg = r[f"{i.metric_id}__code"], r[f"{i.metric_id}__msg"]
        return [InputLine(f"{i.label} (metric)", value, "", f"{code}: {msg}" if code else "", note)]
    if i.item is None:  # a price-stats input
        return [InputLine(i.label, value, f"close of {r['price_as_of']}",
                          f"price_stats {r['primary_ticker']} (tier 2)", note)]  # fmt: skip
    slots: list[Slot] = [i.slot] if i.slot is not None else [MRQ, MRQ_1Y]
    out: list[InputLine] = []
    for s in slots:
        period, src = _source(fin, i.item, s.basis.value, r[s.end_col])
        label = i.label if i.slot is not None else f"{i.item.value}_{s.name}"
        v = value if i.slot is not None else r.get(f"{i.item.value}__{s.name}")
        out.append(InputLine(label, v, period, src, note))
    if i.slot is None:
        out.append(InputLine(i.label, value, "average of the two", "", note))
    return out


def explain(
    metric_id: str, frame: pl.DataFrame, fin: pl.DataFrame, registry: MetricRegistry, p: Params
) -> tuple[MetricDefinition, list[InputLine], Any, str | None, str | None]:
    """(definition, input lines, value, note code, note message) for one company's frame row."""
    m = registry.get(metric_id)
    fn = REGISTRY.get(metric_id)
    if m is None or fn is None:
        raise KeyError(metric_id)
    e = fn(p)
    lines = [ln for i in e.inputs for ln in input_lines(i, frame, fin)]
    r = frame.row(0, named=True)
    return m, lines, r[metric_id], r[f"{metric_id}__code"], r[f"{metric_id}__msg"]
