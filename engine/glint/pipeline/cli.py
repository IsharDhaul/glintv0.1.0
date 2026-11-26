"""`glint refresh` (WT-07): the full pipeline, build-then-swap."""

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from glint.contracts.pipeline import BuildOptions
from glint.core.errors import GlintError
from glint.core.log import LogfmtFormatter, configure_logging
from glint.core.paths import Paths
from glint.core.settings import get_settings
from glint.pipeline.runner import Runner, RunReport, StageRun, new_build_id
from glint.pipeline.stages import STAGE_ORDER, default_stages

app = typer.Typer(help="Full pipeline with build-then-swap.")
console = Console()

STATUS_STYLE = {
    "ok": "green",
    "warn": "yellow",
    "skipped": "cyan",
    "failed": "red",
    "not selected": "dim",
    "not run": "dim",
}


def _split(value: str | None) -> list[str]:
    return [s.strip() for s in value.split(",") if s.strip()] if value else []


def _attach_log_file(path: Path) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path)
    handler.setFormatter(LogfmtFormatter())
    logging.getLogger("glint").addHandler(handler)
    return handler


def _print_stage(run: StageRun) -> None:
    r = run.result
    if r is None:
        return
    style = STATUS_STYLE.get(r.status.value, "")
    detail = run.skip_reason or run.note or ""
    console.print(
        f"[{style}]{r.status.value:>7}[/{style}]  {run.name:<17} {r.duration_s:>8.1f}s  {detail}"
    )
    for w in r.warnings:
        console.print(f"{'':>9}[yellow]⚠ {w}[/yellow]")


def _print_plan(report: RunReport) -> None:
    table = Table(title=f"glint refresh --dry-run (would be build {report.build_id})")
    table.add_column("stage")
    table.add_column("plan")
    for run in report.stages:
        if not run.selected:
            table.add_row(run.name, "[dim]not selected[/dim]")
        elif run.skip_reason:
            table.add_row(run.name, f"skip: {run.skip_reason}")
        else:
            table.add_row(run.name, f"run ({run.note})" if run.note else "run")
    console.print(table)
    prev = report.previous
    current = "none" if prev is None else prev.build_id + (" (synthetic)" if prev.synthetic else "")
    console.print(f"current build: {current} · new build would go to {report.build_db}")
    if report.partial:
        console.print("partial run: starts from a copy of the current build")
    if report.error:
        console.print(f"[red]would fail:[/red] {report.error}")
    console.print("dry run: nothing was downloaded or written.")


@app.callback(invoke_without_command=True)
def refresh(
    only: Annotated[
        str | None, typer.Option(help=f"Comma-separated stages to run: {', '.join(STAGE_ORDER)}.")
    ] = None,
    from_: Annotated[
        str | None, typer.Option("--from", help="Run this stage and every stage after it.")
    ] = None,
    no_download: Annotated[
        bool, typer.Option("--no-download", help="No network: rebuild from raw files on disk.")
    ] = False,
    skip_prices: Annotated[
        bool, typer.Option("--skip-prices", help="Don't fetch new price bars.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would run, change nothing.")
    ] = False,
) -> None:
    """Rebuild everything into a new build, then point current.json at it (atomic swap)."""
    configure_logging()
    settings = get_settings()
    paths = Paths.from_settings(settings)
    build_id = new_build_id()
    options = BuildOptions(no_download=no_download, skip_prices=skip_prices, dry_run=dry_run)
    log_path = None if dry_run else paths.db_dir / "logs" / f"{build_id}.log"
    handler = _attach_log_file(log_path) if log_path else None
    try:
        runner = Runner(settings, default_stages())
        report = runner.run(
            options, only=_split(only), from_=from_, on_stage=_print_stage, log_path=log_path,
            build_id=build_id,
        )  # fmt: skip
    except GlintError as exc:
        console.print(f"[red]error:[/red] {exc.message}")
        raise typer.Exit(1) from exc
    finally:
        if handler is not None:
            logging.getLogger("glint").removeHandler(handler)
            handler.close()

    if report.dry_run:
        _print_plan(report)
        return
    _print_outcome(report)
    if report.status == "failed":
        raise typer.Exit(1)


def _print_outcome(report: RunReport) -> None:
    prev = report.previous.build_id if report.previous else "none"
    for w in report.comparison.warnings if report.comparison else []:
        console.print(f"[yellow]⚠ {w}[/yellow]")
    if report.report_path is not None:
        console.print(f"report: {report.report_path}")
    if report.status == "failed":
        where = f"stage [bold]{report.failed_stage}[/bold]" if report.failed_stage else "setup"
        console.print(f"[red]✗ refresh failed in {where}:[/red] {report.error}")
        console.print(f"  log: {report.log_path}")
        console.print(f"  current build unchanged: {prev}")
        return
    if report.published:
        console.print(
            f"[green]✓ published {report.build_id}[/green] ({report.status}, "
            f"{report.seconds:,.0f} s); previous: {prev}"
        )
        if report.pruned_builds:
            console.print(f"  removed old builds: {', '.join(report.pruned_builds)}")
        for n in report.notices:
            console.print(f"[yellow]⚠ {n}[/yellow]")
    else:
        console.print(f"✓ done ({report.status}); no build stage selected, nothing published")
