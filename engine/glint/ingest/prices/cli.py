"""`glint ingest prices [--date D] [--backfill N]`: fetch daily bars into GLINT_RAW_DIR/prices."""

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from glint.core.errors import GlintError
from glint.core.log import configure_logging
from glint.core.paths import Paths
from glint.core.settings import get_settings
from glint.ingest.prices.backfill import IngestResult, backfill, eta_minutes, ingest_dates
from glint.ingest.prices.coverage import (
    RECENT_SESSIONS,
    UniverseTicker,
    coverage_report,
    load_universe,
)
from glint.ingest.prices.factory import make_provider
from glint.ingest.prices.store import PriceStore
from glint.ingest.prices.symbols import canonical_from_sec

app = typer.Typer(help="Fetch daily price bars (--backfill N).")


@app.callback(invoke_without_command=True)
def ingest_prices(
    day: Annotated[str | None, typer.Option("--date", help="Fetch one date (YYYY-MM-DD).")] = None,
    backfill_sessions: Annotated[
        int | None,
        typer.Option("--backfill", min=1, help="Make sure the last N sessions are on disk."),
    ] = None,
    tickers: Annotated[
        str | None,
        typer.Option(help="Comma-separated tickers (yfinance only; default: the SEC universe)."),
    ] = None,
    provider_name: Annotated[
        str | None,
        typer.Option("--provider", help="massive | yfinance (default: GLINT_PRICE_PROVIDER)."),
    ] = None,
) -> None:
    """Fetch grouped-daily bars. With no options: catch up from the newest date on disk."""
    configure_logging()
    if day and backfill_sessions:
        raise typer.BadParameter("use --date or --backfill, not both")
    settings = get_settings()
    paths = Paths.from_settings(settings)
    store = PriceStore(paths)
    universe = load_universe(paths)
    symbols = (
        [canonical_from_sec(t) for t in tickers.split(",") if t.strip()]
        if tickers
        else [u.ticker for u in universe[0]]
        if universe
        else []
    )
    try:
        provider = make_provider(settings, tickers=symbols, force=provider_name)
        is_massive = provider.name == "massive"
        if provider.is_fallback:
            typer.echo(
                "provider: yfinance (FALLBACK: MASSIVE_API_KEY is not set; "
                f"unofficial source, {len(symbols)} tickers)"
            )
        else:
            typer.echo(f"provider: {provider.name}")
        if not is_massive and not symbols:
            raise GlintError(
                "yfinance needs a ticker list: run `glint ingest sec` first or pass --tickers"
            )
        per_call = 60 / settings.massive_calls_per_min if is_massive else 0.0
        if backfill_sessions:
            typer.echo(
                f"backfill: {backfill_sessions} sessions; worst case "
                f"~{eta_minutes(backfill_sessions, per_call):.0f} min at "
                f"{settings.massive_calls_per_min} calls/min"
                if is_massive
                else f"backfill: {backfill_sessions} sessions"
            )
            result = backfill(store, provider, backfill_sessions, seconds_per_call=per_call)
        else:
            days = [_parse_date(day)] if day else None
            result = ingest_dates(store, provider, days, seconds_per_call=per_call)
    except GlintError as exc:
        typer.echo(f"error: {exc.message}", err=True)
        raise typer.Exit(1) from exc
    _summary(result)
    _coverage(store, universe)


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise typer.BadParameter(f"{text!r} is not a YYYY-MM-DD date", param_hint="--date") from exc


def _summary(r: IngestResult) -> None:
    typer.echo(
        f"fetched {len(r.fetched)} dates ({r.rows:,} bars), {r.on_disk} already on disk, "
        f"{len(r.holidays)} holidays recorded, {r.splits_new} new splits, {r.seconds:.0f}s"
    )
    if r.not_yet_available:
        dates = ", ".join(d.isoformat() for d in r.not_yet_available)
        typer.echo(f"empty, not confirmed as holidays (asked again next run): {dates}")
    if r.history_exhausted:
        typer.echo(f"history ran out after {r.sessions} sessions (provider/plan limit?)")


def _coverage(store: PriceStore, universe: tuple[list[UniverseTicker], Path] | None) -> None:
    latest = store.latest_date()
    if latest is None:
        return
    if universe is None:
        typer.echo("coverage: skipped (no SEC company_tickers_exchange.json in GLINT_RAW_DIR/sec)")
        return
    tickers, source = universe
    recent = store.dates_on_disk()[-RECENT_SESSIONS:]
    report = coverage_report(
        tickers, store.read_bars(start=recent[0], end=latest), latest, source=str(source)
    )
    with store.writer():
        path = store.write_report(f"coverage-{latest.isoformat()}.json", report)
    n = report["common_listings"]
    typer.echo(
        f"coverage {latest}: {report['priced_latest']:,}/{n:,} common listings priced that day "
        f"({_pct(report['coverage_latest'])}); {report['priced_recent']:,}/{n:,} within the last "
        f"{report['recent_sessions']} sessions ({_pct(report['coverage_recent'])}); "
        f"{report['other_listings']:,} warrants/units/rights/preferreds counted separately → {path}"
    )


def _pct(share: float | None) -> str:
    return "n/a" if share is None else f"{share:.1%}"
