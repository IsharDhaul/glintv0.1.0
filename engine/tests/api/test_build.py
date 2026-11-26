# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Step 1: build access — read-only connection, pointer swaps, NO_BUILD / SCHEMA_MISMATCH."""

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import glint.api.build as build_module
from glint.api.build import (
    POINTER_CHECK_SECONDS,
    Build,
    BuildManager,
    BuildUnavailableError,
    read_pointer,
)
from glint.api.routers import catalog
from glint.contracts.api import SectorCount
from glint.contracts.db import CurrentPointer
from glint.contracts.metrics import MetricRegistry
from glint.core.paths import Paths
from tests.api.conftest import ClientFor, point_at, write_test_build


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_no_build_is_503_with_a_helpful_message(client_for: ClientFor, tmp_path: Path) -> None:
    c = client_for(tmp_path / "data")
    r = c.get("/api/sectors")
    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "NO_BUILD"
    assert body["build_id"] is None
    assert "glint fixtures synthetic" in body["message"]
    assert "glint refresh" in body["message"]
    # The header still renders, and health stays up.
    assert c.get("/api/meta").status_code == 200
    assert c.get("/api/health").json() == {"build_id": None, "status": "ok"}


def test_pointer_schema_mismatch_is_503(
    client_for: ClientFor, tmp_path: Path, live_registry: MetricRegistry
) -> None:
    data = tmp_path / "data"
    write_test_build(data, "b1", live_registry, 50, point=False)
    point_at(data, "b1", schema_version=999)
    r = client_for(data).get("/api/sectors")
    assert r.status_code == 503
    assert r.json()["error"] == "SCHEMA_MISMATCH"
    assert r.json()["build_id"] == "b1"
    assert "rebuild" in r.json()["message"]


def test_build_meta_schema_mismatch_is_503(
    client_for: ClientFor, tmp_path: Path, live_registry: MetricRegistry
) -> None:
    """The pointer can lie; the build's own build_meta wins."""
    data = tmp_path / "data"
    db = write_test_build(data, "b1", live_registry, 50)
    with duckdb.connect(str(db)) as con:
        con.execute("UPDATE build_meta SET value = '1' WHERE key = 'db_schema_version'")
    r = client_for(data).get("/api/meta")
    assert r.status_code == 503
    assert r.json()["error"] == "SCHEMA_MISMATCH"


