"""Metric constants from `config/thresholds.yaml` (principle 8: thresholds live in config)."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from glint.core.settings import REPO_ROOT

THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"


@dataclass(frozen=True)
class Params:
    tax_rate_clamp: tuple[float, float] = (0.0, 0.35)
    statutory_tax_rate: float = 0.21
    dps_cut_tolerance: float = 0.01
    dps_years: int = 5
    price_stale_days: int = 7
    stale_annual_report_months: int = 15
    float_tolerance: float = 1e-9
    history_fy_points: int = 10
    history_ttm_points: int = 12
    split_confirm_tolerance: float = 0.02


def params_from(doc: dict[str, Any]) -> Params:
    m = doc["metrics"]
    lo, hi = m["roic_tax_rate_clamp"]
    return Params(
        tax_rate_clamp=(float(lo), float(hi)),
        statutory_tax_rate=float(m["roic_statutory_tax_rate"]),
        dps_cut_tolerance=float(m["dps_cut_tolerance"]),
        dps_years=int(m["dps_no_cut_years"]),
        price_stale_days=int(doc["freshness"]["price_stale_days"]),
        stale_annual_report_months=int(doc["freshness"]["stale_annual_report_months"]),
        float_tolerance=float(doc["float_tolerance"]),
        history_fy_points=int(m["history_points"]["fy"]),
        history_ttm_points=int(m["history_points"]["ttm"]),
        split_confirm_tolerance=float(m["split_confirm_tolerance"]),
    )


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


@cache
def load_params(path: Path = THRESHOLDS_PATH) -> Params:
    return params_from(load_thresholds(path))
