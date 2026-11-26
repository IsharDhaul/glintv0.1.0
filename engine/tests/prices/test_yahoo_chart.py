"""The Yahoo chart transport, on a real recorded response (NVDA, 10-for-1 on 2024-06-10).

Recorded 2026-10-29. Yahoo's closes are split-adjusted as of the recording date, so the raw
pre-split close only comes back after un-adjusting. NVDA's real close on 2024-06-07 was $1,208.88.
"""

from datetime import date
from pathlib import Path

import httpx
import orjson
import pytest

from glint.ingest.prices.yahoo_chart import chart_download, parse_chart
from glint.ingest.prices.yfinance_provider import frame_rows, unadjust
from tests.prices.helpers import FakeClock

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo" / "chart_NVDA_2024-06.json"


def test_parse_recorded_chart() -> None:
    rows = parse_chart(orjson.loads(FIXTURE.read_bytes()))
    assert date(2024, 6, 7) in rows
    assert rows[date(2024, 6, 7)]["Close"] == pytest.approx(120.888, abs=0.001)  # adjusted
    assert rows[date(2024, 6, 10)]["Stock Splits"] == 10.0
    assert rows[date(2024, 6, 7)]["Stock Splits"] == 0.0
    # only quote columns and split events are read; vendor fields in `meta`
    # (fiftyTwoWeekHigh, …) are never used
    assert set(rows[date(2024, 6, 7)]) == {"Open", "High", "Low", "Close", "Volume", "Stock Splits"}


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_download_unadjusts_to_the_traded_close() -> None:
    body = FIXTURE.read_bytes()
    client = _client(httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
    frame = chart_download(["NVDA"], date(2024, 6, 5), date(2024, 6, 13), client=client)
    bars, splits = unadjust(frame_rows(frame, "NVDA"))
    by_day = {b.date: b for b in bars}
    assert by_day[date(2024, 6, 7)].close == pytest.approx(1208.88, abs=0.01)
    assert by_day[date(2024, 6, 10)].close == pytest.approx(121.79, abs=0.01)
    assert [(s.execution_date, s.ratio) for s in splits] == [(date(2024, 6, 10), 10.0)]


def test_failed_symbol_is_empty_not_fatal() -> None:
    body = FIXTURE.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if "NOPE" in request.url.path:
            return httpx.Response(
                404, content=b'{"chart":{"result":null,"error":{"code":"Not Found"}}}'
            )
        if "BOOM" in request.url.path:
            raise httpx.ConnectError("reset", request=request)
        return httpx.Response(200, content=body)

    clock = FakeClock()
    frame = chart_download(
        ["NOPE", "NVDA", "BOOM"],
        date(2024, 6, 5),
        date(2024, 6, 13),
        client=_client(httpx.MockTransport(handler)),
        sleep=clock.sleep,
    )
    assert frame_rows(frame, "NOPE") == []
    assert frame_rows(frame, "BOOM") == []
    assert len(frame_rows(frame, "NVDA")) == 6
    assert clock.sleeps == [0.25, 0.25]  # polite pause between symbols


def test_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=FIXTURE.read_bytes())

    chart_download(
        ["BRK-B"], date(2024, 6, 5), date(2024, 6, 13), client=_client(httpx.MockTransport(handler))
    )
    (req,) = seen
    assert req.url.host == "query1.finance.yahoo.com"
    assert req.url.path == "/v8/finance/chart/BRK-B"
    assert req.url.params["interval"] == "1d"
    assert req.url.params["events"] == "split"
    assert req.url.params["period1"] == "1717545600"  # 2024-06-05 00:00 UTC
