import asyncio
import hashlib
import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import orjson
import pytest

from glint.core.errors import SourceError
from glint.core.filelock import LockTimeoutError, exclusive_lock
from glint.core.http import SecGateway
from glint.core.settings import Settings
from glint.ingest.sec.download import (
    TICKERS,
    DownloadReport,
    download_bulk,
    prune,
    run_download,
    sha256_file,
)


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class FakeSec:
    """Serves the three bulk files with ETags and honours If-None-Match."""

    def __init__(self) -> None:
        self.bodies = {
            "companyfacts.zip": zip_bytes({"CIK0000320193.json": b'{"cik": 320193}'}),
            "submissions.zip": zip_bytes({"CIK0000320193.json": b'{"cik": "320193"}'}),
            "company_tickers_exchange.json": b'{"fields": [], "data": []}',
        }
        self.version = 1
        self.full_downloads = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        name = req.url.path.rsplit("/", 1)[-1]
        etag = f'"{name}-v{self.version}"'
        if req.headers.get("If-None-Match") == etag:
            return httpx.Response(304)
        self.full_downloads += 1
        return httpx.Response(
            200,
            content=self.bodies[name],
            headers={"ETag": etag, "Last-Modified": "Wed, 28 Oct 2026 07:00:00 GMT"},
        )


def run(settings: Settings, fake: FakeSec, sec_raw: Path, today: date) -> DownloadReport:
    async def go() -> DownloadReport:
        transport = httpx.MockTransport(fake.handler)
        async with SecGateway(settings, transport=transport) as gw:
            return await download_bulk(
                gw, sec_raw, today=today, now=lambda: datetime(2026, 10, 29, tzinfo=UTC)
            )

    return asyncio.run(go())


def test_first_run_downloads_and_writes_manifest(settings: Settings, tmp_path: Path) -> None:
    fake = FakeSec()
    report = run(settings, fake, tmp_path / "sec", date(2026, 10, 29))
    assert report.folder == tmp_path / "sec" / "2026-10-29"
    assert [f.changed for f in report.files] == [True, True, True]
    manifest = orjson.loads((report.folder / "manifest.json").read_bytes())
    entry = manifest["files"]["companyfacts.zip"]
    assert entry["bytes"] == len(fake.bodies["companyfacts.zip"])
    assert entry["sha256"] == sha256_file(report.folder / "companyfacts.zip")
    assert entry["url"].endswith("/xbrl/companyfacts.zip")
    assert entry["last_modified"] == "Wed, 28 Oct 2026 07:00:00 GMT"
    assert entry["fetched_at"] == "2026-10-29T00:00:00+00:00"


def test_second_run_same_day_is_a_noop(settings: Settings, tmp_path: Path) -> None:
    fake = FakeSec()
    run(settings, fake, tmp_path / "sec", date(2026, 10, 29))
    report = run(settings, fake, tmp_path / "sec", date(2026, 10, 29))
    assert report.unchanged
    assert fake.full_downloads == 3


def test_new_day_reuses_unchanged_files_without_copying(settings: Settings, tmp_path: Path) -> None:
    fake = FakeSec()
    sec = tmp_path / "sec"
    first = run(settings, fake, sec, date(2026, 10, 29))
    second = run(settings, fake, sec, date(2026, 10, 30))
    assert second.unchanged
    assert fake.full_downloads == 3
    a, b = first.folder / "companyfacts.zip", second.folder / "companyfacts.zip"
    assert a.stat().st_ino == b.stat().st_ino  # hard link, no extra disk
    m1 = orjson.loads((first.folder / "manifest.json").read_bytes())["files"]
    m2 = orjson.loads((second.folder / "manifest.json").read_bytes())["files"]
    assert m1["companyfacts.zip"]["sha256"] == m2["companyfacts.zip"]["sha256"]


