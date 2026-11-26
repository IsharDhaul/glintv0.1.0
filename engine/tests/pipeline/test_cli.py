"""`glint refresh` CLI, on temp dirs only (the `db_dir` fixture points settings at tmp)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import glint.pipeline.cli
from glint.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _keep_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """configure_logging would bind the glint logger to CliRunner's (soon closed) stderr."""
    monkeypatch.setattr(glint.pipeline.cli, "configure_logging", lambda: None)


def test_dry_run_on_empty_dirs_writes_nothing(db_dir: Path) -> None:
    result = runner.invoke(app, ["refresh", "--dry-run", "--no-download"])
    assert result.exit_code == 0, result.output
    assert "would fail: no completed SEC download" in result.output
    assert "nothing was downloaded or written" in result.output
    assert not db_dir.exists()


def test_unknown_stage_is_an_error(db_dir: Path) -> None:
    result = runner.invoke(app, ["refresh", "--only", "nope", "--dry-run"])
    assert result.exit_code == 1
    assert "unknown stage" in result.output


def test_failure_names_the_stage_and_log_and_exits_1(db_dir: Path) -> None:
    result = runner.invoke(app, ["refresh", "--no-download"])
    assert result.exit_code == 1, result.output
    assert "refresh failed in stage extract_facts" in result.output
    assert "log:" in result.output and "current build unchanged: none" in result.output
    assert not (db_dir / "current.json").exists()
