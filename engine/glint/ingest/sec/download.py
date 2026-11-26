"""Download the SEC bulk files into GLINT_RAW_DIR/sec/<YYYY-MM-DD>/ (WT-01 step 1).

- Everything goes through the SEC gateway, under `raw.lock`.
- A new day's folder starts from the previous folder: data files are hard-linked (no extra disk)
  and the gateway's `<file>.meta.json` (ETag / Last-Modified) is copied, so the conditional GET
  turns an unchanged file into a 304 and no bytes move. A second run the same day is a no-op.
- Changed zips are CRC-checked in full; a corrupt download is deleted so the next run refetches.
- `manifest.json` records url, bytes, sha256, etag, last-modified and fetched_at per file. An
  unchanged file carries its previous entry forward only if etag and size still match it (after a
  run that died midway, the meta can be newer than the last manifest).
- `prune` keeps the newest `KEEP_FOLDERS` folders that have a marker file, plus anything newer.
"""

import hashlib
import re
import shutil
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import orjson

from glint.core.errors import SourceError
from glint.core.filelock import raw_lock
from glint.core.http import SecGateway
from glint.core.log import get_logger, log_event
from glint.ingest.sec.covers import CoverReport, cover_targets, fetch_covers

log = get_logger(__name__)

KEEP_FOLDERS = 3
MANIFEST = "manifest.json"
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class BulkFile:
    name: str
    url: str

    @property
    def is_zip(self) -> bool:
        return self.name.endswith(".zip")


COMPANYFACTS = BulkFile(
    "companyfacts.zip", "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
)
SUBMISSIONS = BulkFile(
    "submissions.zip", "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
)
TICKERS = BulkFile(
    "company_tickers_exchange.json", "https://www.sec.gov/files/company_tickers_exchange.json"
)
BULK_FILES: tuple[BulkFile, ...] = (COMPANYFACTS, SUBMISSIONS, TICKERS)


@dataclass(frozen=True)
class FileResult:
    name: str
    changed: bool
    bytes: int


@dataclass(frozen=True)
class DownloadReport:
    folder: Path
    files: list[FileResult]
    covers: CoverReport | None = None  # cover-page facts by class (covers.py)

    @property
    def unchanged(self) -> bool:
        return not any(f.changed for f in self.files)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def dated_folders(sec_raw: Path) -> list[Path]:
    """Dated download folders, oldest first."""
    if not sec_raw.exists():
        return []
    return sorted(p for p in sec_raw.iterdir() if p.is_dir() and _DATED.match(p.name))


def latest_folder(sec_raw: Path, marker: str = MANIFEST) -> Path | None:
    """The newest dated folder that has `marker` (default: the manifest of a completed download)."""
    done = [f for f in dated_folders(sec_raw) if (f / marker).exists()]
    return done[-1] if done else None


def _meta(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _seed_from_previous(folder: Path, previous: Path | None, files: Sequence[BulkFile]) -> None:
    """Start today's folder from the last one: hard-link data, copy the (mutable) meta."""
    if previous is None or previous == folder:
        return
    for f in files:
        src, dst = previous / f.name, folder / f.name
        if dst.exists() or not src.exists() or not _meta(src).exists():
            continue
        dst.hardlink_to(src)
        shutil.copyfile(_meta(src), _meta(dst))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def verify_zip(path: Path) -> int:
    """Full CRC check of every member. Returns the member count; raises SourceError if corrupt."""
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            count = len(zf.infolist())
    except zipfile.BadZipFile as exc:
        raise SourceError("sec", f"{path.name} is not a valid zip: {exc}") from exc
    if bad is not None:
        raise SourceError("sec", f"{path.name}: CRC check failed for member {bad}")
    return count


def _discard(path: Path) -> None:
    path.unlink(missing_ok=True)
    _meta(path).unlink(missing_ok=True)


def prune(sec_raw: Path, keep: int = KEEP_FOLDERS, marker: str = MANIFEST) -> list[Path]:
    """Keep the newest `keep` folders that have `marker`, and every folder newer than the oldest of
    them (e.g. today's, still being built). Older folders go, complete or not."""
    folders = dated_folders(sec_raw)
    done = [f for f in folders if (f / marker).exists()]
    if len(done) < keep:
        return []
    oldest_kept = done[-keep]
    removed = [f for f in folders if f < oldest_kept]
    for f in removed:
        shutil.rmtree(f)
    return removed


async def download_bulk(
    gateway: SecGateway,
    sec_raw: Path,
    *,
    today: date | None = None,
    files: Sequence[BulkFile] = BULK_FILES,
    now: Callable[[], datetime] = _utcnow,
    covers: bool = True,
) -> DownloadReport:
    """Fetch the bulk files into sec_raw/<today>/, then (with `covers`) the cover-page facts by
    class of each listed company's latest 10-K/10-Q not already cached (covers.py). Caller holds
    raw.lock and prunes afterwards."""
    today = today or now().date()
    folder = sec_raw / today.isoformat()
    previous = latest_folder(sec_raw)
    folder.mkdir(parents=True, exist_ok=True)
    _seed_from_previous(folder, previous, files)

    old_manifest: dict[str, Any] = {}
    for source in (folder, previous):
        if source is not None and (source / MANIFEST).exists():
            old_manifest = orjson.loads((source / MANIFEST).read_bytes())["files"]
            break

    entries: dict[str, Any] = {}
    results: list[FileResult] = []
    for f in files:
        dest = folder / f.name
        res = await gateway.download(f.url, dest)
        prior = old_manifest.get(f.name)
        same = prior is not None and (prior.get("etag"), prior.get("bytes")) == (
            res.etag,
            res.bytes,
        )
        if res.changed or not same:
            if f.is_zip:
                try:
                    members = verify_zip(dest)
                except SourceError:
                    _discard(dest)
                    raise
                log_event(log, "sec_zip_verified", file=f.name, members=members)
            entry = {
                "url": f.url,
                "bytes": res.bytes,
                "sha256": sha256_file(dest),
                "etag": res.etag,
                "last_modified": res.last_modified,
                "fetched_at": now().isoformat(timespec="seconds"),
            }
        else:
            entry = prior
        entries[f.name] = entry
        results.append(FileResult(f.name, res.changed, res.bytes))
        log_event(log, "sec_file", file=f.name, changed=res.changed, bytes=res.bytes)

    manifest = {"date": today.isoformat(), "files": entries}
    tmp = folder / (MANIFEST + ".tmp")
    tmp.write_bytes(orjson.dumps(manifest, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))
    tmp.replace(folder / MANIFEST)
    cover_report = await fetch_covers(gateway, sec_raw, cover_targets(folder)) if covers else None
    report = DownloadReport(folder, results, cover_report)
    log_event(
        log,
        "sec_download_done",
        folder=str(folder),
        changed=sum(r.changed for r in results),
        unchanged=sum(not r.changed for r in results),
    )
    return report


async def run_download(gateway: SecGateway, raw_dir: Path, **kwargs: Any) -> DownloadReport:
    """`download_bulk` under raw.lock (fails fast if another worktree is downloading)."""
    with raw_lock(raw_dir):
        return await download_bulk(gateway, raw_dir / "sec", **kwargs)
