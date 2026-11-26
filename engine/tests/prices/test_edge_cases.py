"""Edge cases from the WT-02 review: partial partitions, endless walks, fills, odd headers."""

from datetime import date, timedelta
from typing import Any

import httpx
import orjson
import polars as pl
import pytest

from glint.core.errors import SourceError
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.prices.backfill import MAX_EMPTY_RUN, backfill, ingest_dates
from glint.ingest.prices.massive import MassiveProvider
from glint.ingest.prices.models import Bar, Split
from glint.ingest.prices.splits import adjust_for_splits
from glint.ingest.prices.stats import Windows, price_stats
from glint.ingest.prices.store import PriceStore, bars_frame, splits_frame
from glint.ingest.prices.yfinance_provider import YFinanceProvider, unadjust
from tests.prices.helpers import FakeClock, FakeProvider, bar, fixed_now
from tests.prices.test_backfill import NOW, WEEKDAYS

TOL = 1e-9


@pytest.fixture
def store(settings: Settings) -> PriceStore:
    return PriceStore(Paths.from_settings(settings))


# --- partitions written by the fallback don't satisfy Massive -----------------------------


def test_massive_refetches_dates_the_fallback_wrote(store: PriceStore) -> None:
    yf = FakeProvider()
    yf.name = "yfinance"
    backfill(store, yf, 3, now=NOW)
    assert store.partition_source(WEEKDAYS[0]) == "yfinance"

    massive = FakeProvider()
    massive.name = "massive"
    r = backfill(store, massive, 3, now=NOW)
    assert massive.calls == WEEKDAYS[:3]  # partial fallback dates fetched again
    assert r.on_disk == 0
    assert store.partition_source(WEEKDAYS[0]) == "massive"

    yf_again = FakeProvider()
    yf_again.name = "yfinance"
    backfill(store, yf_again, 3, now=NOW)
    assert yf_again.calls == []  # the fallback happily reuses Massive's dates


def test_partition_without_sidecar_is_refetched_by_massive(store: PriceStore) -> None:
    with store.writer():
        store.write_day(WEEKDAYS[0], [bar("AAPL", WEEKDAYS[0], 1.0)], source="massive")
    store.source_path(WEEKDAYS[0]).unlink()  # as if killed between bars and sidecar
    assert store.dates_on_disk() == [WEEKDAYS[0]]
    assert store.dates_on_disk(sources={"massive"}) == []


# --- holidays need bars on both sides; the walk stops ------------------------------------


def test_walk_stops_when_history_runs_out(store: PriceStore) -> None:
    p = FakeProvider(closed=WEEKDAYS[3:] + [WEEKDAYS[-1] - timedelta(days=i) for i in range(60)])
    r = backfill(store, p, 10, now=NOW)
    assert r.history_exhausted
    assert len(r.fetched) == 3
    assert len(p.calls) == 3 + MAX_EMPTY_RUN
    assert store.holidays() == set()  # nothing older has bars: not a holiday, not recorded
    assert len(r.not_yet_available) == MAX_EMPTY_RUN


def test_one_sided_empty_day_is_not_stamped(store: PriceStore) -> None:
    # newest two empty (unpublished?), and nothing on disk newer → not holidays
    p = FakeProvider(closed=WEEKDAYS[:2])
    r = backfill(store, p, 2, now=NOW)
    assert store.holidays() == set()
    assert r.not_yet_available == sorted(WEEKDAYS[:2])


def test_weekend_date_is_skipped_not_recorded(store: PriceStore) -> None:
    saturday = date(2026, 10, 24)
    p = FakeProvider()
    r = ingest_dates(store, p, [saturday], now=NOW)
    assert p.calls == []
    assert store.holidays() == set()
    assert r.fetched == []


def test_daily_catch_up_confirms_a_holiday_between_sessions(store: PriceStore) -> None:
    backfill(store, FakeProvider(), 1, now=fixed_now(date(2026, 10, 22)))  # Wed 21 Oct on disk
    p = FakeProvider(closed=[date(2026, 10, 22)])  # Thu closed, Fri open
    r = ingest_dates(store, p, now=fixed_now(date(2026, 10, 24)))
    assert r.holidays == [date(2026, 10, 22)]
    assert r.fetched == [date(2026, 10, 23)]


# --- no silent fills --------------------------------------------------------------------------


def test_massive_missing_fields_stay_null() -> None:
    row = {"T": "X", "c": 10.0, "t": 0}
    doc = {"status": "OK", "adjusted": False, "results": [row]}
    p = MassiveProvider(
        "k",
        base_url="https://api.massive.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=orjson.dumps(doc))),
        now=lambda: fixed_now(date(2026, 10, 28)),
    )
    (b,) = p.bars_for_date(date(2026, 10, 27))
    assert (b.open, b.high, b.low, b.volume, b.vwap) == (None, None, None, None, None)
    assert b.close == 10.0


def test_yfinance_missing_volume_stays_null() -> None:
    rows: list[tuple[date, dict[str, float | None]]] = [
        (date(2024, 6, 6), {"Close": 10.0, "Volume": None, "Open": None, "Stock Splits": 0.0}),
        (date(2024, 6, 7), {"Close": 11.0, "Volume": 0.0, "Open": 10.5, "Stock Splits": 0.0}),
    ]
    bars, _ = unadjust(rows)
    assert (bars[0].volume, bars[0].open) == (None, None)
    assert bars[1].volume == 0.0  # a real zero stays a zero


