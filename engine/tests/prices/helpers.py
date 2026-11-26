"""Test doubles shared by the price tests."""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from glint.core.errors import SourceError
from glint.ingest.prices.models import Bar, Split


class FakeClock:
    """A monotonic clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def fixed_now(day: date, hour: int = 15) -> datetime:
    """A UTC instant that falls on `day` in New York."""
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)


def bar(ticker: str, day: date, close: float, volume: float = 1000.0) -> Bar:
    return Bar(ticker, day, close, close, close, close, volume, close)


class FakeProvider:
    name = "fake"
    is_fallback = False

    def __init__(
        self,
        closed: Sequence[date] = (),
        fail_after: int | None = None,
        splits: Sequence[Split] = (),
    ) -> None:
        self.closed = set(closed)
        self.fail_after = fail_after
        self._splits = list(splits)
        self.calls: list[date] = []
        self.prefetched: list[date] = []
        self.splits_since: list[date] = []

    def bars_for_date(self, day: date) -> list[Bar]:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise SourceError("fake", "killed")
        self.calls.append(day)
        if day in self.closed:
            return []
        return [bar("AAPL", day, 100.0 + day.day), bar("MSFT", day, 400.0)]

    def history(self, ticker: str, start: date, end: date) -> list[Bar]:
        return []

    def splits(self, since: date) -> list[Split]:
        self.splits_since.append(since)
        return [s for s in self._splits if s.execution_date >= since]

    def prefetch(self, days: Sequence[date]) -> None:
        self.prefetched = list(days)