def test_pointer_to_missing_file_is_no_build(client_for: ClientFor, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    point_at(data, "gone")
    r = client_for(data).get("/api/metrics")
    assert r.status_code == 503
    assert r.json()["error"] == "NO_BUILD"
    assert "gone.duckdb" in r.json()["message"]


def test_connection_is_read_only(tmp_path: Path, live_registry: MetricRegistry) -> None:
    data = tmp_path / "data"
    write_test_build(data, "b1", live_registry, 20)
    build = BuildManager(Paths(raw_dir=tmp_path / "raw", db_dir=data)).get()
    with pytest.raises(duckdb.Error, match="read-only"):
        build.cursor().execute("DELETE FROM companies")


def test_swap_is_picked_up_within_the_check_interval(
    client_for: ClientFor, tmp_path: Path, live_registry: MetricRegistry
) -> None:
    data = tmp_path / "data"
    write_test_build(data, "a", live_registry, 30)
    write_test_build(data, "b", live_registry, 40, point=False)
    clock = FakeClock()
    c = client_for(data, clock=clock)
    assert c.get("/api/meta").json()["build_id"] == "a"

    point_at(data, "b")
    clock.now += POINTER_CHECK_SECONDS / 2
    assert c.get("/api/meta").json()["build_id"] == "a"  # not re-checked yet

    clock.now += POINTER_CHECK_SECONDS / 2
    meta = c.get("/api/meta").json()
    assert meta["build_id"] == "b"
    assert meta["universe_counts"]["companies"] == 40
    assert c.get("/api/health").json()["build_id"] == "b"


def test_first_build_is_seen_immediately(
    client_for: ClientFor, tmp_path: Path, live_registry: MetricRegistry
) -> None:
    """With no build being served, every request re-stats the pointer (a stat is cheap)."""
    data = tmp_path / "data"
    clock = FakeClock()
    c = client_for(data, clock=clock)
    assert c.get("/api/sectors").status_code == 503
    write_test_build(data, "first", live_registry, 20)
    assert c.get("/api/sectors").status_code == 200


def test_unchanged_pointer_keeps_the_same_connection(
    tmp_path: Path, live_registry: MetricRegistry
) -> None:
    data = tmp_path / "data"
    write_test_build(data, "a", live_registry, 20)
    clock = FakeClock()
    manager = BuildManager(Paths(raw_dir=tmp_path / "raw", db_dir=data), clock=clock)
    first = manager.get()
    clock.now += POINTER_CHECK_SECONDS * 3
    assert manager.get() is first


def test_corrupt_pointer_is_no_build(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "current.json").write_text("{not json")
    manager = BuildManager(Paths(raw_dir=tmp_path / "raw", db_dir=data))
    with pytest.raises(BuildUnavailableError) as exc:
        manager.get()
    assert exc.value.code == "NO_BUILD"


def test_every_response_has_the_build_header(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-glint-build-id"] == "syn-small"


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("http://localhost:3000", True),
        ("http://localhost:3005", True),
        ("http://localhost:3099", True),
        ("http://localhost:3100", False),
        ("http://localhost:8000", False),
        ("http://evil.example:3000", False),
        ("https://localhost:3000", False),
    ],
)
def test_cors_allows_only_local_web_ports(client: TestClient, origin: str, allowed: bool) -> None:
    r = client.options(
        "/api/screen",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    assert (r.headers.get("access-control-allow-origin") == origin) is allowed


# --- review fixes --------------------------------------------------------------------------------


def test_failed_open_is_retried_without_a_pointer_change(
    client_for: ClientFor, tmp_path: Path, live_registry: MetricRegistry
) -> None:
    """The pointer can land before its file (or hit a lock): retry every check interval."""
    data = tmp_path / "data"
    data.mkdir()
    point_at(data, "late")
    clock = FakeClock()
    c = client_for(data, clock=clock)
    assert c.get("/api/sectors").status_code == 503
    write_test_build(data, "late", live_registry, 20, point=False)  # pointer untouched
    assert c.get("/api/sectors").status_code == 503  # not retried before the interval
    clock.now += POINTER_CHECK_SECONDS
    assert c.get("/api/sectors").status_code == 200


def test_unexpected_open_error_is_503_then_recovers(
    client_for: ClientFor,
    tmp_path: Path,
    live_registry: MetricRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    write_test_build(data, "b1", live_registry, 20)
    calls = {"n": 0}

    def flaky(paths: Paths | None = None) -> CurrentPointer | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("current.json: permission denied")
        return read_pointer(paths)

    monkeypatch.setattr(build_module, "read_pointer", flaky)
    clock = FakeClock()
    c = client_for(data, clock=clock)
    r = c.get("/api/sectors")
    assert r.status_code == 503
    assert "permission denied" in r.json()["message"]
    clock.now += POINTER_CHECK_SECONDS
    assert c.get("/api/sectors").status_code == 200


def test_rebuild_in_place_serves_the_new_file(
    client_for: ClientFor, tmp_path: Path, live_registry: MetricRegistry
) -> None:
    """`glint fixtures synthetic` rewrites builds/synthetic.duckdb under the same name."""
    data = tmp_path / "data"
    write_test_build(data, "same", live_registry, 30)
    clock = FakeClock()
    c = client_for(data, clock=clock)
    assert c.get("/api/meta").json()["universe_counts"]["companies"] == 30
    # The CLI (another process) unlinks and rewrites the file: a new inode at the same path.
    staged = write_test_build(tmp_path / "staging", "same", live_registry, 45, point=False)
    staged.replace(data / "builds" / "same.duckdb")
    point_at(data, "same")
    clock.now += POINTER_CHECK_SECONDS
    assert c.get("/api/meta").json()["universe_counts"]["companies"] == 45


def test_header_names_the_build_the_request_used(
    client_for: ClientFor,
    tmp_path: Path,
    live_registry: MetricRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A swap that lands mid-request doesn't relabel the response."""
    data = tmp_path / "data"
    write_test_build(data, "a", live_registry, 20)
    write_test_build(data, "b", live_registry, 20, point=False)
    clock = FakeClock()
    real = catalog._sector_counts  # pyright: ignore[reportPrivateUsage]

    def swap_mid_request(build: Build) -> list[SectorCount]:
        point_at(data, "b")
        clock.now += POINTER_CHECK_SECONDS
        return real(build)

    monkeypatch.setattr(catalog, "_sector_counts", swap_mid_request)
    r = client_for(data, clock=clock).get("/api/sectors")
    assert r.json()["build_id"] == "a"
    assert r.headers["x-glint-build-id"] == "a"
