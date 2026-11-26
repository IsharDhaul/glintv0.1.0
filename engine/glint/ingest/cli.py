"""`glint ingest`: wiring only. Each source's commands live in its own package."""

import typer

from glint.ingest.prices import cli as prices_cli
from glint.ingest.sec import cli as sec_cli

app = typer.Typer(help="Download raw data (SEC bulk files, price bars).", no_args_is_help=True)
app.add_typer(sec_cli.app, name="sec")
app.add_typer(prices_cli.app, name="prices")
