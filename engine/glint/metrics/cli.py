"""`glint metrics TICKER [--category c] [--explain id] [--db PATH]` (WT-06 step 12).

Without --explain: every live metric of the company from the build's snapshot, by category, each
with its null reason or note. With --explain: the formula, each input (value, period, tag,
accession) and the result, recomputed from the build's tables by the stage's own functions.
"""

from pathlib import Path

import duckdb
import typer
from rich.console import Console
from rich.table import Table

from glint.api.build import build_db_path, connect_read_only, read_pointer
from glint.contracts.enums import NOTE_DISPLAY, Category, NoteCode
from glint.contracts.metrics import load_registry
from glint.core.paths import Paths
from glint.financials.concepts import load_concepts
from glint.flags.engine import load_rules
from glint.metrics.explain import explain, fmt_value
from glint.metrics.io import read_sql
from glint.metrics.params import load_params
from glint.metrics.share_classes import load_share_classes
from glint.metrics.stage import load_side_inputs, run_metrics
from glint.universe.tickers import canonical_symbol

app = typer.Typer(
    help="Metrics for a ticker, with inputs (--explain id).",
    context_settings={"allow_interspersed_args": True},
)
console = Console()


def open_build(db: Path | None) -> duckdb.DuckDBPyConnection:
    if db is not None:
        return connect_read_only(db)
    paths = Paths.from_settings()
    pointer = read_pointer(paths)
    if pointer is None:
        console.print("[red]error:[/red] no build yet: pass --db or run `glint refresh`")
        raise typer.Exit(1)
    return connect_read_only(build_db_path(pointer, paths))


def _cik(con: duckdb.DuckDBPyConnection, ticker: str) -> str:
    t = canonical_symbol(ticker)
    hit = con.execute(
        "SELECT cik FROM companies WHERE list_contains(tickers, ?) ORDER BY cik", [t]
    ).fetchone()
    if hit is None:
        console.print(f"[yellow]{t} is not in this build.[/yellow]")
        raise typer.Exit(1)
    return str(hit[0])


def _note(code: str | None, msg: str | None) -> str:
    if code is None:
        return ""
    return f"{NOTE_DISPLAY[NoteCode(code)].value} {code}: {msg}"


def show(con: duckdb.DuckDBPyConnection, cik: str, category: Category | None) -> None:
    reg = load_registry()
    snap = read_sql(con, "SELECT * FROM metrics_snapshot WHERE cik = ?", [cik]).row(0, named=True)
    notes = {
        m: (c, msg)
        for m, c, msg in con.execute(
            "SELECT metric_id, code, message FROM metric_notes WHERE cik = ?", [cik]
        ).fetchall()
    }
    title = (
        f"{snap['name']} ({snap['ticker']}, CIK {cik}) · {snap['sector']} · fundamentals to "
        f"{snap['as_of_fundamentals']} · prices {snap['as_of_prices'] or '—'}"
    )
    table = Table(title=title)
    for col in ("category", "metric", "value", "note"):
        table.add_column(col, justify="right" if col == "value" else "left")
    for m in reg.live():
        if category is not None and m.category is not category:
            continue
        code, msg = notes.get(m.id, (None, None))
        table.add_row(m.category.value, m.id, fmt_value(snap[m.id], m.unit), _note(code, msg))
    console.print(table)
    flags = con.execute(
        "SELECT question FROM flags WHERE cik = ? ORDER BY flag_id", [cik]
    ).fetchall()
    for (q,) in flags:
        console.print(f"[bold]?[/bold] {q}")


def show_explain(con: duckdb.DuckDBPyConnection, cik: str, metric_id: str) -> None:
    reg = load_registry()
    params = load_params()
    companies = read_sql(con, "SELECT * FROM companies WHERE cik = ?", [cik])
    fin = read_sql(con, "SELECT * FROM financials WHERE cik = ?", [cik])
    tickers = companies["tickers"][0].to_list()
    stats = read_sql(con, "SELECT * FROM price_stats WHERE list_contains(?, ticker)", [tickers])
    side = load_side_inputs(con, Paths.from_settings(), companies)
    out = run_metrics(
        side["companies"], fin, stats, side["splits"],
        as_of_fundamentals=side["as_of_fundamentals"], as_of_prices=side["as_of_prices"],
        share_classes=load_share_classes(), registry=reg, params=params,
        concepts=load_concepts(), flag_cfg=load_rules(),
    )  # fmt: skip
    try:
        m, lines, value, code, msg = explain(metric_id, out.frame, fin, reg, params)
    except KeyError:
        console.print(f"[red]error:[/red] unknown metric {metric_id!r}")
        raise typer.Exit(2) from None
    r = out.frame.row(0, named=True)
    console.print(f"[bold]{m.name}[/bold] ({m.id}) · {m.category.value} · {m.unit.value} · "
                  f"basis {m.basis.value} · {m.tier.value} tier")  # fmt: skip
    console.print(f"[bold]Formula:[/bold] {m.definition}")
    console.print(f"{r['name']} ({r['primary_ticker']}, CIK {cik}) · TTM end {r['ttm_end']} · "
                  f"balance sheet {r['mrq_end']} (year ago {r['mrq_1y_end']})")  # fmt: skip
    table = Table(show_lines=False)
    for col in ("input", "value", "period", "source (tag · accession)"):
        table.add_column(col, justify="right" if col == "value" else "left")
    for ln in lines:
        src = ln.source + (f" [yellow]{ln.note}[/yellow]" if ln.note else "")
        table.add_row(ln.label, fmt_value(ln.value), ln.period, src)
    console.print(table)
    stored = read_sql(con, f"SELECT {metric_id} AS v FROM metrics_snapshot WHERE cik = ?", [cik])
    console.print(f"[bold]Result:[/bold] {fmt_value(value, m.unit)}  {_note(code, msg)}")
    if stored.height and stored["v"][0] != value and not (stored["v"][0] is None and value is None):
        console.print(f"[red]stored snapshot value differs: {stored['v'][0]}[/red]")


@app.callback(invoke_without_command=True)
def metrics(
    ticker: str = typer.Argument(..., help="e.g. AAPL or BRK.B"),
    *,
    category: Category | None = typer.Option(None, "--category", help="Only this category."),
    explain_id: str | None = typer.Option(None, "--explain", help="Explain one metric id."),
    db: Path | None = typer.Option(None, "--db", help="Build DuckDB (default: current build)."),
) -> None:
    """Metrics for a ticker from a build, or --explain one of them."""
    with open_build(db) as con:
        cik = _cik(con, ticker)
        if explain_id is not None:
            show_explain(con, cik, explain_id)
        else:
            show(con, cik, category)
