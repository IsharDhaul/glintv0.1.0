# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Step 9: every endpoint's real output validates against the committed contracts/openapi.json."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from glint.api.app import create_app
from tests.api.conftest import ClientFor
from tests.api.openapi_check import SchemaError, load_openapi, response_schema, validate

SPEC = load_openapi()
VECTORS = json.loads((Path(__file__).parent / "lz_vectors.json").read_text())["vectors"]
QUALITY = next(v["encoded"] for v in VECTORS if '"name":"Quality compounders"' in v["text"])

SCREEN = {
    "filters": {
        "op": "and",
        "children": [
            {"metric": "roic", "cmp": "pct_rank_gte", "value": 0.5, "within": "sector"},
            {"op": "or", "children": [
                {"metric": "fcf_margin", "cmp": "gte", "value": 0.05},
                {"metric": "gross_margin", "cmp": "vs_sector_median_gte", "value": 0},
            ]},
        ],
    },
    "rank": {"factors": [{"metric": "roic", "weight": 2}, {"metric": "ev_ebit", "weight": 1}]},
    "columns": ["ticker", "name", "sector", "roic", "rank_score"],
}  # fmt: skip

# (method, url, json body, expected status) — on the small synthetic build.
CASES: list[tuple[str, str, Any, int]] = [
    ("GET", "/api/health", None, 200),
    ("GET", "/api/meta", None, 200),
    ("GET", "/api/metrics", None, 200),
    ("GET", "/api/sectors", None, 200),
    ("GET", "/api/presets", None, 200),
    ("GET", "/api/presets/quality-compounders", None, 200),
    ("GET", "/api/presets/nope", None, 404),
    ("POST", "/api/screen", SCREEN, 200),
    ("POST", "/api/screen", {}, 200),
    ("POST", "/api/screen", {"limit": 0}, 422),
    ("POST", "/api/screen/export", SCREEN, 200),
    ("GET", "/api/distribution?metric=roic", None, 200),
    ("GET", "/api/distribution?metric=gross_margin&within=sector&sector=Banks", None, 200),
    ("GET", "/api/distribution?metric=nope", None, 404),
    ("GET", "/api/search?q=syn00", None, 200),
    ("GET", "/api/search?q=sinthetic", None, 200),
    ("GET", "/api/companies/SYN0001", None, 200),
    ("GET", f"/api/companies/SYN0002?screen={QUALITY}", None, 200),
    ("GET", "/api/companies/SYN0002?screen=!!", None, 422),
    ("GET", "/api/companies/NOPE", None, 404),
    ("GET", "/api/companies/SYN0001/history?metric=revenue_ttm", None, 200),
    ("GET", "/api/screens", None, 501),
    ("POST", "/api/nl-screen", {"prompt": "small caps"}, 501),
]


@pytest.mark.parametrize(("method", "url", "body", "status"), CASES, ids=lambda x: str(x)[:40])
def test_response_matches_the_contract(
    client: TestClient, method: str, url: str, body: Any, status: int
) -> None:
    r = client.request(method, url, json=body)
    assert r.status_code == status, r.text
    schema = response_schema(SPEC, method, url.split("?", maxsplit=1)[0], status)
    if schema is None:
        assert r.headers["content-type"].startswith("text/csv")
        return
    validate(r.json(), schema, SPEC)


def test_no_build_responses_match_the_contract(client_for: ClientFor, tmp_path: Path) -> None:
    c = client_for(tmp_path / "none")
    for method, url, status in [("GET", "/api/sectors", 503), ("GET", "/api/meta", 200)]:
        r = c.request(method, url)
        assert r.status_code == status
        schema = response_schema(SPEC, method, url, status)
        assert schema is not None
        validate(r.json(), schema, SPEC)


def test_committed_openapi_is_current() -> None:
    """`make contracts` would produce no diff (CI's contracts job also checks the TS types)."""
    assert create_app().openapi() == SPEC


def test_validator_catches_drift(client: TestClient) -> None:
    body = client.get("/api/companies/SYN0001").json()
    schema = response_schema(SPEC, "GET", "/api/companies/SYN0001", 200)
    assert schema is not None
    for mutate in (
        lambda b: b.pop("build_id"),
        lambda b: b["company"].update(kind="martian"),
        lambda b: b.update(extra=1),
        lambda b: b["as_of"].update(prices="yesterday"),
        lambda b: b["metrics"]["roic"].update(value=[1]),
    ):
        bad = copy.deepcopy(body)
        mutate(bad)
        with pytest.raises(SchemaError):
            validate(bad, schema, SPEC)


def test_validator_enforces_max_items(client: TestClient) -> None:
    body = client.get("/api/presets/magic-formula").json()
    schema = response_schema(SPEC, "GET", "/api/presets/magic-formula", 200)
    assert schema is not None
    validate(body, schema, SPEC)
    sort = body["preset"]["screen"]["sort"]
    sort["then"] = [{"by": "roic"}] * 3  # Sort.then: at most 2
    with pytest.raises(SchemaError, match="more than 2"):
        validate(sort, {"$ref": "#/components/schemas/Sort"}, SPEC)
    with pytest.raises(SchemaError):
        validate(body, schema, SPEC)
