"""Presets (§2.8): one `config/presets/<id>.json` per preset, validated at startup.

A preset must parse as `Preset` (with `id` = the file stem), reference only known **P0**
metrics with suitable comparators, and pass engine validation. Liveness isn't checked here:
P0 metrics go live as WT-06 lands them, and a run on a build where one isn't live yet fails
with INVALID_SCREEN like any other screen.
"""

import json
import re
from pathlib import Path

from pydantic import ValidationError

from glint.contracts.api import Preset
from glint.contracts.enums import Priority
from glint.contracts.metrics import MetricRegistry, load_registry
from glint.contracts.screen import CATEGORICAL_FIELDS, SPECIAL_COLUMNS, Group, Screen
from glint.core.errors import ContractError
from glint.core.settings import REPO_ROOT
from glint.screen.validate import InvalidScreenError, check_screen

PRESETS_DIR = REPO_ROOT / "config" / "presets"
PRESET_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _metric_refs(screen: Screen) -> list[str]:
    def walk(group: Group) -> list[str]:
        return [c.metric for c in group.conditions()]

    refs = walk(screen.filters) + list(screen.columns)
    if screen.rank is not None:
        refs += [f.metric for f in screen.rank.factors]
    if screen.sort is not None:
        refs += [k.by for k in screen.sort.all_keys()]
    return [r for r in refs if r not in CATEGORICAL_FIELDS and r not in SPECIAL_COLUMNS]


def load_preset(path: Path, registry: MetricRegistry) -> Preset:
    preset_id = path.stem
    if not PRESET_ID_RE.match(preset_id):
        raise ContractError(f"{path.name}: preset ids are kebab-case")
    try:
        raw = json.loads(path.read_text())
        preset = Preset.model_validate({**raw, "id": preset_id})
    except (ValueError, ValidationError) as exc:
        raise ContractError(f"{path.name}: {exc}") from exc
    all_live = MetricRegistry(list(registry), treat_all_as_live=True)
    try:
        check_screen(preset.screen, all_live)
    except InvalidScreenError as exc:
        raise ContractError(f"{path.name}: {exc.message}") from exc
    not_p0 = sorted(
        {
            m
            for m in _metric_refs(preset.screen)
            if (d := registry.get(m)) and d.priority != Priority.P0
        }
    )
    if not_p0:
        raise ContractError(f"{path.name}: presets may use only P0 metrics, not {not_p0}")
    return preset


def load_presets(
    registry: MetricRegistry | None = None, presets_dir: Path = PRESETS_DIR
) -> dict[str, Preset]:
    """Every preset in `presets_dir`, by id, in file-name order. Raises on the first bad one."""
    registry = registry or load_registry()
    return {p.stem: load_preset(p, registry) for p in sorted(presets_dir.glob("*.json"))}
