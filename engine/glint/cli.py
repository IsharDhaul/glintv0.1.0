"""The `glint` CLI. Every sub-app is pre-registered here (WT-00); worktrees fill in their own
module and never edit this file."""

import typer

from glint.api import cli as api_cli
from glint.core.settings import ForeignCheckoutError, check_checkout
from glint.financials import cli as financials_cli
from glint.fixtures import cli as fixtures_cli
from glint.ingest import cli as ingest_cli
from glint.ingest.prices import price_cli
from glint.metrics import cli as metrics_cli
from glint.pipeline import cli as pipeline_cli
from glint.quality import cli as quality_cli
from glint.screen import cli as screen_cli
from glint.smoke import cli as smoke_cli
from glint.universe import cli as universe_cli

app = typer.Typer(
    name="glint",
    help="Glint: fundamentals-first US stock screener. Educational tool. Not investment advice.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def _main() -> None:
    try:
        check_checkout()
    except ForeignCheckoutError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None


app.add_typer(fixtures_cli.app, name="fixtures")
app.add_typer(ingest_cli.app, name="ingest")
app.add_typer(universe_cli.app, name="universe")
app.add_typer(price_cli.app, name="price")
app.add_typer(financials_cli.app, name="financials")
app.add_typer(metrics_cli.app, name="metrics")
app.add_typer(screen_cli.app, name="screen")
app.add_typer(pipeline_cli.app, name="refresh")
app.add_typer(api_cli.app, name="serve")
app.add_typer(quality_cli.app, name="audit")
app.add_typer(smoke_cli.app, name="smoke")
