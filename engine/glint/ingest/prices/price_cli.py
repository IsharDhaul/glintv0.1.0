"""`glint price TICKER`: the last bars and the price stats, from what is on disk (no network)."""

from typing import Annotated

import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from glint.contracts.enums import NOTE_DISPLAY, NoteCode
from glint.core.paths import Paths
from glint.core.settings import get_settings
from glint.ingest.prices.splits import adjust_for_splits
from glint.ingest.prices.stats import STAT_COLUMNS, price_stats
from glint.ingest.prices.store import PriceStore
from glint.ingest.prices.symbols import canonical_from_sec
from glint.ingest.prices.ticker_changes import renamed_to

app = typer.Typer(
    help="Show bars and price stats for a ticker.",
    context_settings={"allow_interspersed_args": True},  # `glint price AAPL --days 3`
)

_PCT = frozenset(
    {
        "return_1m",
        "return_3m",
        "return_6m",
        "return_12m",
        "momentum_12_1",
        "pct_from_52w_high",
        "volatility_1y",
    }
)


def _fmt(stat: str, value: float | None) -> str:
    if value is None:
        return "—"
    if stat in _PCT:
        return f"{value:+.2%}" if stat != "volatility_1y" else f"{value:.2%}"
    if stat == "avg_dollar_volume_3m":
        return f"${value:,.0f}"
    return f"{value:,.2f}"


@app.callback(invoke_without_command=True)
def price(
    ticker: Annotated[str, typer.Argument(help="Ticker, e.g. AAPL or BRK.B")],
    days: Annotated[int, typer.Option(min=1, help="How many recent bars to show.")] = 10,
) -> None:
    """Recent bars (unadjusted and split-adjusted) plus price stats. Tier 2 market data."""
    symbol = canonical_from_sec(ticker)
    store = PriceStore(Paths.from_settings(get_settings()))
    as_of = store.latest_date()
    if as_of is None:
        typer.echo("no prices on disk yet: run `glint ingest prices --backfill N`", err=True)
        raise typer.Exit(1)
    if (change := renamed_to(symbol, store.active_changes())) is not None:
        typer.echo(f"{symbol} became {change.new} on {change.effective} (same company, CIK "
                   f"{change.cik}); showing {change.new}", err=True)  # fmt: skip
        symbol = change.new
    bars = store.read_bars(tickers=[symbol])
    if bars.height == 0:
        typer.echo(f"{symbol}: no price bars on disk (newest date {as_of})", err=True)
        raise typer.Exit(1)
    adjusted = adjust_for_splits(bars, store.load_splits(), as_of)
    result = price_stats(adjusted, as_of)
    stats = result.stats.row(0, named=True)
    notes = {r["stat"]: r for r in result.notes.iter_rows(named=True)}

    console = Console()
    console.print(
        f"[bold]{symbol}[/bold]  price date {stats['as_of']}  ·  {stats['history_days']} "
        f"sessions on disk  ·  tier 2 market data (not from filings)"
    )
    if stats["as_of"] != as_of:
        console.print(f"[yellow]no bar on {as_of}, the newest date on disk[/yellow]")

    bars_table = Table(title=f"Last {days} bars")
    for col in ("date", "open", "high", "low", "close", "adj close", "volume"):
        bars_table.add_column(col, justify="right")
    tail = adjusted.tail(days)
    for r in tail.iter_rows(named=True):
        bars_table.add_row(
            str(r["date"]),
            f"{r['open']:,.2f}",
            f"{r['high']:,.2f}",
            f"{r['low']:,.2f}",
            f"{r['close']:,.2f}",
            f"{r['adj_close']:,.2f}",
            f"{r['volume']:,.0f}",
        )
    console.print(bars_table)

    stats_table = Table(title="Price stats (price return only, excludes dividends)")
    stats_table.add_column("stat")
    stats_table.add_column("value", justify="right")
    stats_table.add_column("note")
    for stat in STAT_COLUMNS:
        note = notes.get(stat)
        shown = _fmt(stat, stats[stat])
        if note:
            shown = NOTE_DISPLAY[NoteCode(note["code"])].value
        stats_table.add_row(stat, shown, f"{note['code']}: {note['message']}" if note else "")
    console.print(stats_table)
    splits = store.load_splits().filter(pl.col("ticker") == symbol)
    for s in splits.iter_rows(named=True):
        console.print(
            f"split {s['execution_date']}: {s['split_to']:g}-for-{s['split_from']:g} "
            f"({s['adjustment_type'] or 'split'})"
        )
