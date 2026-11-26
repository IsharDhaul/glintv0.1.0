"""`glint ingest sec` end to end: download, extract facts, build companies, under one raw.lock.

Readers use the newest folder with `companies.parquet` (a finished ingest); old folders are pruned
only after today's build succeeds.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import orjson

from glint.core.errors import SourceError
from glint.core.filelock import raw_lock
from glint.core.http import SecGateway
from glint.ingest.sec.covers import CoverReport, cover_targets, fetch_covers
from glint.ingest.sec.download import (
    COMPANYFACTS,
    MANIFEST,
    DownloadReport,
    dated_folders,
    download_bulk,
    latest_folder,
    prune,
)
from glint.ingest.sec.extract import FACTS_DIR, ExtractStats, extract_facts
from glint.universe.build import COMPANIES_FILE, BuildReport, write_companies


@dataclass(frozen=True)
class IngestReport:
    folder: Path
    download: DownloadReport | None
    facts: ExtractStats
    companies: BuildReport
    removed_folders: list[Path]


def extract_folder(folder: Path, *, force: bool = False) -> ExtractStats:
    manifest = orjson.loads((folder / MANIFEST).read_bytes())
    sha = manifest["files"][COMPANYFACTS.name]["sha256"]
    previous = [f / FACTS_DIR for f in reversed(dated_folders(folder.parent)) if f != folder]
    return extract_facts(
        folder / COMPANYFACTS.name, folder / FACTS_DIR, source_sha256=sha,
        previous_out=previous, force=force,
    )  # fmt: skip


async def run_ingest(
    gateway: SecGateway | None, raw_dir: Path, *, download: bool = True, force_extract: bool = False
) -> IngestReport:
    sec_raw = raw_dir / "sec"
    with raw_lock(raw_dir):
        report: DownloadReport | None = None
        if download:
            if gateway is None:
                raise SourceError("sec", "download requested without a gateway")
            report = await download_bulk(gateway, sec_raw)
            folder = report.folder
        else:
            latest = latest_folder(sec_raw)
            if latest is None:
                raise SourceError(
                    "sec", f"no completed download under {sec_raw}; run without --no-download"
                )
            folder = latest
        facts = extract_folder(folder, force=force_extract)
        companies = write_companies(folder, as_of=date.fromisoformat(folder.name))
        removed = prune(sec_raw, marker=COMPANIES_FILE)
    return IngestReport(folder, report, facts, companies, removed)


async def run_covers(gateway: SecGateway, raw_dir: Path) -> tuple[Path, CoverReport, BuildReport]:
    """Cover-page facts for the newest finished folder (no bulk download), then rebuild its
    companies.parquet so the Up-C columns use them."""
    sec_raw = raw_dir / "sec"
    with raw_lock(raw_dir):
        folder = latest_folder(sec_raw)
        if folder is None:
            raise SourceError("sec", f"no completed download under {sec_raw}")
        covers = await fetch_covers(gateway, sec_raw, cover_targets(folder))
        companies = write_companies(folder, as_of=date.fromisoformat(folder.name))
    return folder, covers, companies
