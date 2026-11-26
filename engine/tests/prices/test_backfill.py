import logging
from datetime import date

import pytest

from glint.core.errors import SourceError
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.prices.backfill import backfill, eta_minutes, ingest_dates, weekdays_back
from glint.ingest.prices.models import Split
from glint.ingest.prices.store import PriceStore
from tests.prices.helpers import FakeProvider, fixed_now

NOW = fixed_now(date(2026, 10, 29))  # Thursday → newest requestable is Wed 28 Oct
# The 8 weekdays up to Wed 28 Oct 2026, newest first.
WEEKDAYS = [
    date(2026, 10, 28),
    date(2026, 10, 27),
    date(2026, 10, 26),
    date(2026, 10, 23),
    date(2026, 10, 22),
    date(2026, 10, 21),
    date(2026, 10, 20),
    date(2026, 10, 19),
]


@pytest.fixture
def store(settings: Settings) -> PriceStore:
    return PriceStore(Paths.from_settings(settings))


def test_weekdays_back_skips_weekends() -> None:
    it = weekdays_back(date(2026, 10, 26))  # Monday
    assert [next(it) for _ in range(3)] == [
        date(2026, 10, 26),
        date(2026, 10, 23),
        date(2026, 10, 22),
    ]


def test_eta_matches_the_plan_arithmetic() -> None:
    # 252 sessions at 5 calls a minute is about 51 minutes (SPEC §4.1)
    assert eta_minutes(252, 60 / 5) == pytest.approx(50.4)


def test_backfill_from_empty(store: PriceStore) -> None:
    p = FakeProvider()
    r = backfill(store, p, 5, now=NOW)
    assert p.calls == WEEKDAYS[:5]
    assert store.dates_on_disk() == sorted(WEEKDAYS[:5])
    assert (r.sessions, r.rows, r.on_disk) == (5, 10, 0)


def test_backfill_resumes_after_kill_without_refetching(
    store: PriceStore, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SourceError, match="killed"):
        backfill(store, FakeProvider(fail_after=2), 5, now=NOW)
    assert store.dates_on_disk() == sorted(WEEKDAYS[:2])  # what arrived before the kill is kept

    monkeypatch.setattr(logging.getLogger("glint"), "propagate", True)
    p = FakeProvider()
    with caplog.at_level(logging.INFO, logger="glint"):
        r = backfill(store, p, 5, now=NOW)
    assert p.calls == WEEKDAYS[2:5]  # saved dates are never asked for again
    assert p.prefetched == WEEKDAYS[2:5]
    assert (r.on_disk, len(r.fetched)) == (2, 3)
    plan = next(rec for rec in caplog.records if rec.getMessage() == "prices_backfill_plan")
    assert (plan.on_disk, plan.to_fetch) == (2, 3)  # type: ignore[attr-defined]

    again = FakeProvider()
    r = backfill(store, again, 5, now=NOW)
    assert again.calls == []
    assert r.on_disk == 5


def test_holiday_recorded_and_window_extended(store: PriceStore) -> None:
    holiday = WEEKDAYS[2]
    p = FakeProvider(closed=[holiday])
    r = backfill(store, p, 5, now=NOW)
    assert r.holidays == [holiday]
    assert store.holidays() == {holiday}
    assert store.dates_on_disk() == sorted([d for d in WEEKDAYS[:6] if d != holiday])

    # next run: the holiday is never asked for again
    p2 = FakeProvider()
    backfill(store, p2, 6, now=NOW)
    assert holiday not in p2.calls
    assert p2.calls == [WEEKDAYS[6]]


def test_newest_empty_date_is_not_a_holiday(store: PriceStore) -> None:
    p = FakeProvider(closed=[WEEKDAYS[0]])  # e.g. not published yet
    r = backfill(store, p, 3, now=NOW)
    assert r.not_yet_available == [WEEKDAYS[0]]
    assert store.holidays() == set()
    assert store.dates_on_disk() == sorted(WEEKDAYS[1:4])


def test_splits_merged_since_oldest_date(store: PriceStore) -> None:
    s = Split("NVDA", date(2026, 10, 22), 1, 10)
    p = FakeProvider(splits=[s, Split("OLD", date(2020, 1, 2), 1, 2)])
    r = backfill(store, p, 5, now=NOW)
    assert p.splits_since == [WEEKDAYS[4]]
    assert r.splits_new == 1
    assert store.load_splits()["ticker"].to_list() == ["NVDA"]


def test_ingest_catches_up_after_newest_on_disk(store: PriceStore) -> None:
    backfill(store, FakeProvider(), 2, now=fixed_now(date(2026, 10, 23)))  # 21, 22 Oct
    p = FakeProvider()
    r = ingest_dates(store, p, now=NOW)
    assert p.calls == [WEEKDAYS[0], WEEKDAYS[1], WEEKDAYS[2], WEEKDAYS[3]]
    assert len(r.fetched) == 4


def test_nothing_to_fetch_makes_no_calls(store: PriceStore) -> None:
    backfill(store, FakeProvider(), 3, now=NOW)
    p = FakeProvider()
    backfill(store, p, 3, now=NOW)
    ingest_dates(store, p, [WEEKDAYS[0]], now=NOW)
    assert p.calls == []
    assert p.splits_since == []  # no splits refresh either


def test_ingest_explicit_date_skips_saved(store: PriceStore) -> None:
    ingest_dates(store, FakeProvider(), [WEEKDAYS[3]], now=NOW)
    p = FakeProvider()
    r = ingest_dates(store, p, [WEEKDAYS[3], WEEKDAYS[4]], now=NOW)
    assert p.calls == [WEEKDAYS[4]]
    assert r.on_disk == 1
