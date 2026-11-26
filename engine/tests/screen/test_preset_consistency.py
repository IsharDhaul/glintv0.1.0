"""WT-10 consistency: the 12 presets of SPEC §2.8 exist, validate, use only live P0 metrics,
run on the synthetic build, and never claim returns."""

import json
import re
from pathlib import Path

import duckdb
import pytest

from glint.contracts.api import PresetKind
from glint.contracts.enums import MetricStatus, Priority, Unit
from glint.contracts.metrics import MetricRegistry, load_registry
from glint.contracts.screen import Comparator, Condition, Screen
from glint.screen.engine import run_screen
from glint.screen.presets import PRESETS_DIR, load_presets

SPEC_PRESETS = {
    "magic-formula",
    "piotroski-value",
    "quality-compounders",
    "qarp",
    "net-nets",
    "shareholder-yield",
    "cash-rich-smallcaps",
    "margin-inflection",
    "rule-of-40",
    "dividend-durability",
    "dilution-watch",
    "accruals-risk",
}
RETURNS_LANGUAGE = re.compile(r"outperform|beat the market|returns of", re.IGNORECASE)


def metric_refs(screen: Screen, registry: MetricRegistry) -> set[str]:
    """Every registry metric a screen filters, ranks, sorts or shows."""
    refs = {c.metric for c in screen.filters.conditions()} | set(screen.columns)
    if screen.rank is not None:
        refs |= {f.metric for f in screen.rank.factors}
    if screen.sort is not None:
        refs |= {k.by for k in screen.sort.all_keys()}
    return {r for r in refs if registry.get(r) is not None}


def test_exactly_the_spec_presets() -> None:
    assert {p.stem for p in PRESETS_DIR.glob("*.json")} == SPEC_PRESETS


def test_every_preset_metric_exists_is_live_and_p0() -> None:
    registry = load_registry()  # real statuses
    for pid, preset in load_presets(registry).items():
        refs = metric_refs(preset.screen, registry)
        filtered = {c.metric for c in preset.screen.filters.conditions()}
        assert filtered <= refs, f"{pid}: unknown filter metric {filtered - refs}"
        for ref in refs:
            m = registry.get(ref)
            assert m is not None
            assert m.status is MetricStatus.LIVE, f"{pid}: {ref} is not live"
            assert m.priority is Priority.P0, f"{pid}: {ref} is not P0"


def test_every_preset_has_source_and_how_to_read() -> None:
    for pid, p in load_presets().items():
        assert p.summary.strip() and p.source.strip(), pid
        assert len(p.how_to_read) >= 200, f"{pid}: how_to_read should say what it finds"
        assert all(m.strip() and m == m.strip() for m in p.misses), f"{pid}: blank misses line"


RED_FLAG_PRESETS = {"accruals-risk", "dilution-watch"}


def test_red_flag_presets_say_so() -> None:
    """`kind` is the field the UI groups by; the name and copy must agree with it."""
    for pid, p in load_presets().items():
        red = p.kind is PresetKind.RED_FLAGS
        assert red == (pid in RED_FLAG_PRESETS), pid
        assert red == p.name.endswith("(red flags)"), pid
        assert red == p.how_to_read.startswith("A risk screen, not a buy list."), pid


@pytest.mark.parametrize("path", sorted(PRESETS_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_no_returns_language(path: Path) -> None:
    assert not RETURNS_LANGUAGE.search(path.read_text()), path.name


def test_glints_differences_from_source_are_stated() -> None:
    presets = load_presets()
    assert "debt paydown" in presets["shareholder-yield"].how_to_read
    assert "debt paydown" in presets["shareholder-yield"].source
    assert "short list" in presets["net-nets"].summary.lower()
    magic = presets["magic-formula"].how_to_read
    assert "excess cash" in magic and "short-term debt" in magic  # Greenblatt ROC as in §2.4
    assert "FCF margin" in presets["rule-of-40"].how_to_read
    assert "cheapest fifth" in presets["piotroski-value"].how_to_read


def _usd(v: float) -> str:
    return f"${v / 1e9:g}B" if v >= 1e9 else f"${v / 1e6:g}M"


def _phrases(cond: Condition, unit: Unit) -> list[str]:
    """Ways the copy may state a threshold. Empty: nothing to check (zero, bool)."""
    v = cond.value
    if isinstance(v, bool) or not isinstance(v, int | float) or v == 0:
        return []
    if cond.cmp is Comparator.PCT_RANK_LTE:
        return [f"cheapest {v * 100:g}%"]
    if cond.cmp is Comparator.PCT_RANK_GTE:
        return [f"top {(1 - v) * 100:g}%"]
    if unit is Unit.PP:
        return [f"{v * 100:g} percentage points"]
    if unit is Unit.FRAC:
        return [f"{v * 100:g}%", f"{v:g}×"]
    if unit is Unit.USD:
        return [_usd(v)]
    if unit is Unit.X:
        return [f"{v:g}×", *(["half"] if v == 0.5 else [])]
    return [f"at least {v:g}"]


@pytest.mark.parametrize("preset_id", sorted(SPEC_PRESETS))
def test_how_to_read_states_the_actual_thresholds(preset_id: str) -> None:
    """Every threshold in the screen appears in the copy, so text and JSON can't drift apart."""
    registry = load_registry()
    preset = load_presets(registry)[preset_id]
    text = preset.how_to_read
    for cond in preset.screen.filters.conditions():
        m = registry.get(cond.metric)
        assert m is not None
        phrases = _phrases(cond, m.unit)
        assert not phrases or any(p in text for p in phrases), (
            f"{preset_id}: {cond.metric} {cond.cmp.value} {cond.value} not stated (want {phrases})"
        )
    u = preset.screen.universe
    for bound in (u.market_cap_min, u.market_cap_max):
        if bound is not None:
            assert _usd(bound) in text, f"{preset_id}: market-cap bound {_usd(bound)} not stated"


@pytest.mark.parametrize("preset_id", sorted(SPEC_PRESETS))
def test_every_preset_runs_on_synthetic(
    preset_id: str, synthetic_db: Path, live_registry: MetricRegistry
) -> None:
    preset = load_presets(live_registry)[preset_id]
    with duckdb.connect(str(synthetic_db), read_only=True) as con:
        r = run_screen(con, preset.screen, live_registry).response
    assert r.total <= r.universe_count
    assert r.warnings == []
    json.dumps(r.model_dump(mode="json"))  # serialises as the API would send it
