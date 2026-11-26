"""Fetch grouped-daily dates into the store: a resumable backfill and the daily catch-up.

Resume rule: a date with a usable partition on disk, or recorded as a holiday, is never fetched
again. Each date is written atomically as soon as it arrives, so killing the process loses at
most the date in flight, and the next run carries on from there. "Usable" depends on who is
asking: Massive (whole-market grouped daily) only trusts partitions Massive wrote, so dates a
yfinance fallback filled for a few tickers are fetched again once a key is configured.

Holiday rule: a weekday with no bars is recorded as a holiday only when sessions *on both sides*
of it have bars on disk. An empty answer at the newest end may mean "not published yet"; at the
oldest end it may mean "beyond the plan's history". Neither is a holiday, so neither is recorded.

Stop rule: the backfill gives up walking back after `MAX_EMPTY_RUN` empty weekdays in a row (no
US market closure has been that long since 2001's four days) or after `sessions × 2 + 30`
weekdays in total, and says so. A provider's "older than your plan" refusal
(`HistoryLimitError`) stops it the same way.
"""

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import takewhile

from glint.core.log import get_logger, log_event
from glint.ingest.prices.provider import (
    HistoryLimitError,
    PriceProvider,
    latest_requestable,
)
from glint.ingest.prices.store import PriceStore

MAX_EMPTY_RUN = 5
"""Consecutive empty weekdays after which the backfill decides history has run out."""

log = get_logger(__name__)


@dataclass
class IngestResult:
    fetched: list[date] = field(default_factory=list[date])
    on_disk: int = 0
    holidays: list[date] = field(default_factory=list[date])
    not_yet_available: list[date] = field(default_factory=list[date])
    rows: int = 0
    splits_new: int = 0
    seconds: float = 0.0
    history_exhausted: bool = False

    @property
    def sessions(self) -> int:
        return self.on_disk + len(self.fetched)


def weekdays_back(start: date) -> Iterator[date]:
    """Weekdays from `start` going backwards, `start` included if it is a weekday."""
    day = start
    while True:
        if day.weekday() < 5:
            yield day
        day -= timedelta(days=1)


def eta_minutes(calls: int, seconds_per_call: float) -> float:
    return calls * seconds_per_call / 60


def usable_sources(provider: PriceProvider) -> frozenset[str] | None:
    """Partition sources this provider may skip. None = any partition will do."""
    return frozenset({"massive"}) if provider.name == "massive" else None


class _Fetcher:
    def __init__(self, store: PriceStore, provider: PriceProvider, seconds_per_call: float) -> None:
        self.store = store
        self.provider = provider
        self.seconds_per_call = seconds_per_call
        self.result = IngestResult()
        self.on_disk = set(store.dates_on_disk(sources=usable_sources(provider)))
        self.any_bars = set(store.dates_on_disk())
        self.closed = store.holidays()
        self.empty: list[date] = []

    def fetch(self, day: date, *, todo_left: int) -> bool:
        """Fetch and store one date. True if it produced a session."""
        bars = self.provider.bars_for_date(day)
        if not bars:
            self.empty.append(day)
            log_event(log, "prices_date_empty", date=day.isoformat())
            return False
        rows = self.store.write_day(day, bars, source=self.provider.name)
        self.on_disk.add(day)
        self.any_bars.add(day)
        self.result.fetched.append(day)
        self.result.rows += rows
        log_event(
            log,
            "prices_date_saved",
            date=day.isoformat(),
            rows=rows,
            left=todo_left,
            eta_min=round(eta_minutes(todo_left, self.seconds_per_call), 1),
        )
        return True

    def finish(self) -> None:
        """Confirm holidays (bars on both sides), then merge splits since the oldest date."""
        for day in sorted(self.empty):
            if any(d > day for d in self.any_bars) and any(d < day for d in self.any_bars):
                self.store.add_holiday(day, source=self.provider.name)
                self.result.holidays.append(day)
                log_event(log, "prices_holiday_recorded", date=day.isoformat())
            else:
                self.result.not_yet_available.append(day)
        if self.result.not_yet_available:
            log_event(
                log,
                "prices_empty_unconfirmed",
                dates=",".join(d.isoformat() for d in self.result.not_yet_available),
            )
        # Splits only need refreshing when new bars arrived; a run with nothing to fetch makes
        # no calls at all (for yfinance, a splits call is a full-universe history download).
        dates = sorted(self.any_bars)
        if dates and self.result.fetched:
            self.result.splits_new = self.store.merge_splits(self.provider.splits(dates[0]))
            log_event(
                log, "prices_splits_merged", since=dates[0].isoformat(), new=self.result.splits_new
            )


