"""`glint ingest sec` end to end against a fake SEC: download → facts_raw → companies."""

import asyncio
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import orjson
import polars as pl
import pytest

from glint.core.errors import SourceError
from glint.core.http import SecGateway
from glint.core.settings import Settings
from glint.fixtures.sec import FIXTURE_DIR
from glint.ingest.sec.run import IngestReport, run_ingest

TICKERS = ["AAPL", "BRK.B", "GOOGL", "TSM", "AAC"]


def bodies() -> dict[str, bytes]:
    manifest = orjson.loads((FIXTURE_DIR / "manifest.json").read_bytes())
    ciks = {f["ticker"]: f["cik"] for f in manifest["fixtures"]}
    out: dict[str, bytes] = {}
    for name, kind in (("companyfacts.zip", "companyfacts"), ("submissions.zip", "submissions")):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for t in TICKERS:
                zf.writestr(f"CIK{ciks[t]}.json", (FIXTURE_DIR / f"{t}.{kind}.json").read_bytes())
        out[name] = buf.getvalue()
    tick = orjson.loads((FIXTURE_DIR / "company_tickers_exchange.json").read_bytes())
    keep = {int(ciks[t]) for t in TICKERS}
    tick["data"] = [r for r in tick["data"] if int(r[0]) in keep]
    out["company_tickers_exchange.json"] = orjson.dumps(tick)
    return out


def ingest(settings: Settings, download: bool = True) -> IngestReport:
    files = bodies()

    def handler(req: httpx.Request) -> httpx.Response:
        name = req.url.path.rsplit("/", 1)[-1]
        if req.headers.get("If-None-Match") == f'"{name}"':
            return httpx.Response(304)
        return httpx.Response(200, content=files[name], headers={"ETag": f'"{name}"'})

    async def go() -> IngestReport:
        if not download:
            return await run_ingest(None, settings.raw_dir, download=False)
        async with SecGateway(settings, transport=httpx.MockTransport(handler)) as gw:
            return await run_ingest(gw, settings.raw_dir)

    return asyncio.run(go())


def test_end_to_end(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import glint.ingest.sec.download as dl  # noqa: PLC0415

    monkeypatch.setattr(dl, "_utcnow", lambda: datetime(2026, 10, 29, tzinfo=UTC))
    first = ingest(settings)
    assert first.download is not None and not first.download.unchanged
    assert first.facts.companies == len(TICKERS) and first.facts.facts_kept > 0
    assert first.companies.companies == len(TICKERS)

    df = pl.read_parquet(first.companies.path)
    rows = {r["primary_ticker"]: r for r in df.iter_rows(named=True)}
    assert rows["BRK.B"]["tickers"] == ["BRK.B", "BRK.A"]
    assert rows["GOOGL"]["sector"] == "Technology"
    assert rows["AAC"]["kind"] == "spac"
    assert rows["TSM"]["is_foreign_filer"] and rows["TSM"]["reporting_currency"] == "TWD"

    second = ingest(settings)
    assert second.download is not None and second.download.unchanged
    assert second.facts.skipped

    offline = ingest(settings, download=False)
    assert offline.download is None and offline.folder == first.folder


def test_no_download_needs_a_previous_download(settings: Settings) -> None:
    with pytest.raises(SourceError, match="no completed download"):
        ingest(settings, download=False)


def test_folder_has_expected_layout(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import glint.ingest.sec.download as dl  # noqa: PLC0415

    monkeypatch.setattr(dl, "_utcnow", lambda: datetime(2026, 10, 29, tzinfo=UTC))
    folder: Path = ingest(settings).folder
    names = {p.name for p in folder.iterdir()}
    assert {"companyfacts.zip", "submissions.zip", "company_tickers_exchange.json",
            "manifest.json", "facts_raw", "companies.parquet"} <= names  # fmt: skip
