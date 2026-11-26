# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""screen, export, distribution."""

import csv
import io
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from glint.api.build import connect_read_only
from glint.api.routers.screen import HISTOGRAM_BINS, screen_slug
from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import Screen
from glint.screen.engine import run_screen
from tests.api.conftest import SMALL_N

SCREEN: dict[str, Any] = {
    "name": "Cheap & good (test)",
    "filters": {
        "op": "and",
        "children": [
            {"metric": "roic", "cmp": "gte", "value": 0.1},
            {"metric": "ev_ebit", "cmp": "between", "value": [0, 20]},
        ],
    },
    "rank": {"factors": [{"metric": "roic", "weight": 1}, {"metric": "ev_ebit", "weight": 1}]},
    "columns": ["ticker", "name", "roic", "ev_ebit", "rank_score"],
}


def _preset_screen(client: TestClient, preset_id: str) -> dict[str, Any]:
    return client.get(f"/api/presets/{preset_id}").json()["preset"]["screen"]


def test_screen_matches_the_engine(
    client: TestClient, small_data_dir: Any, live_registry: MetricRegistry
) -> None:
    r = client.post("/api/screen", json=SCREEN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["build_id"] == "syn-small"
    with connect_read_only(small_data_dir / "builds" / "syn-small.duckdb") as con:
        direct = run_screen(con, Screen.model_validate(SCREEN), live_registry).response
    assert body == direct.model_dump(mode="json")
    assert body["funnel"][0]["label"] == "Universe"
    assert body["total"] == len(body["results"])


@pytest.mark.parametrize("preset_id", ["magic-formula", "quality-compounders", "dilution-watch"])
def test_every_preset_screen_runs(client: TestClient, preset_id: str) -> None:
    r = client.post("/api/screen", json=_preset_screen(client, preset_id))
    assert r.status_code == 200, r.text


def test_whole_preset_body_gets_a_hint(client: TestClient) -> None:
    preset = client.get("/api/presets/magic-formula").json()["preset"]
    r = client.post("/api/screen", json=preset)
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_SCREEN"
    assert "`screen` object" in r.json()["message"]


def test_unknown_metric_is_invalid_screen_with_path(client: TestClient) -> None:
    body = {"filters": {"op": "and", "children": [{"metric": "nope", "cmp": "gt", "value": 1}]}}
    r = client.post("/api/screen", json=body)
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_SCREEN"
    assert r.json()["path"] == ["filters", "children", 0, "metric"]
    assert r.json()["build_id"] == "syn-small"


def test_screen_without_build_is_503(client_for: Any, tmp_path: Any) -> None:
    r = client_for(tmp_path / "none").post("/api/screen", json=SCREEN)
    assert r.status_code == 503
    assert r.json()["error"] == "NO_BUILD"


# --- export ------------------------------------------------------------------------------------


def test_export_csv(client: TestClient) -> None:
    screened = client.post("/api/screen", json=SCREEN).json()
    r = client.post("/api/screen/export", json=SCREEN)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-glint-build-id"] == "syn-small"
    disposition = r.headers["content-disposition"]
    assert re.fullmatch(
        r'attachment; filename="glint-cheap-good-test-\d{4}-\d{2}-\d{2}\.csv"', disposition
    )
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == [
        "rank",
        "ticker",
        "name",
        "roic",
        "ev_ebit",
        "rank_score",
        "as_of_fundamentals",
        "as_of_prices",
        "notes",
    ]
    assert len(rows) - 1 == len(screened["results"])
    first, result = rows[1], screened["results"][0]
    assert first[0] == str(result["rank"])
    assert first[1] == result["ticker"]
    assert float(first[3]) == result["values"]["roic"]
    assert first[6:8] == ["2026-01-02", "2026-01-01"]


def test_export_nulls_are_empty_with_a_reason(client: TestClient) -> None:
    """A null cell is empty, and `notes` carries its reason code (never a silent zero)."""
    body = {"columns": ["ticker", "roic", "pe_ttm"], "limit": SMALL_N}
    rows = list(csv.DictReader(io.StringIO(client.post("/api/screen/export", json=body).text)))
    nulls = [r for r in rows if r["roic"] == ""]
    assert nulls, "the synthetic build has null ROICs"
    assert all("roic: " in r["notes"] for r in nulls)
    assert "rank" not in rows[0]


def test_export_null_rank_says_why(client: TestClient) -> None:
    """Ranked without `rank_score` as a column: a null rank still carries its reason."""
    body = {
        "rank": {"method": "rank_sum", "factors": [{"metric": "roic", "weight": 1},
                                                   {"metric": "pe_ttm", "weight": 1}]},
        "columns": ["ticker", "roic"],
        "limit": 1000,
    }  # fmt: skip
    rows = list(csv.DictReader(io.StringIO(client.post("/api/screen/export", json=body).text)))
    assert "rank_score" not in rows[0]
    unranked = [r for r in rows if r["rank"] == ""]
    assert unranked, "rank_sum needs every factor, so some rows are unranked"
    assert all("rank: " in r["notes"] for r in unranked)
    assert all("rank_score" not in r["notes"] for r in rows)


def test_export_adds_ticker_when_not_a_column(client: TestClient) -> None:
    r = client.post("/api/screen/export", json={"columns": ["roic"], "limit": 3})
    header = next(csv.reader(io.StringIO(r.text)))
    assert header[:2] == ["ticker", "roic"]


@pytest.mark.parametrize(
    ("name", "slug"),
    [("Quality compounders", "quality-compounders"), ("  P/E < 10!! ", "p-e-10"), ("—", "screen")],
)
def test_screen_slug(name: str, slug: str) -> None:
    assert screen_slug(name) == slug


# --- distribution ------------------------------------------------------------------------------


def test_distribution_over_the_universe(client: TestClient) -> None:
    r = client.get("/api/distribution?metric=roic")
    assert r.status_code == 200, r.text
    d = r.json()
    universe = client.post("/api/screen", json={"near_misses": False}).json()["universe_count"]
    assert d["count"] + d["null_count"] == universe
    assert len(d["bins"]) == HISTOGRAM_BINS
    assert sum(b["count"] for b in d["bins"]) == d["count"]
    assert all(b["lo"] <= b["hi"] for b in d["bins"])
    assert all(a["hi"] == b["lo"] for a, b in zip(d["bins"], d["bins"][1:], strict=False))
    p = d["percentiles"]
    assert list(p) == ["p5", "p25", "p50", "p75", "p95"]
    assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]
    assert d["bins"][0]["lo"] <= p["p5"] and d["bins"][-1]["hi"] >= p["p95"]


