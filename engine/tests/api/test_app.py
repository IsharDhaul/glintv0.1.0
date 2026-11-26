# Starlette's TestClient is untyped without the optional httpx2 package.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glint.api.app import create_app

MVP_REQUESTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/metrics", None),
    ("GET", "/api/sectors", None),
    ("POST", "/api/screen", {}),
    ("POST", "/api/screen/export", {}),
    ("GET", "/api/distribution?metric=roic", None),
    ("GET", "/api/search?q=appel", None),
    ("GET", "/api/companies/AAPL", None),
    ("GET", "/api/companies/AAPL/history?metric=roic", None),
    ("GET", "/api/snapshot/meta", None),
    ("GET", "/api/snapshot/values", None),
]
"""§5.5 MVP routes that need a build: 503 NO_BUILD without one."""

STUB_REQUESTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/screens", None),
    ("POST", "/api/screens", {"name": "x", "screen": {}}),
    ("GET", "/api/screens/s1", None),
    ("PUT", "/api/screens/s1", {"name": "x", "screen": {}}),
    ("DELETE", "/api/screens/s1", None),
    ("GET", "/api/screens/s1/diff", None),
    ("GET", "/api/watchlists/w1", None),
    ("POST", "/api/watchlists/w1/items", {"ticker": "AAPL"}),
    ("DELETE", "/api/watchlists/w1/items/AAPL", None),
    ("POST", "/api/nl-screen", {"prompt": "profitable small caps"}),
]
"""v1 (WT-12) and v2 (WT-13) routes: 501 until their worktree lands. Every §5.5 MVP route is
implemented (WT-08)."""

BUILDLESS_REQUESTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/health", None),
    ("GET", "/api/meta", None),
    ("GET", "/api/presets", None),
    ("GET", "/api/presets/magic-formula", None),
]
"""Routes that answer 200 with or without a build."""


@pytest.fixture
def bare_client(db_dir: Path) -> TestClient:
    """No build: GLINT_DB_DIR points at an empty temp dir."""
    return TestClient(create_app())


def test_health(bare_client: TestClient) -> None:
    r = bare_client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"build_id": None, "status": "ok"}


def test_meta_without_build(bare_client: TestClient) -> None:
    r = bare_client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["build_id"] is None
    assert body["synthetic"] is False
    assert "No build yet" in body["warnings"][0]
    assert body["universe_rules"]["stale_annual_report_months"] > 0  # config, even with no build


@pytest.mark.parametrize(("method", "url", "body"), MVP_REQUESTS)
def test_mvp_routes_without_build_are_503(
    bare_client: TestClient, method: str, url: str, body: dict[str, object] | None
) -> None:
    r = bare_client.request(method, url, json=body)
    assert r.status_code == 503, r.text
    assert r.json()["error"] == "NO_BUILD"


@pytest.mark.parametrize(("method", "url", "body"), BUILDLESS_REQUESTS)
def test_buildless_routes_are_200(
    bare_client: TestClient, method: str, url: str, body: dict[str, object] | None
) -> None:
    assert bare_client.request(method, url, json=body).status_code == 200


@pytest.mark.parametrize(("method", "url", "body"), STUB_REQUESTS)
def test_stub_routes_return_501_error_model(
    bare_client: TestClient, method: str, url: str, body: dict[str, object] | None
) -> None:
    r = bare_client.request(method, url, json=body)
    assert r.status_code == 501, r.text
    assert r.json() == {
        "build_id": None,
        "error": "NOT_IMPLEMENTED",
        "message": r.json()["message"],
        "path": None,
    }
    assert "WT-" in r.json()["message"]


def test_every_openapi_path_is_covered() -> None:
    paths = set(create_app().openapi()["paths"])
    covered = {
        url.split("?")[0]
        .replace("magic-formula", "{preset_id}")
        .replace("/AAPL/history", "/{ticker}/history")
        .replace("/companies/AAPL", "/companies/{ticker}")
        .replace("/screens/s1", "/screens/{screen_id}")
        .replace("/watchlists/w1/items/AAPL", "/watchlists/{watchlist_id}/items/{ticker}")
        .replace("/watchlists/w1", "/watchlists/{watchlist_id}")
        for _, url, _ in MVP_REQUESTS + STUB_REQUESTS + BUILDLESS_REQUESTS
    }
    assert paths == covered


def test_invalid_screen_is_422_with_path(client: TestClient) -> None:
    r = client.post("/api/screen", json={"limit": 5000})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "INVALID_SCREEN"
    assert body["path"] == ["limit"]


def test_bad_query_is_invalid_request(client: TestClient) -> None:
    r = client.get("/api/search")
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_REQUEST"


def test_schema_mismatch_is_503(bare_client: TestClient, db_dir: Path) -> None:
    db_dir.mkdir(parents=True)
    (db_dir / "current.json").write_text(
        '{"build_id": "b0", "path": "builds/b0.duckdb", "db_schema_version": 999,'
        ' "synthetic": false, "created_at": "2026-10-28T00:00:00Z"}'
    )
    r = bare_client.get("/api/meta")
    assert r.status_code == 503
    assert r.json()["error"] == "SCHEMA_MISMATCH"
    assert r.json()["build_id"] == "b0"


def test_nested_invalid_condition_path_has_no_union_tags(client: TestClient) -> None:
    body = {
        "filters": {
            "op": "and",
            "children": [
                {"op": "or", "children": [{"metric": "roic", "cmp": "between", "value": [2, 1]}]}
            ],
        }
    }
    r = client.post("/api/screen", json=body)
    assert r.status_code == 422
    assert r.json()["path"] == ["filters", "children", 0, "children", 0]


@pytest.mark.parametrize(
    ("method", "url", "status", "code"),
    [("GET", "/api/nope", 404, "NOT_FOUND"), ("POST", "/api/health", 405, "METHOD_NOT_ALLOWED")],
)
def test_framework_errors_use_error_model(
    bare_client: TestClient, method: str, url: str, status: int, code: str
) -> None:
    r = bare_client.request(method, url)
    assert r.status_code == status
    assert r.json()["error"] == code
    assert "build_id" in r.json()


def test_corrupt_pointer_is_no_build(bare_client: TestClient, db_dir: Path) -> None:
    db_dir.mkdir(parents=True)
    (db_dir / "current.json").write_text("{not json")
    r = bare_client.get("/api/meta")
    assert r.status_code == 503
    assert r.json()["error"] == "NO_BUILD"
    assert bare_client.get("/api/health").status_code == 200
