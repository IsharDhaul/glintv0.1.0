from typer.testing import CliRunner

from glint.cli import app

runner = CliRunner()

SUB_APPS = [
    "fixtures", "ingest", "universe", "price", "financials", "metrics",
    "screen", "refresh", "serve", "audit", "smoke",
]  # fmt: skip


def test_help_lists_all_sub_apps() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in SUB_APPS:
        assert name in result.output, name