def backfill(
    store: PriceStore,
    provider: PriceProvider,
    sessions: int,
    *,
    seconds_per_call: float = 0.0,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> IngestResult:
    """Make sure the newest `sessions` trading days up to yesterday (New York) are on disk."""
    started = clock()
    with store.writer():
        f = _Fetcher(store, provider, seconds_per_call)
        newest = latest_requestable(now)
        window: list[date] = []
        for day in weekdays_back(newest):
            if len(window) >= sessions:
                break
            if day not in f.closed:
                window.append(day)
        todo = [d for d in window if d not in f.on_disk]
        f.result.on_disk = len(window) - len(todo)
        log_event(
            log,
            "prices_backfill_plan",
            sessions=sessions,
            newest=newest.isoformat(),
            on_disk=f.result.on_disk,
            to_fetch=len(todo),
            eta_min=round(eta_minutes(len(todo), seconds_per_call), 1),
        )
        provider.prefetch(todo)
        have = f.result.on_disk
        empty_run = 0
        max_walk = sessions * 2 + 30
        for walked, day in enumerate(weekdays_back(newest)):
            if have >= sessions:
                break
            if walked >= max_walk or empty_run >= MAX_EMPTY_RUN:
                f.result.history_exhausted = True
                log_event(
                    log, "prices_history_exhausted", oldest_tried=day.isoformat(), sessions=have
                )
                break
            if day in f.closed:
                continue
            if day in f.on_disk:
                empty_run = 0
                if day not in window:  # pulled in to replace a holiday found on the way
                    f.result.on_disk += 1
                    have += 1
                continue
            try:
                got = f.fetch(day, todo_left=max(sessions - have - 1, 0))
            except HistoryLimitError as exc:
                f.result.history_exhausted = True
                log_event(log, "prices_history_limit", date=day.isoformat(), error=exc.message)
                break
            if got:
                have += 1
                empty_run = 0
            else:
                empty_run += 1
        f.finish()
    f.result.seconds = clock() - started
    _log_done("prices_backfill_done", f.result)
    return f.result


def ingest_dates(
    store: PriceStore,
    provider: PriceProvider,
    days: list[date] | None = None,
    *,
    seconds_per_call: float = 0.0,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> IngestResult:
    """Fetch the given dates, or (by default) every weekday after the newest one on disk."""
    started = clock()
    with store.writer():
        f = _Fetcher(store, provider, seconds_per_call)
        newest = latest_requestable(now)
        if days is None:
            last = max(f.on_disk) if f.on_disk else newest - timedelta(days=1)
            days = list(takewhile(lambda d: d > last, weekdays_back(newest)))[::-1]
        weekend = [d for d in days if d.weekday() >= 5]
        if weekend:
            log_event(log, "prices_weekend_skipped", dates=",".join(map(str, weekend)))
        days = [d for d in days if d.weekday() < 5]
        todo = sorted((d for d in days if d not in f.on_disk and d not in f.closed), reverse=True)
        f.result.on_disk = sum(d in f.on_disk for d in days)
        provider.prefetch(todo)
        for i, day in enumerate(todo):
            f.fetch(day, todo_left=len(todo) - i - 1)
        f.finish()
    f.result.seconds = clock() - started
    _log_done("prices_ingest_done", f.result)
    return f.result


def _log_done(event: str, r: IngestResult) -> None:
    log_event(
        log,
        event,
        fetched=len(r.fetched),
        on_disk=r.on_disk,
        holidays=len(r.holidays),
        not_yet=len(r.not_yet_available),
        rows=r.rows,
        splits_new=r.splits_new,
        history_exhausted=r.history_exhausted,
        seconds=round(r.seconds, 1),
    )
