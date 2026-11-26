"""Screen-engine settings read from `config/thresholds.yaml` (principle 8: never in code)."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from glint.core.settings import REPO_ROOT

THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"


@dataclass(frozen=True)
class ScreenConfig:
    float_tolerance: float
    small_peer_group_min: int


@cache
def load_screen_config(path: Path = THRESHOLDS_PATH) -> ScreenConfig:
    doc = yaml.safe_load(path.read_text())
    return ScreenConfig(
        float_tolerance=float(doc["float_tolerance"]),
        small_peer_group_min=int(doc["metrics"]["small_peer_group_min"]),
    )