def test_changed_file_on_new_day_does_not_touch_previous_folder(
    settings: Settings, tmp_path: Path
) -> None:
    fake = FakeSec()
    sec = tmp_path / "sec"
    first = run(settings, fake, sec, date(2026, 10, 29))
    old_bytes = (first.folder / "companyfacts.zip").read_bytes()
    old_meta = (first.folder / "companyfacts.zip.meta.json").read_bytes()
    fake.version = 2
    fake.bodies["companyfacts.zip"] = zip_bytes({"CIK0000320193.json": b'{"cik": 1}'})
    second = run(settings, fake, sec, date(2026, 10, 30))
    assert all(f.changed for f in second.files)
    assert (first.folder / "companyfacts.zip").read_bytes() == old_bytes
    assert (first.folder / "companyfacts.zip.meta.json").read_bytes() == old_meta


def test_corrupt_zip_is_discarded(settings: Settings, tmp_path: Path) -> None:
    fake = FakeSec()
    fake.bodies["companyfacts.zip"] = b"not a zip"
    with pytest.raises(SourceError, match="not a valid zip"):
        run(settings, fake, tmp_path / "sec", date(2026, 10, 29))
    folder = tmp_path / "sec" / "2026-10-29"
    assert not (folder / "companyfacts.zip").exists()
    assert not (folder / "companyfacts.zip.meta.json").exists()
    assert not (folder / "manifest.json").exists()


def test_prune_keeps_three_marked_folders_and_anything_newer(tmp_path: Path) -> None:
    sec = tmp_path / "sec"
    marked = ["2026-10-22", "2026-10-24", "2026-10-26", "2026-10-27"]
    for day in [*marked, "2026-10-23", "2026-10-25", "2026-10-28"]:
        (sec / day).mkdir(parents=True)
    for day in marked:
        (sec / day / "done").write_text("")
    removed = prune(sec, keep=3, marker="done")
    assert [p.name for p in removed] == ["2026-10-22", "2026-10-23"]
    # 2026-10-25 (crashed) sits between kept folders; 2026-10-28 is today's, still building.
    assert [p.name for p in sorted(sec.iterdir())] == [
        "2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28",
    ]  # fmt: skip
    assert prune(sec, keep=5, marker="done") == []


def test_crash_after_a_200_does_not_reuse_the_old_manifest_entry(
    settings: Settings, tmp_path: Path
) -> None:
    fake = FakeSec()
    sec = tmp_path / "sec"
    run(settings, fake, sec, date(2026, 10, 29))
    fake.version = 2
    new_zip = zip_bytes({"CIK0000320193.json": b'{"cik": 2}'})
    fake.bodies["companyfacts.zip"] = new_zip
    fake.bodies["submissions.zip"] = b"not a zip"  # the run dies after companyfacts got its 200
    with pytest.raises(SourceError):
        run(settings, fake, sec, date(2026, 10, 30))
    fake.bodies["submissions.zip"] = zip_bytes({"CIK0000320193.json": b"{}"})
    second = run(settings, fake, sec, date(2026, 10, 30))
    entry = orjson.loads((second.folder / "manifest.json").read_bytes())["files"][
        "companyfacts.zip"
    ]
    assert entry["sha256"] == hashlib.sha256(new_zip).hexdigest()
    assert entry["etag"] == '"companyfacts.zip-v2"' and entry["bytes"] == len(new_zip)


def test_refuses_while_another_process_holds_raw_lock(settings: Settings) -> None:
    fake = FakeSec()

    async def go() -> None:
        async with SecGateway(settings, transport=httpx.MockTransport(fake.handler)) as gw:
            await run_download(gw, settings.raw_dir)

    # flock is per open file description, so a second open in this process still conflicts.
    with exclusive_lock(settings.raw_dir / "raw.lock"), pytest.raises(LockTimeoutError):
        asyncio.run(go())
    assert fake.full_downloads == 0


@pytest.mark.live
def test_live_downloads_ticker_file(tmp_path: Path) -> None:
    """Real SEC call (needs GLINT_SEC_USER_AGENT in .env). Only the small ticker file."""

    async def go() -> DownloadReport:
        async with SecGateway() as gw:
            return await download_bulk(gw, tmp_path / "sec", files=[TICKERS])

    report = asyncio.run(go())
    doc = orjson.loads((report.folder / TICKERS.name).read_bytes())
    assert doc["fields"] == ["cik", "name", "ticker", "exchange"]
    assert len(doc["data"]) > 5000
