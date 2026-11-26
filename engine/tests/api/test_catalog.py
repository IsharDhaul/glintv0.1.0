# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""meta, metrics, sectors, presets."""

from fastapi.testclient import TestClient

from glint.contracts.enums import Sector
from glint.contracts.metrics import MetricRegistry
from glint.metrics.params import load_params
from tests.api.conftest import SMALL_N


def test_meta_on_synthetic_build(client: TestClient) -> None:
    body = client.get("/api/meta").json()
    assert body["build_id"] == "syn-small"
    assert body["synthetic"] is True
    assert body["universe_counts"]["companies"] == SMALL_N
    assert body["universe_counts"]["by_kind"] == {"synthetic": SMALL_N}
    assert body["as_of"] == {"fundamentals": "2026-01-02T08:00:00Z", "prices": "2026-01-01"}
    assert any("Synthetic data" in w for w in body["warnings"])
    assert body["last_run"] is None  # synthetic builds have no pipeline run
    stale = load_params().stale_annual_report_months  # config/thresholds.yaml
    assert body["universe_rules"] == {"stale_annual_report_months": stale}


def test_metrics_lists_live_registry(client: TestClient, live_registry: MetricRegistry) -> None:
    body = client.get("/api/metrics").json()
    assert body["build_id"] == "syn-small"
    assert [m["id"] for m in body["metrics"]] == [m.id for m in live_registry]
    roic = next(m for m in body["metrics"] if m["id"] == "roic")
    assert roic["definition"] and roic["inputs"] and roic["unit"] == "frac"


def test_sectors_cover_every_sector_and_sum_to_the_snapshot(client: TestClient) -> None:
    sectors = client.get("/api/sectors").json()["sectors"]
    assert [s["sector"] for s in sectors] == [s.value for s in Sector]
    assert sum(s["count"] for s in sectors) == SMALL_N


def test_presets_list_and_detail(client: TestClient) -> None:
    listing = client.get("/api/presets").json()["presets"]
    ids = [p["id"] for p in listing]
    assert {"magic-formula", "quality-compounders", "dilution-watch"} <= set(ids)
    assert all(p["name"] and p["summary"] for p in listing)
    kinds = {p["id"]: p["kind"] for p in listing}
    assert kinds["dilution-watch"] == "red_flags" and kinds["magic-formula"] == "screen"
    detail = client.get("/api/presets/magic-formula").json()
    assert detail["build_id"] == "syn-small"
    assert detail["preset"]["id"] == "magic-formula"
    assert detail["preset"]["kind"] == "screen"
    assert detail["preset"]["screen"]["rank"]["method"] == "rank_sum"
    misses = detail["preset"]["misses"]
    assert misses and all(isinstance(m, str) for m in misses)


def test_unknown_preset_is_404(client: TestClient) -> None:
    r = client.get("/api/presets/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "UNKNOWN_PRESET"
    assert r.json()["build_id"] == "syn-small"
