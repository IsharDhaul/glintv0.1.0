"""`glint fixtures`: real trimmed SEC fixtures and the synthetic build (WT-00)."""

import asyncio
import tempfile
from pathlib import Path

import typer

from glint.core.errors import GlintError
from glint.core.http import SecGateway
from glint.core.log import configure_logging
from glint.core.paths import Paths
from glint.fixtures import sec as sec_fixtures
from glint.fixtures import synthetic as synthetic_fixtures

app = typer.Typer(help="Real trimmed SEC fixtures and the synthetic build.", no_args_is_help=True)


@app.command()
def sec(
    out: Path = typer.Option(sec_fixtures.FIXTURE_DIR, help="Where to write the fixtures."),
) -> None:
    """Fetch and trim companyfacts + submissions for the Appendix D tickers (network: SEC)."""
    configure_logging()

    async def run() -> tuple[int, list[str], list[str]]:
        with tempfile.TemporaryDirectory() as work:
            async with SecGateway() as gateway:
                fixtures, tickers_doc, picks = await sec_fixtures.build_fixtures(
                    gateway, Path(work)
                )
        total = sec_fixtures.write_fixtures(fixtures, tickers_doc, picks, out)
        return total, [f.ticker for f in fixtures], picks

    try:
        total, tickers, picks = asyncio.run(run())
    except GlintError as exc:
        typer.echo(f"error: {exc.message}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"wrote {len(tickers)} fixtures ({total / 1e6:.1f} MB) to {out}")
    typer.echo("tickers: " + ", ".join(tickers))
    for p in picks:
        typer.echo(f"pick: {p}")


@app.command()
def synthetic(
    n: int = typer.Option(6000, "--n", min=1, help="Number of synthetic companies."),
    seed: int = typer.Option(7, help="Random seed (same seed, same build)."),
    mocks: bool = typer.Option(True, help="Also export web/mocks/{meta,metrics,companies}.json."),
) -> None:
    """Build data/builds/synthetic.duckdb, point data/current.json at it, export web mocks."""
    configure_logging()
    paths = Paths.from_settings()
    db_path, build = synthetic_fixtures.run(
        n, seed, paths, synthetic_fixtures.MOCKS_DIR if mocks else None
    )
    nulls = sum(v is None for row in build.values for v in row.values())
    cells = sum(len(row) for row in build.values)
    typer.echo(f"wrote {n:,} synthetic companies (seed {seed}) to {db_path}")
    typer.echo(
        f"null cells: {nulls:,} / {cells:,} ({nulls / cells:.1%}), every one with a reason code"
    )
    typer.echo(f"current.json -> {paths.current_pointer}")
    if mocks:
        typer.echo(f"mocks -> {synthetic_fixtures.MOCKS_DIR}")
