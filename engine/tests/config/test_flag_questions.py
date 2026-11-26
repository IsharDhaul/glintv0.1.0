"""Flag questions follow their thresholds (principle 8): `{key}` placeholders are filled from the
flag's own keys, and the stale flag and the universe's stale exclusion share one number."""

import pytest
import yaml

from glint.flags.engine import load_rules, render_question
from glint.metrics.params import THRESHOLDS_PATH, load_params


def test_every_question_renders_with_its_own_numbers() -> None:
    rules = load_rules()
    for flag_id, block in rules.items():
        q = block["question"]
        assert "{" not in q.replace("{x}", ""), f"{flag_id}: unfilled placeholder in {q!r}"
    assert "less than 2 times" in rules["thin_coverage"]["question"]
    assert "15% or more of revenue" in rules["heavy_sbc"]["question"]
    assert "50% or more of assets" in rules["goodwill_heavy"]["question"]
    assert "over 15 months old" in rules["stale_filing"]["question"]
    assert "last 20 sessions" in rules["market_cap_implausible"]["question"]
    assert "{x}" in rules["dilution"]["question"]  # filled per company from the evidence


def test_a_threshold_change_changes_the_question() -> None:
    block = {"sbc_to_revenue_gte": 0.2, "question": "Stock comp is {sbc_to_revenue_gte:.0%}."}
    assert render_question(block) == "Stock comp is 20%."


def test_a_misspelled_placeholder_fails_loudly() -> None:
    with pytest.raises(KeyError, match="sbc_to_revenue"):
        render_question({"sbc_to_revenue_gte": 0.15, "question": "{sbc_to_revenue:.0%}"})


def test_stale_flag_and_universe_use_one_number() -> None:
    raw = yaml.safe_load(THRESHOLDS_PATH.read_text())
    assert "annual_report_age_months_gt" not in raw["flags"]["stale_filing"]  # one key only
    months = raw["freshness"]["stale_annual_report_months"]
    assert load_rules()["stale_filing"]["annual_report_age_months_gt"] == months
    assert load_params().stale_annual_report_months == months
