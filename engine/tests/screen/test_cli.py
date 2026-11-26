import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from glint.cli import app
from glint.core.paths import Paths
from glint.fixtures import synthetic

runner = CliRunner()


@pytest.fixture
def built(db_dir: Path) -> Path:
    synthetic.run(400, 7, Paths.from_settings(), mocks_dir=None)
    return db_dir


def test_preset_on_synthetic(built: Path) -> None:
    r = runner.invoke(app, ["screen", "quality-compounders", "--synthetic", "--show", "5"])
    assert r.exit_code == 0, r.output
    assert "SYNTHETIC: not real data" in r.output
    assert "Funnel" in r.output and "binding" in r.output
    assert "Near misses" in r.output
    assert "SQL" not in r.output


def test_explain_prints_sql_and_params(built: Path) -> None:
    r = runner.invoke(app, ["screen", "magic-formula", "--synthetic", "--explain"])
    assert r.exit_code == 0, r.output
    assert "WITH u AS" in r.output
    assert "$p0 = " in r.output


def test_json_file_and_current_build(built: Path, tmp_path: Path) -> None:
    f = tmp_path / "s.json"
    f.write_text(
        json.dumps(
            {
                "filters": {
                    "op": "and",
                    "children": [{"metric": "roic", "cmp": "gte", "value": 15}],
                },
                "columns": ["ticker", "roic"],
            }
        )
    )
    r = runner.invoke(app, ["screen", str(f)])  # no --synthetic: follows current.json
    assert r.exit_code == 0, r.output
    assert "warning:" in r.output and "0.15" in r.output


def test_errors_exit_1(built: Path, tmp_path: Path) -> None:
    r = runner.invoke(app, ["screen", "no-such-preset", "--synthetic"])
    assert r.exit_code == 1
    assert "no preset 'no-such-preset'" in r.output

    f = tmp_path / "bad.json"
    f.write_text(
        json.dumps(
            {
                "filters": {
                    "op": "and",
                    "children": [{"metric": "roic; DROP TABLE", "cmp": "gte", "value": 1}],
                }
            }
        )
    )
    r = runner.invoke(app, ["screen", str(f), "--synthetic"])
    assert r.exit_code == 1
    assert "invalid screen: filters.children.0.metric: unknown metric" in r.output


def test_no_build(db_dir: Path) -> None:
    r = runner.invoke(app, ["screen", "magic-formula"])
    assert r.exit_code == 1
    assert "no build yet" in r.output
    r = runner.invoke(app, ["screen", "magic-formula", "--synthetic"])
    assert r.exit_code == 1
    assert "glint fixtures synthetic" in r.output
