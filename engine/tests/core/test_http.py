import asyncio
from pathlib import Path

import httpx
import pytest

from glint.core.errors import SourceError
from glint.core.http import SecGateway
from glint.core.settings import Settings
from tests.conftest import make_settings

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def gateway(settings: Settings, handler: httpx.MockTransport) -> SecGateway:
    return SecGateway(settings, transport=handler, backoff_initial_s=0, backoff_max_s=0)


def test_sets_user_agent_and_parses_json(settings: Settings) -> None:
    seen: list[str] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["User-Agent"])
        return httpx.Response(200, json={"cik": 320193})

    async def run() -> object:
        async with gateway(settings, httpx.MockTransport(handle)) as sec:
            return await sec.get_json(URL)

    assert asyncio.run(run()) == {"cik": 320193}
    assert seen == [settings.sec_user_agent]


def test_retries_429_and_5xx_then_succeeds(settings: Settings) -> None:
    statuses = iter([429, 503, 200])

    def handle(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json={})

    async def run() -> object:
        async with gateway(settings, httpx.MockTransport(handle)) as sec:
            return await sec.get_json(URL)

    assert asyncio.run(run()) == {}


def test_gives_up_after_max_attempts(settings: Settings) -> None:
    calls = 0

    def handle(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async def run() -> object:
        async with gateway(settings, httpx.MockTransport(handle)) as sec:
            return await sec.get_json(URL)

    with pytest.raises(SourceError) as err:
        asyncio.run(run())
    assert err.value.status == 503
    assert calls == 5


def test_404_is_not_retried(settings: Settings) -> None:
    calls = 0

    def handle(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    async def run() -> object:
        async with gateway(settings, httpx.MockTransport(handle)) as sec:
            return await sec.get_json(URL)

    with pytest.raises(SourceError):
        asyncio.run(run())
    assert calls == 1


def test_retries_network_errors(settings: Settings) -> None:
    calls = 0

    def handle(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("boom", request=req)
        return httpx.Response(200, json=[1])

    async def run() -> object:
        async with gateway(settings, httpx.MockTransport(handle)) as sec:
            return await sec.get_json(URL)

    assert asyncio.run(run()) == [1]


def test_refuses_non_sec_hosts(settings: Settings) -> None:
    async def run() -> object:
        async with gateway(settings, httpx.MockTransport(lambda _r: httpx.Response(200))) as sec:
            return await sec.get_json("https://example.com/x.json")

    with pytest.raises(SourceError, match="non-SEC host"):
        asyncio.run(run())


def test_refuses_placeholder_user_agent(tmp_path: Path) -> None:
    s = make_settings(raw_dir=tmp_path, db_dir=tmp_path)
    with pytest.raises(SourceError, match="contact address"):
        SecGateway(s)


def test_download_streams_then_uses_conditional_get(settings: Settings, tmp_path: Path) -> None:
    body = b"x" * 3_000_000
    seen_headers: list[dict[str, str]] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(req.headers))
        if req.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=body, headers={"ETag": '"v1"'})

    dest = tmp_path / "sec" / "companyfacts.zip"

    async def run() -> tuple[bool, bool]:
        async with gateway(settings, httpx.MockTransport(handle)) as sec:
            first = await sec.download("https://www.sec.gov/files/companyfacts.zip", dest)
            second = await sec.download("https://www.sec.gov/files/companyfacts.zip", dest)
            return first.changed, second.changed

    assert asyncio.run(run()) == (True, False)
    assert dest.read_bytes() == body
    assert "if-none-match" not in seen_headers[0]
    assert seen_headers[1]["if-none-match"] == '"v1"'
    assert not dest.with_name("companyfacts.zip.part").exists()