def test_distribution_within_one_sector(client: TestClient) -> None:
    whole = client.get("/api/distribution?metric=gross_margin").json()
    tech = client.get(
        "/api/distribution?metric=gross_margin&within=sector&sector=Technology"
    ).json()
    assert tech["sector"] == "Technology"
    assert 0 < tech["count"] < whole["count"]


@pytest.mark.parametrize(
    ("query", "status", "code"),
    [
        ("metric=nope", 404, "UNKNOWN_METRIC"),
        ("metric=roic&within=sector", 422, "INVALID_REQUEST"),
        ("metric=roic&sector=Technology", 422, "INVALID_REQUEST"),
        ("metric=roic&sector=Nope", 422, "INVALID_REQUEST"),
    ],
)
def test_distribution_errors(client: TestClient, query: str, status: int, code: str) -> None:
    r = client.get(f"/api/distribution?{query}")
    assert r.status_code == status
    assert r.json()["error"] == code


def test_distribution_rejects_yes_no_metrics(
    client: TestClient, live_registry: MetricRegistry
) -> None:
    from glint.contracts.enums import Unit  # noqa: PLC0415

    flag = next((m.id for m in live_registry if m.unit is Unit.BOOL), None)
    if flag is None:
        pytest.skip("no bool metric in the registry")
    r = client.get(f"/api/distribution?metric={flag}")
    assert r.status_code == 422
    assert r.json()["path"] == ["metric"]
