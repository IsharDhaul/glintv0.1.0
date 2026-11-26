"""MassiveProvider against real recorded responses (trimmed to Appendix D + ZOOZ + SPY).

Recorded 2026-10-29 from api.massive.com: grouped daily (unadjusted) for 2026-05-29,
2026-06-01 and 2026-10-28, and the splits page holding ZOOZ's 1-for-20 reverse split
effective 2026-06-01.
"""

from datetime import date
from pathlib import Path

import httpx
import polars as pl
import pytest

from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.prices.backfill import backfill
from glint.ingest.prices.massive import MassiveProvider
from glint.ingest.prices.provider import HistoryLimitError
from glint.ingest.prices.splits import adjust_for_splits
from glint.ingest.prices.store import PriceStore
from tests.prices.helpers import FakeClock, fixed_now

FIXTURES = Path(__file__).parent / "fixtures" / "massive"
GROUPED = "/v2/aggs/grouped/locale/us/market/stocks/"
APPENDIX_D = {
    "AAPL", "MSFT", "NVDA", "KO", "MU", "KHC", "RIVN", "SBUX", "XOM", "F", "JPM", "O",
    "BRK.A", "BRK.B", "GOOGL", "GOOG", "TSM", "ASML",
}  # fmt: skip
PAST_PLAN = (
    b'{"status":"NOT_AUTHORIZED","request_id":"recorded","message":"Attempted to request data '
    b'past historical entitlements. Please upgrade your plan at https://polygon.io/pricing"}'
)


def _recorded(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith(GROUPED):
        f = FIXTURES / f"grouped_{path.removeprefix(GROUPED)}.json"
        if f.exists():
            return httpx.Response(200, content=f.read_bytes())
        return httpx.Response(403, content=PAST_PLAN)
    if path == "/stocks/v1/splits":
        return httpx.Response(200, content=(FIXTURES / "splits_zooz.json").read_bytes())
    return httpx.Response(404)


def _provider(today: date) -> MassiveProvider:
    clock = FakeClock()
    return MassiveProvider(
        "k",
        base_url="https://api.massive.com",
        transport=httpx.MockTransport(_recorded),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: fixed_now(today),
    )


def test_recorded_grouped_daily_parses() -> None:
    bars = {b.ticker: b for b in _provider(date(2026, 10, 29)).bars_for_date(date(2026, 10, 28))}
    assert set(bars) >= APPENDIX_D  # Massive symbols are canonical for classes: BRK.B
    assert all(b.date == date(2026, 10, 28) for b in bars.values())
    assert all(b.volume is not None and b.vwap is not None for b in bars.values())
    assert bars["BRK.A"].close > 100 * bars["BRK.B"].close  # two classes, very different prices


def test_recorded_split() -> None:
    (split,) = _provider(date(2026, 10, 29)).splits(date(2026, 6, 1))
    assert (split.ticker, split.execution_date, split.ratio) == ("ZOOZ", date(2026, 6, 1), 0.05)
    assert split.adjustment_type == "reverse_split"


def test_recorded_reverse_split_adjusts_to_a_flat_return(settings: Settings) -> None:
    p = _provider(date(2026, 6, 2))
    store = PriceStore(Paths.from_settings(settings))
    with store.writer():
        for d in (date(2026, 5, 29), date(2026, 6, 1)):
            store.write_day(d, p.bars_for_date(d), source="massive")
        store.merge_splits(p.splits(date(2026, 5, 29)))
    adj = adjust_for_splits(
        store.read_bars(tickers=["ZOOZ"]), store.load_splits(), date(2026, 6, 1)
    )
    raw = adj["close"].to_list()
    assert raw == [0.304, 6.08]  # as traded: before and after the 1-for-20
    assert adj["adj_close"].to_list() == pytest.approx([6.08, 6.08], abs=1e-9)
    assert adj.filter(pl.col("date") == date(2026, 5, 29))["split_factor"][0] == 0.05


def test_plan_history_limit_is_a_history_limit_error() -> None:
    with pytest.raises(HistoryLimitError, match="historical entitlements"):
        _provider(date(2026, 10, 29)).bars_for_date(date(2024, 10, 28))


def test_backfill_stops_cleanly_at_the_plan_limit(settings: Settings) -> None:
    # Only 2026-10-28 is "inside the plan" here; everything older answers 403 like the real API.
    store = PriceStore(Paths.from_settings(settings))
    r = backfill(store, _provider(date(2026, 10, 29)), 5, now=fixed_now(date(2026, 10, 29)))
    assert r.history_exhausted
    assert r.fetched == [date(2026, 10, 28)]
    assert store.holidays() == set()