def test_adv_is_null_with_a_reason_when_volume_is_missing() -> None:
    d0 = date(2026, 1, 5)
    bars = bars_frame(
        [
            Bar("X", d0, None, None, None, 10.0, 100.0),
            Bar("X", d0 + timedelta(days=1), None, None, None, 11.0, None),
            Bar("Y", d0, None, None, None, 10.0, 0.0),
            Bar("Y", d0 + timedelta(days=1), None, None, None, 11.0, 0.0),
        ]
    )
    as_of = d0 + timedelta(days=1)
    w = Windows(m1=1, m3=1, m6=1, m12=1, high=1, vol=1, adv=2)
    out = price_stats(adjust_for_splits(bars, splits_frame([]), as_of), as_of, w)
    adv = dict(out.stats.select("ticker", "avg_dollar_volume_3m").rows())
    assert adv == {"X": None, "Y": 0.0}  # a real zero volume is not missing
    note = out.notes.filter(pl.col("stat") == "avg_dollar_volume_3m").row(0, named=True)
    assert (note["ticker"], note["code"]) == ("X", "MISSING_INPUT")
    assert note["message"] == "avg_dollar_volume_3m: volume missing on 1 of the last 2 sessions"


# --- splits ------------------------------------------------------------------------------------


def test_reverse_and_double_splits() -> None:
    d0 = date(2024, 1, 1)
    days = [d0 + timedelta(days=i) for i in range(4)]
    bars = bars_frame(
        [bar("R", d, c) for d, c in zip(days, [1.0, 1.0, 10.0, 10.0], strict=True)]
        + [bar("D", d, c) for d, c in zip(days, [800.0, 400.0, 200.0, 200.0], strict=True)]
    )
    splits = splits_frame(
        [
            Split("R", days[2], 10, 1),  # 1-for-10 reverse
            Split("D", days[1], 1, 2),
            Split("D", days[2], 1, 2),
        ]
    )
    adj = adjust_for_splits(bars, splits, days[-1])
    r = adj.filter(pl.col("ticker") == "R")
    assert r["adj_close"].to_list() == pytest.approx([10.0, 10.0, 10.0, 10.0], abs=TOL)
    assert r["adj_volume"].to_list() == pytest.approx([100.0, 100.0, 1000.0, 1000.0], abs=TOL)
    d = adj.filter(pl.col("ticker") == "D")
    assert d["adj_close"].to_list() == pytest.approx([200.0, 200.0, 200.0, 200.0], abs=TOL)
    assert d["split_factor"].to_list() == [4.0, 2.0, 1.0, 1.0]


def test_yfinance_reverse_split_unadjust() -> None:
    rows: list[tuple[date, dict[str, float | None]]] = [
        (date(2024, 3, 1), {"Close": 10.0, "Volume": 100.0, "Stock Splits": 0.0}),
        (date(2024, 3, 4), {"Close": 10.5, "Volume": 10.0, "Stock Splits": 0.1}),
    ]
    bars, splits = unadjust(rows)
    assert bars[0].close == pytest.approx(1.0, abs=TOL)  # traded at $1 before the 1-for-10
    assert bars[0].volume == pytest.approx(1000.0, abs=TOL)
    assert splits[0].ratio == pytest.approx(0.1)


# --- yfinance doesn't re-download the universe ------------------------------------------


def test_yfinance_backfill_past_a_holiday_downloads_once(store: PriceStore) -> None:
    import pandas as pd  # noqa: PLC0415

    days = [d for d in WEEKDAYS[::-1] if d != WEEKDAYS[2]]  # one closed weekday
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
    frame = pd.DataFrame(
        [[1.0, 1.0, 1.0, 1.0, 1.0, 100.0, 0.0, 0.0] for _ in days],
        index=pd.DatetimeIndex([pd.Timestamp(d) for d in days]),
        columns=pd.MultiIndex.from_product([["AAPL"], fields]),
    )
    calls: list[Any] = []

    def download(symbols: list[str], start: date, end: date) -> Any:
        calls.append(start)
        return frame

    p = YFinanceProvider(["AAPL"], download=download, now=lambda: NOW)
    r = backfill(store, p, 6, now=NOW)
    assert r.holidays == [WEEKDAYS[2]]
    assert len(r.fetched) == 6
    assert len(calls) == 1  # prefetch slack covers the extra day; splits reuse the window


# --- Massive headers ----------------------------------------------------------------------------


def test_retry_after_http_date_falls_back_to_a_minute() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "Wed, 28 Oct 2026 07:28:00 GMT"}),
            httpx.Response(200, content=orjson.dumps({"status": "OK", "results": []})),
        ]
    )
    clock = FakeClock()
    p = MassiveProvider(
        "k",
        base_url="https://api.massive.test",
        transport=httpx.MockTransport(lambda r: next(responses)),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: fixed_now(date(2026, 10, 28)),
    )
    assert p.bars_for_date(date(2026, 10, 27)) == []
    assert clock.t == pytest.approx(60)


def test_repeated_429_gives_up() -> None:
    clock = FakeClock()
    p = MassiveProvider(
        "k",
        base_url="https://api.massive.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "5"})),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: fixed_now(date(2026, 10, 28)),
    )
    with pytest.raises(SourceError, match=r"gave up.*429"):
        p.bars_for_date(date(2026, 10, 27))


def test_error_status_in_a_200_is_not_an_empty_day() -> None:
    doc = {"status": "ERROR", "error": "something"}
    p = MassiveProvider(
        "k",
        base_url="https://api.massive.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=orjson.dumps(doc))),
        now=lambda: fixed_now(date(2026, 10, 28)),
    )
    with pytest.raises(SourceError, match="status 'ERROR'"):
        p.bars_for_date(date(2026, 10, 27))
