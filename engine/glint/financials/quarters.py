"""Fiscal years and discrete quarters (§4.3 rule 5). Pure.

Quarters come from filed 3-month facts where they exist. Otherwise a quarter is the difference of
two year-to-date values with the same start: Q2 = H1 − Q1, Q3 = 9M − H1, Q4 = FY − 9M. When the
earlier year-to-date value isn't filed, the sum of the contiguous quarters it covers stands in
(the same arithmetic). Both sides must come from the same tag(s) (`Value.tag_key`). When the
winning tags differ, the same tag filed for both periods is used instead (`alternatives`);
otherwise the quarter stays unknown. Derived quarters carry `quarter_derived=True`.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from glint.financials.concepts import DurationBounds, DurationClass
from glint.financials.periods import Period, classify, next_day
from glint.financials.select import Alternatives, Value, as_lineage

_YTD = (
    DurationClass.QUARTER,
    DurationClass.HALF_YEAR,
    DurationClass.NINE_MONTHS,
    DurationClass.FISCAL_YEAR,
)


def _latest_per_end(values: list[Value]) -> dict[date, Value]:
    """One value per end date: the latest filed (then the later start) when several share it."""
    out: dict[date, Value] = {}
    for v in sorted(values, key=lambda v: (v.filed, v.period.start or v.period.end)):
        out[v.period.end] = v
    return out


def fiscal_years(values: Mapping[Period, Value], bounds: DurationBounds) -> dict[date, Value]:
    """FY values keyed by period end."""
    fys = [v for p, v in values.items() if classify(p, bounds) is DurationClass.FISCAL_YEAR]
    return dict(sorted(_latest_per_end(fys).items()))


@dataclass(frozen=True, slots=True)
class _Cum:
    """A year-to-date amount from `start` to `end`: filed, or summed from discrete quarters."""

    value: float
    first: float | None
    first_date: date | None
    parts: tuple[Value, ...]


def _sum_quarters(start: date, end: date, quarters: Mapping[date, Value], gap: int) -> _Cum | None:
    """The contiguous discrete quarters from `start` through `end`, if they're all known."""
    chain: list[Value] = []
    by_start = {q.period.start: q for q in quarters.values()}
    cursor = start
    while True:
        q = by_start.get(cursor)
        if q is None or q.period.end > end:
            return None
        chain.append(q)
        if q.period.end == end:
            break
        cursor = next_day(q.period.end, gap)
    firsts = [q.first_filed_value for q in chain]
    has_first = all(f is not None for f in firsts)
    return _Cum(
        value=sum(q.value for q in chain),
        first=sum(f for f in firsts if f is not None) if has_first else None,
        first_date=max(q.first_filed_date or q.filed for q in chain) if has_first else None,
        parts=tuple(chain),
    )


def _difference(ytd: Value, cum: _Cum, period: Period) -> Value:
    parts = (ytd, *cum.parts)
    latest = max(parts, key=lambda v: (v.filed, v.source_accn or ""))
    first = (
        ytd.first_filed_value - cum.first
        if ytd.first_filed_value is not None and cum.first is not None
        else None
    )
    first_dates = [d for d in (ytd.first_filed_date, cum.first_date) if d is not None]
    return Value(
        item=ytd.item,
        period=period,
        value=ytd.value - cum.value,
        unit=ytd.unit,
        source_tag=None,
        source_accn=latest.source_accn,
        filed=latest.filed,
        first_filed_value=first,
        first_filed_date=max(first_dates) if first is not None else None,
        derived=any(p.derived for p in parts),
        quarter_derived=True,
        inputs=(
            f"{ytd.period.label()} − {ytd.period.start}..{cum.parts[-1].period.end}"
            f" [{ytd.tag_key}]",
        ),
        lineage=ytd.tag_key,
    )


def _filed_pair(v: Value, earlier: Value, alts: Alternatives) -> tuple[Value, _Cum] | None:
    """The longer and earlier year-to-date under one lineage: v's tag first, then the earlier's."""
    for key in (v.tag_key, earlier.tag_key):
        a, b = as_lineage(v, key, alts), as_lineage(earlier, key, alts)
        if a is not None and b is not None:
            return a, _Cum(b.value, b.first_filed_value, b.first_filed_date, (b,))
    return None


def _summed_pair(v: Value, cum: _Cum | None, alts: Alternatives) -> tuple[Value, _Cum] | None:
    """Summed quarters stand in for the earlier year-to-date only if they share one lineage."""
    if cum is None:
        return None
    keys = {p.tag_key for p in cum.parts}
    if len(keys) != 1:
        return None
    a = as_lineage(v, keys.pop(), alts)
    return (a, cum) if a is not None else None


def discrete_quarters(
    values: Mapping[Period, Value],
    bounds: DurationBounds,
    *,
    additive: bool = True,
    gap_days: int = 1,
    alternatives: Alternatives | None = None,
) -> dict[date, Value]:
    """Discrete quarters keyed by period end, oldest first."""
    alts = alternatives or {}
    classes = {p: classify(p, bounds) for p in values}
    filed_quarters = [v for p, v in values.items() if classes[p] is DurationClass.QUARTER]
    quarters = _latest_per_end(filed_quarters)
    if not additive:
        return dict(sorted(quarters.items()))

    # Year-to-date values grouped by their start date.
    ytd: dict[date, dict[date, Value]] = defaultdict(dict)
    for p, v in values.items():
        if p.start is not None and classes[p] in _YTD:
            ytd[p.start][p.end] = v

    longer = sorted(
        (v for p, v in values.items() if classes[p] in _YTD[1:]),
        key=lambda v: (v.period.end, v.period.start),
    )
    for v in longer:
        end, start = v.period.end, v.period.start
        assert start is not None
        if end in quarters:
            continue
        # The latest earlier cut-off inside this year whose remainder is one quarter.
        cuts = sorted(
            {e for e in ytd[start] if e < end} | {q for q in quarters if start <= q < end},
            reverse=True,
        )
        for cut in cuts:
            period = Period(end=end, start=next_day(cut, gap_days))
            if classify(period, bounds) is not DurationClass.QUARTER:
                continue
            filed = ytd[start].get(cut)
            pair = _filed_pair(v, filed, alts) if filed is not None else None
            if pair is None:
                pair = _summed_pair(v, _sum_quarters(start, cut, quarters, gap_days), alts)
            if pair is not None:
                quarters[end] = _difference(*pair, period)
                break
    return dict(sorted(quarters.items()))
