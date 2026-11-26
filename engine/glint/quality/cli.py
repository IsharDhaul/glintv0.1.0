"""`glint audit [--db PATH] [--top N] [--extremes N]` (WT-06 step 11): outliers to review on a
build, over the default universe (§2.3). Recomputes with the stage's functions (read-only), so
every hit can show the inputs behind it. Never changes a value."""

from pathlib import Path
from typing import Any

import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from glint.contracts.enums import DEFAULT_EXCHANGES, FINANCIAL_SECTORS, Kind, Priority, Unit
from glint.contracts.metrics import load_registry
from glint.core.paths import Paths
from glint.financials.concepts import load_concepts
from glint.flags.engine import load_rules
from glint.metrics.cli import open_build
from glint.metrics.explain import fmt_value
from glint.metrics.params import load_params, load_thresholds
from glint.metrics.share_classes import load_share_classes
from glint.metrics.stage import load_inputs, run_metrics
from glint.quality.audit import distribution, extremes, null_rates, rule_outliers

app = typer.Typer(help="Distribution and outlier checks on a build.")
console = Console()


def default_universe(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(
        pl.col("exchange").is_in([e.value for e in DEFAULT_EXCHANGES])
        & (pl.col("kind") == Kind.OPERATING.value)
        & pl.col("has_facts")
    )


def domestic_non_financial(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(
        ~pl.col("is_foreign_filer") & ~pl.col("sector").is_in([s.value for s in FINANCIAL_SECTORS])
    )


def _cell(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.4g}" if abs(v) < 1e5 else f"{v / 1e6:,.1f}M"
    return "—" if v is None else str(v)


def _print_frame(title: str, df: pl.DataFrame) -> None:
    table = Table(title=title)
    for c in df.columns:
        table.add_column(c)
    for row in df.iter_rows():
        table.add_row(*(_cell(v) for v in row))
    console.print(table)


@app.callback(invoke_without_command=True)
def audit(
    *,
    db: Path | None = typer.Option(None, "--db", help="Build DuckDB (default: current build)."),
    top: int = typer.Option(10, "--top", min=1, help="Hits shown per rule."),
    extremes_n: int = typer.Option(3, "--extremes", min=0, help="Extreme values per metric."),
) -> None:
    """§4.6 rules, per-metric distributions and P0 null rates for the default universe."""
    reg = load_registry()
    with open_build(db) as con:
        inputs = load_inputs(con, Paths.from_settings())
    out = run_metrics(
        **inputs, share_classes=load_share_classes(), registry=reg, params=load_params(),
        concepts=load_concepts(), flag_cfg=load_rules(),
    )  # fmt: skip
    frame = default_universe(out.frame)
    console.print(f"[bold]Default universe:[/bold] {frame.height:,} companies "
                  f"(of {out.frame.height:,} in the build)")  # fmt: skip

    for rule, hits in rule_outliers(
        frame, inputs["fin"], inputs["splits"], load_thresholds()["audit"], top=top
    ).items():
        _print_frame(f"rule {rule}: {hits.height} shown (top {top})", hits)

    numeric = [m for m in reg.live() if m.unit is not Unit.BOOL]
    dist = distribution(frame, [m.id for m in numeric])
    keep = ["metric_id", "n", "p1", "p5", "p50", "p95", "p99", "null_share"]
    reasons = [c for c in dist.columns if c.startswith("null_") and c != "null_share"]
    dist = dist.with_columns(
        pl.concat_str(
            [pl.when(pl.col(c) > 0).then(pl.format(f"{c[5:]} {{}}", (pl.col(c) * 100).round(1)))
             for c in reasons], separator=" ", ignore_nulls=True,
        ).alias("null % by reason")
    )  # fmt: skip
    _print_frame("distribution (default universe)", dist.select(*keep, "null % by reason"))

    if extremes_n:
        for m in numeric:
            ex = extremes(frame, m.id, extremes_n)
            if ex.height:
                vals = ", ".join(
                    f"{r['primary_ticker']} {fmt_value(r[m.id], m.unit)}"
                    for r in ex.iter_rows(named=True)
                )
                console.print(f"[dim]extremes {m.id}:[/dim] {vals}")

    dom = domestic_non_financial(frame)
    p0 = [m.id for m in reg.live() if m.priority is Priority.P0]
    rates = null_rates(dom, p0)
    _print_frame(f"P0 null rate, domestic non-financials (n={dom.height:,})", rates)
