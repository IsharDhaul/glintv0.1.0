"""`glint screen <file.json|preset-id> [--synthetic] [--explain]` (WT-04): run a screen in the
terminal and print the funnel, the top results and the near misses."""

import json
from pathlib import Path
from typing import Annotated

import duckdb
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from glint.api.build import build_db_path, connect_read_only, read_pointer
from glint.contracts.api import CellValue, ScreenResponse
from glint.contracts.enums import NOTE_DISPLAY, Unit
from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import CATEGORICAL_FIELDS, Screen
from glint.core.errors import ContractError
from glint.core.paths import Paths
from glint.fixtures.synthetic import BUILD_ID as SYNTHETIC_BUILD_ID
from glint.screen.engine import RANK_SCORE, registry_for_build, run_screen
from glint.screen.labels import format_value
from glint.screen.presets import load_presets
from glint.screen.validate import InvalidScreenError

app = typer.Typer(
    help="Run a screen (preset id or JSON file) in the terminal.",
    context_settings={"allow_interspersed_args": True},  # `glint screen x --explain`
)
console = Console(width=140)


def _load_screen(target: str, registry: MetricRegistry) -> Screen:
    path = Path(target)
    if path.suffix == ".json" or path.exists():
        try:
            return Screen.model_validate(json.loads(path.read_text()))
        except (OSError, ValueError, ValidationError) as exc:
            raise ContractError(f"{target}: {exc}") from exc
    presets = load_presets(registry)
    if target not in presets:
        raise ContractError(f"no preset {target!r}; presets: {', '.join(presets)}")
    return presets[target].screen


def _open_build(synthetic: bool) -> duckdb.DuckDBPyConnection:
    paths = Paths.from_settings()
    if synthetic:
        db = paths.build_db(SYNTHETIC_BUILD_ID)
        if not db.exists():
            raise ContractError("no synthetic build: run `glint fixtures synthetic`")
        return connect_read_only(db)
    pointer = read_pointer(paths)
    if pointer is None:
        raise ContractError("no build yet: run `glint refresh` or use --synthetic")
    return connect_read_only(build_db_path(pointer, paths))


def _cell(value: CellValue, column: str, registry: MetricRegistry) -> str:
    if column == RANK_SCORE:
        return "—" if value is None else f"{value:.4g}" if isinstance(value, float) else str(value)
    if column in CATEGORICAL_FIELDS:
        return "—" if value is None else str(value)
    m = registry.get(column)
    return format_value(value, m.unit if m else Unit.SCORE)


def _print(r: ScreenResponse, screen: Screen, registry: MetricRegistry, show: int) -> None:
    synthetic = " (SYNTHETIC: not real data)" if r.build_id == SYNTHETIC_BUILD_ID else ""
    console.print(f"[bold]{screen.name}[/] · build {r.build_id}{synthetic}")
    console.print(f"As of: fundamentals {r.as_of.fundamentals} · prices {r.as_of.prices}")
    for w in r.warnings:
        console.print(f"[yellow]warning:[/] {w}")

    funnel = Table(title="Funnel")
    for col in ("#", "step", "remaining", "removed", "of which missing data"):
        funnel.add_column(col, justify="left" if col == "step" else "right")
    for f in r.funnel:
        label = f"[bold red]{f.label} ← binding[/]" if f.binding else f.label
        funnel.add_row(
            str(f.index), label, f"{f.remaining:,}", f"{f.removed:,}", f"{f.removed_missing:,}"
        )
    console.print(funnel)

    shown = r.results[:show]
    results = Table(title=f"Results: {r.total:,} match · showing {len(shown)}")
    ranked = screen.rank is not None
    if ranked:
        results.add_column("rank", justify="right")
    columns = list(screen.columns)
    for col in columns:
        results.add_column(col, justify="left" if col in CATEGORICAL_FIELDS else "right")
    for row in shown:
        cells: list[str] = [str(row.rank) if row.rank is not None else "—"] if ranked else []
        for col in columns:
            value = row.values.get(col)
            note = row.notes.get(col)
            text = _cell(value, col, registry)
            if value is None and note is not None:
                text = f"{NOTE_DISPLAY[note.code].value} {note.code.value}"
            cells.append(text)
        results.add_row(*cells)
    console.print(results)
    if ranked and shown and shown[0].factor_contributions:
        top = shown[0]
        parts = ", ".join(
            f"{k} {v:.3f}" if v is not None else f"{k} —"
            for k, v in top.factor_contributions.items()
        )
        console.print(f"Top result {top.ticker}: factor contributions {parts}")

    if screen.near_misses:
        near = Table(title=f"Near misses (failed exactly one filter): {len(r.near_misses)}")
        for col in ("ticker", "failed filter", "metric", "value", "threshold", "distance"):
            near.add_column(col, justify="right" if col == "distance" else "left")
        for nm in r.near_misses:
            near.add_row(
                nm.ticker,
                nm.failed_label,
                nm.metric,
                _near_value(nm.value, nm.metric, nm.cmp.value, registry),
                _near_value(nm.threshold, nm.metric, nm.cmp.value, registry),
                "—" if nm.distance is None else f"{nm.distance:.3f}",
            )
        console.print(near)


def _near_value(
    value: CellValue | list[CellValue], metric: str, cmp: str, registry: MetricRegistry
) -> str:
    if cmp.startswith("pct_rank"):
        return f"pctile {value:.2f}" if isinstance(value, float) else "—"
    if isinstance(value, list):
        return " – ".join(_near_value(v, metric, cmp, registry) for v in value)
    m = registry.get(metric)
    # Near misses sit close to the threshold: one decimal would print "10.0% vs 10.0%".
    if isinstance(value, float) and m is not None and m.unit is Unit.FRAC:
        return f"{value * 100:.2f}%"
    if isinstance(value, float) and m is not None and m.unit is Unit.PP:
        return f"{value * 100:+.2f} pp"
    if isinstance(value, float) and m is not None and m.unit is Unit.X:
        return f"{value:.2f}x"
    return _cell(value, metric, registry)


@app.callback(invoke_without_command=True)
def screen_cmd(
    target: Annotated[str, typer.Argument(help="Preset id (e.g. magic-formula) or a .json file")],
    synthetic: Annotated[
        bool, typer.Option("--synthetic", help="Run on the synthetic build (data/builds).")
    ] = False,
    explain: Annotated[
        bool, typer.Option("--explain", help="Also print the SQL and its bound parameters.")
    ] = False,
    show: Annotated[int, typer.Option(min=1, help="How many result rows to print.")] = 20,
) -> None:
    """Run a screen and print the funnel, top results and near misses."""
    try:
        con = _open_build(synthetic)
        with con:
            registry = registry_for_build(con)
            screen = _load_screen(target, registry)
            run = run_screen(con, screen, registry)
    except InvalidScreenError as exc:
        for issue in exc.issues:
            where = ".".join(str(p) for p in issue.path)
            typer.echo(f"invalid screen: {where}: {issue.message}", err=True)
        raise typer.Exit(1) from exc
    except ContractError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(1) from exc

    _print(run.response, screen, registry, show)
    if explain:
        c = run.compiled
        for title, query_sql in (
            ("SQL 1/3: universe counts", c.counts_sql),
            ("SQL 2/3: passing rows + near-miss candidates, with funnel counts", c.rows_sql),
            ("SQL 3/3: requested columns for the result page ($ciks)", c.page_sql),
        ):
            console.rule(title)
            console.print(query_sql, markup=False, highlight=False)
        console.rule("Bound parameters")
        for name, value in c.params.items():
            console.print(f"${name} = {value!r}", markup=False, highlight=False)
