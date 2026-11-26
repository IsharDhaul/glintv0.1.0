from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest

from glint.core.cache import JsonCache
from glint.core.errors import SourceError
from glint.ingest.prices.massive import MassiveProvider
from tests.prices.helpers import FakeClock, fixed_now

TODAY = date(2026, 10, 28)  # a Wednesday
GROUPED = "/v2/aggs/grouped/locale/us/market/stocks/"

Handler = Callable[[httpx.Request], httpx.Response]


def _json(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, content=orjson.dumps(body), headers=headers)


def _grouped(results: list[dict[str, Any]] | None) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "adjusted": False,
        "queryCount": len(results or []),
        "resultsCount": len(results or []),
        "status": "OK",
        "request_id": "x",
    }
    if results is not None:
        doc["results"] = results
    return doc


def _row(sym: str, c: float, **kw: Any) -> dict[str, Any]:
    return {"T": sym, "o": c, "h": c, "l": c, "c": c, "v": 100.0, "vw": c, "t": 0, "n": 1} | kw


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def _provider(
    handler: Handler, clock: FakeClock | None = None, cache: JsonCache | None = None
) -> tuple[MassiveProvider, Recorder, FakeClock]:
    clock = clock or FakeClock()
    rec = Recorder(handler)
    provider = MassiveProvider(
        "test-key",
        base_url="https://api.massive.test",
        calls_per_min=5,
        cache=cache,
        transport=httpx.MockTransport(rec),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: fixed_now(TODAY),
    )
    return provider, rec, clock


def test_grouped_daily_request_and_parse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(_grouped([_row("MSFT", 410.5), _row("BRK.B", 455.0, vw=None)]))

    p, rec, _ = _provider(handler)
    bars = p.bars_for_date(date(2026, 10, 27))
    req = rec.requests[0]
    assert req.url.path == GROUPED + "2026-10-27"
    assert req.url.params["adjusted"] == "false"
    assert req.headers["Authorization"] == "Bearer test-key"
    assert "apiKey" not in str(req.url)  # keys stay out of URLs (and logs)
    assert [b.ticker for b in bars] == ["BRK.B", "MSFT"]
    assert bars[1].close == 410.5
    assert bars[0].vwap is None


def test_empty_weekday_is_an_empty_list() -> None:
    p, _, _ = _provider(lambda r: _json(_grouped(None)))
    assert p.bars_for_date(date(2026, 1, 1)) == []


def test_weekend_needs_no_call() -> None:
    p, rec, _ = _provider(lambda r: _json(_grouped([])))
    assert p.bars_for_date(date(2026, 10, 25)) == []
    assert rec.requests == []


@pytest.mark.parametrize("day", [TODAY, TODAY + timedelta(days=1)])
def test_never_requests_today_or_later(day: date) -> None:
    p, rec, _ = _provider(lambda r: _json(_grouped([])))
    with pytest.raises(SourceError, match="end-of-day data only"):
        p.bars_for_date(day)
    assert rec.requests == []


def test_rejects_adjusted_response() -> None:
    p, _, _ = _provider(lambda r: _json(_grouped([_row("A", 1)]) | {"adjusted": True}))
    with pytest.raises(SourceError, match="unadjusted"):
        p.bars_for_date(date(2026, 10, 27))


def test_paces_to_five_calls_per_minute() -> None:
    p, rec, clock = _provider(lambda r: _json(_grouped([_row("A", 1)])))
    days = [date(2026, 10, 19) + timedelta(days=i) for i in range(7)]
    weekdays = [d for d in days if d.weekday() < 5]  # 5 weekdays
    for d in [*weekdays, date(2026, 10, 26), date(2026, 10, 27)]:
        p.bars_for_date(d)
    assert len(rec.requests) == 7
    assert clock.t == 60  # calls 6 and 7 waited for the first minute to roll over


def test_429_waits_retry_after_then_succeeds() -> None:
    responses = iter(
        [
            _json({"status": "ERROR", "error": "too many"}, 429, {"Retry-After": "30"}),
            _json(_grouped([_row("A", 1)])),
        ]
    )
    p, rec, clock = _provider(lambda r: next(responses))
    assert len(p.bars_for_date(date(2026, 10, 27))) == 1
    assert len(rec.requests) == 2
    assert clock.t == pytest.approx(30)


def test_5xx_backs_off_then_gives_up() -> None:
    p, rec, clock = _provider(lambda r: _json({"status": "ERROR"}, 502))
    with pytest.raises(SourceError, match="gave up"):
        p.bars_for_date(date(2026, 10, 27))
    assert len(rec.requests) == 5
    assert clock.sleeps[:4] == [2, 4, 8, 16]


def test_network_error_retries() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return _json(_grouped([_row("A", 1)]))

    p, _, _ = _provider(handler)
    assert len(p.bars_for_date(date(2026, 10, 27))) == 1


def test_403_fails_at_once_with_hint() -> None:
    p, rec, _ = _provider(lambda r: _json({"status": "NOT_AUTHORIZED", "message": "plan"}, 403))
    with pytest.raises(SourceError, match="check MASSIVE_API_KEY") as err:
        p.bars_for_date(date(2026, 10, 27))
    assert err.value.status == 403
    assert len(rec.requests) == 1


def test_empty_key_refused() -> None:
    with pytest.raises(SourceError, match="MASSIVE_API_KEY"):
        MassiveProvider("")


def test_splits_follow_next_url_and_sort() -> None:
    page1 = {
        "status": "OK",
        "results": [
            {
                "ticker": "NVDA",
                "execution_date": "2024-06-10",
                "split_from": 1,
                "split_to": 10,
                "adjustment_type": "forward_split",
            }
        ],
        "next_url": "https://api.massive.test/stocks/v1/splits?cursor=abc",
    }
    page2 = {
        "status": "OK",
        "results": [
            {
                "ticker": "XYZ",
                "execution_date": "2024-03-01",
                "split_from": 10,
                "split_to": 1,
                "adjustment_type": "reverse_split",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _json(page2 if "cursor" in str(request.url) else page1)

    p, rec, _ = _provider(handler)
    splits = p.splits(date(2024, 1, 1))
    assert rec.requests[0].url.params["execution_date.gte"] == "2024-01-01"
    assert rec.requests[1].headers["Authorization"] == "Bearer test-key"
    assert [(s.ticker, s.ratio) for s in splits] == [("XYZ", 0.1), ("NVDA", 10)]


def test_next_url_on_other_host_refused() -> None:
    p, _, _ = _provider(lambda r: _json({"results": [], "next_url": "https://evil.test/x"}))
    with pytest.raises(SourceError, match="another host"):
        p.splits(date(2024, 1, 1))


def test_history_clamps_to_yesterday_and_caches(tmp_path: Path) -> None:
    # 2026-10-26 and 10-27, stamped at 04:00 UTC (= midnight New York, EDT)
    rows = [_row("AAPL", 260.0, t=1_792_987_200_000), _row("AAPL", 262.0, t=1_793_073_600_000)]

    p, rec, _ = _provider(
        lambda r: _json({"status": "OK", "results": rows}), cache=JsonCache(tmp_path)
    )
    bars = p.history("AAPL", date(2026, 10, 1), date(2026, 12, 31))
    assert rec.requests[0].url.path.endswith("/range/1/day/2026-10-01/2026-10-27")
    assert [(b.date, b.close) for b in bars] == [
        (date(2026, 10, 26), 260.0),
        (date(2026, 10, 27), 262.0),
    ]
    p.history("AAPL", date(2026, 10, 1), date(2026, 12, 31))
    assert len(rec.requests) == 1
