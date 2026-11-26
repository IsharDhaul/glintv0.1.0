"""The config registries parse and agree with the contracts."""

from typing import Any

import yaml

from glint.contracts.enums import FlagId, FlagSeverity, LineItem, Sector, Taxonomy
from glint.contracts.metrics import METRIC_ID_RE, load_registry
from glint.core.settings import REPO_ROOT

CONFIG = REPO_ROOT / "config"

# Every metric id in SPEC §2.4, transcribed independently of config/metrics.yaml.
SPEC_METRIC_IDS = """
price market_cap enterprise_value revenue_ttm avg_dollar_volume_3m
pe_ttm earnings_yield ev_ebit ebit_ev ev_ebitda ev_sales p_fcf fcf_yield pb dividend_yield
buyback_yield shareholder_yield ncav_to_mcap
gross_margin operating_margin ebitda_margin net_margin fcf_margin roe roa roic greenblatt_roc
cash_conversion sbc_to_revenue fcf_after_sbc_margin
revenue_growth_yoy revenue_cagr_3y revenue_cagr_5y eps_growth_yoy ebit_growth_yoy fcf_growth_yoy
gross_margin_change_yoy operating_margin_change_yoy share_count_change_yoy rule_of_40
net_debt net_debt_to_ebitda debt_to_equity current_ratio quick_ratio interest_coverage altman_z
cash_to_mcap goodwill_to_assets
asset_turnover dso dio dpo cash_conversion_cycle capex_to_revenue capex_to_dna
piotroski_f accruals_ratio payout_ratio fcf_payout_ratio dps_no_cut_5y
return_1m return_3m return_6m return_12m momentum_12_1 pct_from_52w_high volatility_1y
data_coverage days_since_filing flag_count
""".split()

NON_LINE_ITEM_INPUTS = {"close", "volume", "filings", "flags"}


def load(name: str) -> Any:
    return yaml.safe_load((CONFIG / name).read_text())


def test_metrics_registry_matches_spec() -> None:
    reg = load_registry()
    ids = [m.id for m in reg]
    assert sorted(ids) == sorted(SPEC_METRIC_IDS)
    assert len(ids) == len(set(ids))
    assert all(METRIC_ID_RE.match(i) for i in ids)


def test_metric_inputs_are_known() -> None:
    reg = load_registry()
    known = {li.value for li in LineItem} | {m.id for m in reg} | NON_LINE_ITEM_INPUTS
    for m in reg:
        assert set(m.inputs) <= known, (m.id, set(m.inputs) - known)


def test_presets_use_only_p0_metrics_are_marked() -> None:
    # SPEC §2.8: every metric a preset names must be P0.
    preset_metrics = {
        "ebit_ev", "greenblatt_roc", "pb", "piotroski_f", "roic", "gross_margin",
        "revenue_cagr_3y", "net_debt_to_ebitda", "fcf_margin", "fcf_yield", "operating_margin",
        "ncav_to_mcap", "shareholder_yield", "cash_to_mcap", "operating_margin_change_yoy",
        "revenue_growth_yoy", "rule_of_40", "revenue_ttm", "dividend_yield", "fcf_payout_ratio",
        "dps_no_cut_5y", "share_count_change_yoy", "sbc_to_revenue", "accruals_ratio",
        "cash_conversion", "market_cap",
    }  # fmt: skip
    reg = load_registry()
    for mid in preset_metrics:
        m = reg.get(mid)
        assert m is not None and m.priority.value == "P0", mid


def test_concepts_cover_every_line_item() -> None:
    concepts = load("concepts.yaml")
    items = concepts["line_items"]
    assert set(items) == {li.value for li in LineItem}
    taxonomies = {t.value for t in Taxonomy}
    for name, spec in items.items():
        assert spec["kind"] in {"duration", "instant"}, name
        assert spec["unit"] in {"currency", "per_share", "shares"}, name
        assert set(spec["tags"]) <= taxonomies, name
        assert spec["tags"] or spec.get("derive"), name
    assert "EntityCommonStockSharesOutstanding" in concepts["dei_cover_tags"]


def test_sectors_map_to_known_sectors() -> None:
    sectors = load("sectors.yaml")
    names = {s.value for s in Sector}
    assert sectors["default"] in names
    for r in sectors["ranges"]:
        assert r["sector"] in names
        for lo, hi in r["sic"]:
            assert 100 <= lo <= hi <= 9999
    assert {k["kind"] for k in sectors["kinds"]} == {"fund", "spac"}


def test_thresholds_cover_every_flag() -> None:
    t = load("thresholds.yaml")
    assert t["float_tolerance"] == 1e-9
    assert set(t["flags"]) == {f.value for f in FlagId}
    assert all("?" in f["question"] for f in t["flags"].values())
    assert all(f["severity"] in {s.value for s in FlagSeverity} for f in t["flags"].values())


def test_empty_override_files_parse() -> None:
    overrides = load("sector_overrides.yaml")["overrides"]
    assert [o["ticker"] for o in overrides] == ["QVCG", "MELI", "NUTX", "EBAY", "ETSY", "PYPL"]
    assert all(o["reason"] for o in overrides)
    share_classes = load("share_classes.yaml")
    ciks = [c["cik"] for c in share_classes["companies"]]
    assert ciks == []  # BRK from its cover; HUBG, DUOL from cover + quote (`unlisted_economic`)
    confirmed = {e["ticker"] for e in share_classes["unlisted_economic"]}
    assert {"HUBG", "DUOL", "GOOGL"} <= confirmed
    excluded = share_classes["cover_excluded"]
    assert [e["ticker"] for e in excluded] == ["USCI", "YSAG", "ESBA", "SF", "TAP"]
    assert all(e["reason"] for e in excluded)
