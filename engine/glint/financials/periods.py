"""The period engine (§4.3 rules 1–2). Pure: periods are `(start, end)` dates, never `fy`/`fp`."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from typing import NamedTuple

from glint.financials.concepts import DurationBounds, DurationClass
from glint.financials.facts import Fact


class Period(NamedTuple):
    """A duration `[start, end]` or, with `start=None`, an instant at `end`.

    A NamedTuple (ordered, hashed and compared as `(end, start)`, like the frozen dataclass it
    replaced): periods are dict keys everywhere, and a tuple hashes in C (WT-03.md, 2026-11-23).
    """

    end: date
    start: date | None = None

    @property
    def is_instant(self) -> bool:
        return self.start is None

    @property
    def days(self) -> int:
        return 0 if self.start is None else (self.end - self.start).days

    def label(self) -> str:
        return str(self.end) if self.start is None else f"{self.start}..{self.end}"


def period_of(fact: Fact) -> Period:
    return Period(end=fact.end, start=fact.start)


def classify(period: Period, bounds: DurationBounds) -> DurationClass | None:
    """None for an instant; otherwise the duration class by length in days."""
    if period.start is None:
        return None
    return bounds.classify(period.days)


def by_period[F: Fact](facts: Iterable[F]) -> dict[Period, list[F]]:
    """Group facts by `(start, end)`. The same period from many filings lands in one bucket."""
    out: dict[Period, list[F]] = defaultdict(list)
    for f in facts:
        out[period_of(f)].append(f)
    return dict(out)


def next_day(d: date, gap_days: int = 1) -> date:
    return d + timedelta(days=gap_days)


def is_contiguous(prev: Period, nxt: Period, gap_days: int = 1) -> bool:
    """`nxt` starts exactly `gap_days` after `prev` ends."""
    return nxt.start is not None and nxt.start == next_day(prev.end, gap_days)
