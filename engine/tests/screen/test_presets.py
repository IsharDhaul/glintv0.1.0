import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from glint.contracts.metrics import MetricRegistry
from glint.core.errors import ContractError
from glint.screen.engine import run_screen
from glint.screen.presets import load_presets

STARTERS = {"magic-formula", "quality-compounders", "dilution-watch"}


def test_starter_presets_validate(strict_registry: MetricRegistry) -> None:
    presets = load_presets(strict_registry)  # real statuses: liveness isn't a load-time rule
    assert set(presets) >= STARTERS
    for pid, p in presets.items():
        assert p.id == pid and p.name and p.summary and p.how_to_read and p.source


@pytest.mark.parametrize("preset_id", sorted(STARTERS))
def test_starter_presets_run_on_synthetic(
    preset_id: str, synthetic_db: Path, live_registry: MetricRegistry
) -> None:
    preset = load_presets(live_registry)[preset_id]
    with duckdb.connect(str(synthetic_db), read_only=True) as con:
        r = run_screen(con, preset.screen, live_registry).response
    assert 0 < r.total <= r.universe_count  # magic-formula ranks the whole universe
    assert r.warnings == []
    if preset.screen.rank is not None:
        assert r.results[0].rank == 1


def _write(d: Path, name: str, screen: dict[str, object]) -> None:
    doc = {
        "name": "X",
        "summary": "x",
        "kind": "screen",
        "how_to_read": "x",
        "source": "x",
        "screen": screen,
    }
    (d / name).write_text(json.dumps(doc))


def test_bad_presets_are_rejected(tmp_path: Path, strict_registry: MetricRegistry) -> None:
    roic = {"metric": "roic", "cmp": "gte", "value": 0.1}
    _write(tmp_path, "Bad_Name.json", {"filters": {"op": "and", "children": [roic]}})
    with pytest.raises(ContractError, match="kebab-case"):
        load_presets(strict_registry, tmp_path)

    (tmp_path / "Bad_Name.json").unlink()
    _write(tmp_path, "p1.json", {"filters": {"op": "and", "children": [
        {"metric": "quick_ratio", "cmp": "gte", "value": 1}]}})  # fmt: skip
    with pytest.raises(ContractError, match="only P0"):
        load_presets(strict_registry, tmp_path)

    _write(tmp_path, "p1.json", {"filters": {"op": "and", "children": [
        {"metric": "nope", "cmp": "gte", "value": 1}]}})  # fmt: skip
    with pytest.raises(ContractError, match="unknown metric"):
        load_presets(strict_registry, tmp_path)

    _write(tmp_path, "p1.json", {"limit": 5000})
    with pytest.raises(ContractError, match=r"p1\.json"):
        load_presets(strict_registry, tmp_path)


def test_kind_is_required_and_misses_default_empty(
    tmp_path: Path, strict_registry: MetricRegistry
) -> None:
    doc: dict[str, Any] = {
        "name": "X",
        "summary": "x",
        "how_to_read": "x",
        "source": "x",
        "screen": {},
    }
    (tmp_path / "p1.json").write_text(json.dumps(doc))
    with pytest.raises(ContractError, match="kind"):
        load_presets(strict_registry, tmp_path)
    (tmp_path / "p1.json").write_text(json.dumps({**doc, "kind": "red_flags"}))
    p = load_presets(strict_registry, tmp_path)["p1"]
    assert p.kind == "red_flags" and p.misses == []
