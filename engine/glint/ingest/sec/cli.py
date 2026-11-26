"""`glint ingest sec` (WT-01): download and extract the SEC bulk files (bulk only)."""

import asyncio
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from glint.core.errors import GlintError
from glint.core.http import SecGateway
from glint.core.log import configure_logging
from glint.core.paths import Paths
from glint.ingest.sec.covers import CoverReport
from glint.ingest.sec.download import DownloadReport
from glint.ingest.sec.extract import ExtractStats
from glint.ingest.sec.run import IngestReport, run_covers, run_ingest

app = typer.Typer(help="Download and extract the SEC bulk files.")
console = Console()


def _print_download(report: DownloadReport) -> None:
    table = Table(title=f"SEC bulk files → {report.folder}")
    table.add_column("file")
    table.add_column("status")
    table.add_column("MB", justify="right")
    for f in report.files:
        table.add_row(f.name, "downloaded" if f.changed else "unchanged", f"{f.bytes / 1e6:,.1f}")
    console.print(table)
    if report.unchanged:
        console.print("Nothing changed since the last download (no-op).")


def _print_covers(report: CoverReport) -> None:
    console.print(
        f"cover facts: {report.targets:,} listed 10-K/10-Q filers — {report.cached:,} cached, "
        f"{report.fetched:,} fetched, {report.no_instance:,} without an XBRL instance, "
        f"{len(report.failed):,} failed (retried next run)"
    )
    for line in report.failed[:10]:
        console.print(f"[yellow]  {line}[/yellow]")


def _print_facts(stats: ExtractStats) -> None:
    if stats.reused_from:
        how = f"reused (hard-linked) from {stats.reused_from}"
    elif stats.skipped:
        how = "already extracted (same source and tag list)"
    else:
        how = f"extracted in {stats.seconds:,.0f} s"
    console.print(
        f"facts_raw: {how} — {stats.companies:,} companies, {stats.facts_kept:,} facts kept, "
        f"{stats.companies_without_kept_facts:,} companies with no kept facts, "
        f"{stats.files_written:,} parquet files"
    )


@app.callback(invoke_without_command=True)
def ingest_sec(
    download: bool = typer.Option(True, help="Fetch from SEC first (else use the latest folder)."),
    force_extract: bool = typer.Option(False, help="Re-extract facts_raw even if up to date."),
    covers_only: bool = typer.Option(
        False, help="Only fetch cover-page facts by class for the newest folder (no bulk files)."
    ),
) -> None:
    """Fetch companyfacts.zip, submissions.zip and company_tickers_exchange.json, then extract."""
    configure_logging()
    paths = Paths.from_settings()
    if covers_only:

        async def covers() -> tuple[Any, CoverReport, Any]:
            async with SecGateway() as gateway:
                return await run_covers(gateway, paths.raw_dir)

        try:
            folder, cover_report, built = asyncio.run(covers())
        except GlintError as exc:
            console.print(f"[red]error:[/red] {exc.message}")
            raise typer.Exit(1) from exc
        _print_covers(cover_report)
        console.print(f"companies: {built.companies:,} rows → {built.path} ({folder.name})")
        return

    async def run() -> IngestReport:
        if not download:
            return await run_ingest(
                None, paths.raw_dir, download=False, force_extract=force_extract
            )
        async with SecGateway() as gateway:
            return await run_ingest(gateway, paths.raw_dir, force_extract=force_extract)

    try:
        report = asyncio.run(run())
    except GlintError as exc:
        console.print(f"[red]error:[/red] {exc.message}")
        raise typer.Exit(1) from exc
    if report.download is not None:
        _print_download(report.download)
        if report.download.covers is not None:
            _print_covers(report.download.covers)
    _print_facts(report.facts)
    console.print(
        f"companies: {report.companies.companies:,} rows → {report.companies.path} "
        f"({report.companies.seconds:,.0f} s)"
    )
    if missing := report.companies.missing_submissions:
        console.print(
            f"[yellow]{len(missing):,} CIKs have no submissions record (kind and foreign status "
            f"unverified): {', '.join(missing[:20])}{' …' if len(missing) > 20 else ''}[/yellow]"
        )
    for p in report.removed_folders:
        console.print(f"pruned old folder {p.name}")
