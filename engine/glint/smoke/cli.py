"""`glint smoke [--expectations FILE] [--perf]` (WT-09 steps 4 and 6): presets, Appendix D
company lookups and search cases on the current build, through the API in-process (no server,
no network); `--perf` also times the §5.10 API budgets. Exits 1 on any failure."""

# Starlette's TestClient is untyped without the optional httpx2 package.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from pathlib import Path

import typer
from fastapi.testclient import TestClient
from rich.console import Console
from rich.table import Table

from glint.api.app import create_app
from glint.contracts.metrics import load_registry
from glint.smoke.checks import EXPECTATIONS_FILE, check_perf, load_expectations, run_smoke

app = typer.Typer(help="Presets and company lookups on a real build.")
console = Console()


@app.callback(invoke_without_command=True)
def smoke(
    *,
    expectations: Path = typer.Option(
        EXPECTATIONS_FILE, "--expectations", help="Expected kinds, null reasons, search hits."
    ),
    perf: bool = typer.Option(False, "--perf", help="Also time the §5.10 API budgets."),
) -> None:
    """Every preset, every Appendix D company and the search cases; non-zero exit on a failure."""
    with TestClient(create_app()) as client:
        want = load_expectations(expectations)
        checks = run_smoke(client, want, load_registry())
        if perf:
            checks += check_perf(client, want.perf, list(want.companies))

    table = Table(title="glint smoke")
    for col in ("", "group", "check", "detail"):
        table.add_column(col)
    for c in checks:
        mark = "[green]ok[/green]" if c.ok else "[red]FAIL[/red]"
        table.add_row(mark, c.group, c.name, c.detail if c.ok else "; ".join(c.problems))
    console.print(table)

    failed = [c for c in checks if not c.ok]
    console.print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        raise typer.Exit(1)
