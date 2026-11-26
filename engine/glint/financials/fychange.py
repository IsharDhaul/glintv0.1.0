"""Fiscal-year-end changes (§4.3 rule 14). Pure.

Two signals, both from dates and forms (never `fy`/`fp`):
- a transition report (10-KT) whose own period isn't a fiscal year;
- consecutive fiscal years whose end dates shift on the calendar by more than `max_shift_days`
  (52/53-week years drift by up to a week).

Each change yields breaks: the last day of the old fiscal year and the last day of the transition
period. No TTM window may span a break.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from glint.financials.concepts import DurationBounds, DurationClass
from glint.financials.facts import Fact
from glint.financials.periods import Period, classify

TRANSITION_FORMS = ("10-KT", "10-KT/A")


@dataclass(frozen=True, slots=True)
class FiscalYearChange:
    old_year_end: date
    transition: Period  # from the day after the old year end to the start of the new regime

    @property
    def breaks(self) -> tuple[date, ...]:
        return (self.old_year_end, self.transition.end)


def calendar_shift(a: date, b: date) -> int:
    """Days between two dates' positions in the calendar year (Dec 31 vs Jan 2 → 2)."""
    diff = abs(a.timetuple().tm_yday - b.timetuple().tm_yday)
    return min(diff, 365 - diff)


def detect_changes(
    facts: Iterable[Fact],
    fiscal_year_periods: Iterable[Period],
    bounds: DurationBounds,
    max_shift_days: int,
) -> list[FiscalYearChange]:
    changes: dict[date, FiscalYearChange] = {}

    # Signal 1: a 10-KT's own (latest-ending) duration that isn't a full year.
    by_accn: dict[str, list[Period]] = defaultdict(list)
    for f in facts:
        if f.form in TRANSITION_FORMS and f.start is not None:
            by_accn[f.accn].append(Period(end=f.end, start=f.start))
    for periods in by_accn.values():
        own_end = max(p.end for p in periods)
        own = [p for p in periods if p.end == own_end]
        for p in own:
            if p.start is not None and classify(p, bounds) is not DurationClass.FISCAL_YEAR:
                old_end = p.start - timedelta(days=1)
                changes[p.end] = FiscalYearChange(old_end, p)
                break

    # Signal 2: consecutive fiscal years that end at different points in the calendar.
    years = sorted({p for p in fiscal_year_periods if p.start is not None}, key=lambda p: p.end)
    for prev, nxt in pairwise(years):
        if calendar_shift(prev.end, nxt.end) > max_shift_days and nxt.start is not None:
            transition_end = nxt.start - timedelta(days=1)
            if transition_end > prev.end and transition_end not in changes:
                changes[transition_end] = FiscalYearChange(
                    prev.end, Period(end=transition_end, start=prev.end + timedelta(days=1))
                )
    return [changes[k] for k in sorted(changes)]
