"""Trailing twelve months for flows (§4.3 rule 6). Pure.

TTM at a quarter end is the sum of the 4 discrete quarters ending there, which must be contiguous
and must not straddle a fiscal-year change (rule 14). At a fiscal year end, TTM is the FY value,
and the sum of the 4 quarters is checked against it. When the 4 quarters aren't all known, TTM is
FY + year-to-date − the prior year's year-to-date of the same length (the same arithmetic over
filed cumulative values, all three from the same tag(s)), under the same span and fiscal-year-change
checks.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from glint.financials.concepts import DurationBounds, DurationClass
from glint.financials.periods import Period, classify, is_contiguous, next_day
from glint.financials.select import Alternatives, Value, as_lineage


@dataclass
class TtmResult:
    values: dict[date, Value] = field(default_factory=dict[date, Value])
    warnings: list[str] = field(default_factory=list[str])


def four_quarters(
    end: date, quarters: Mapping[date, Value], gap_days: int = 1
) -> tuple[Value, ...] | None:
    """The 4 contiguous discrete quarters ending at `end`, oldest first, or None. `quarters` is
    keyed by period end (discrete_quarters), so the previous quarter is a lookup, not a scan."""
    q = quarters.get(end)
    if q is None:
        return None
    chain = [q]
    while len(chain) < 4:
        start = chain[0].period.start
        if start is None:
            return None
        prev = quarters.get(start - timedelta(days=gap_days))
        if prev is None or not is_contiguous(prev.period, chain[0].period, gap_days):
            return None
        chain.insert(0, prev)
    return tuple(chain)


def _straddles(start: date, end: date, breaks: Iterable[date]) -> bool:
    """A break `b` is the last day of a fiscal year before a change; windows must not span it."""
    return any(start <= b < end for b in breaks)


def _summed(quarters: tuple[Value, ...]) -> Value:
    latest = max(quarters, key=lambda v: (v.filed, v.source_accn or ""))
    firsts = [q.first_filed_value for q in quarters]
    has_first = all(f is not None for f in firsts)
    start = quarters[0].period.start
    end = quarters[-1].period.end
    return Value(
        item=latest.item,
        period=Period(end=end, start=start),
        value=sum(q.value for q in quarters),
        unit=latest.unit,
        source_tag=None,
        source_accn=latest.source_accn,
        filed=latest.filed,
        first_filed_value=sum(f for f in firsts if f is not None) if has_first else None,
        first_filed_date=(
            max(q.first_filed_date or q.filed for q in quarters) if has_first else None
        ),
        derived=any(q.derived for q in quarters),
        inputs=tuple(f"Σ {q.period.label()}" for q in quarters),
    )


_PARTIAL_YEAR = (DurationClass.QUARTER, DurationClass.HALF_YEAR, DurationClass.NINE_MONTHS)


def _ytd_bridge(
    end: date,
    fiscal_years: Mapping[date, Value],
    ytd: Mapping[Period, Value],
    *,
    bounds: DurationBounds,
    gap_days: int,
    breaks: tuple[date, ...],
    alternatives: Alternatives,
) -> Value | None:
    """FY + year-to-date ending at `end` − prior year-to-date, all three under one lineage (the
    winning tags, or the same tag filed for each). The year-to-date starts the day after the FY
    ends; the prior one has the FY's start and the same duration class; the span it leaves must be
    fiscal-year length and must not straddle a fiscal-year change."""
    for cur in (v for p, v in ytd.items() if p.end == end and p.start is not None):
        cls = classify(cur.period, bounds)
        if cls not in _PARTIAL_YEAR:
            continue
        fy = next(
            (
                f
                for f in fiscal_years.values()
                if next_day(f.period.end, gap_days) == cur.period.start
            ),
            None,
        )
        if fy is None:
            continue
        for p, prior in ytd.items():
            if (
                p.start != fy.period.start
                or p.end >= fy.period.end
                or classify(p, bounds) is not cls
            ):
                continue
            start = next_day(p.end, gap_days)
            span = Period(end=end, start=start)
            if _straddles(start, end, breaks) or (
                classify(span, bounds) is not DurationClass.FISCAL_YEAR
            ):
                continue
            for key in (cur.tag_key, fy.tag_key, prior.tag_key):
                parts = [as_lineage(x, key, alternatives) for x in (fy, cur, prior)]
                if all(x is not None for x in parts):
                    f, c, pr = parts
                    assert f is not None and c is not None and pr is not None
                    return _bridged(f, c, pr, start)
    return None


def _bridged(fy: Value, cur: Value, prior: Value, start: date) -> Value:
    parts = (fy, cur, prior)
    latest = max(parts, key=lambda v: (v.filed, v.source_accn or ""))
    f_fy, f_cur, f_prior = fy.first_filed_value, cur.first_filed_value, prior.first_filed_value
    first = (
        f_fy + f_cur - f_prior
        if f_fy is not None and f_cur is not None and f_prior is not None
        else None
    )
    return Value(
        item=fy.item,
        period=Period(end=cur.period.end, start=start),
        value=fy.value + cur.value - prior.value,
        unit=latest.unit,
        source_tag=None,
        source_accn=latest.source_accn,
        filed=latest.filed,
        first_filed_value=first,
        first_filed_date=(
            max(v.first_filed_date or v.filed for v in parts) if first is not None else None
        ),
        derived=any(v.derived for v in parts),
        lineage=fy.tag_key,
        inputs=(
            f"FY {fy.period.label()}",
            f"+ {cur.period.label()}",
            f"− {prior.period.label()}",
            f"[{fy.tag_key}]",
        ),
    )


def ttm_series(
    fiscal_years: Mapping[date, Value],
    quarters: Mapping[date, Value],
    bounds: DurationBounds,
    *,
    additive: bool = True,
    gap_days: int = 1,
    tolerance: float = 0.005,
    breaks: Iterable[date] = (),
    ytd: Mapping[Period, Value] | None = None,
    alternatives: Alternatives | None = None,
) -> TtmResult:
    """TTM values keyed by period end, oldest first, plus FY consistency warnings. `ytd` is
    every selected duration value of the item, for the FY + YTD − prior YTD fallback."""
    breaks = tuple(breaks)
    ytd = ytd if additive and ytd else {}
    out = TtmResult()
    partial_ends = {p.end for p in ytd if classify(p, bounds) in _PARTIAL_YEAR}
    for end in sorted(set(quarters) | set(fiscal_years) | partial_ends):
        four = four_quarters(end, quarters, gap_days) if additive else None
        if four is not None:
            start = four[0].period.start
            assert start is not None
            span = Period(end=end, start=start)
            if _straddles(start, end, breaks) or (
                classify(span, bounds) is not DurationClass.FISCAL_YEAR
            ):
                four = None
        fy = fiscal_years.get(end)
        if fy is not None:
            out.values[end] = replace(fy, quarter_derived=False)
            if four is not None:
                total = sum(q.value for q in four)
                if abs(total - fy.value) > tolerance * abs(fy.value):
                    out.warnings.append(
                        f"{fy.item}: Σ4q {total:,.0f} ≠ FY {fy.value:,.0f} at {end}"
                    )
        elif four is not None:
            out.values[end] = _summed(four)
        elif (
            bridged := _ytd_bridge(
                end,
                fiscal_years,
                ytd,
                bounds=bounds,
                gap_days=gap_days,
                breaks=breaks,
                alternatives=alternatives or {},
            )
        ) is not None:
            out.values[end] = bridged
    return out
