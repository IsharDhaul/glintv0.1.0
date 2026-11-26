"""API fixtures: synthetic builds in temp data dirs, served through a TestClient."""

# Starlette's TestClient is untyped without the optional httpx2 package.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from glint.api.app import create_app
from glint.api.build import BuildManager
from glint.contracts.db import DB_SCHEMA_VERSION, CurrentPointer
from glint.contracts.metrics import MetricRegistry, load_registry
from glint.core.paths import Paths
from glint.fixtures.synthetic import generate, write_build

SMALL_N = 400
PERF_N = 6000
SEED = 7


@pytest.fixture(scope="session")
def live_registry() -> MetricRegistry:
    return load_registry(treat_all_as_live=True)


def write_test_build(
    db_dir: Path,
    build_id: str,
    registry: MetricRegistry,
    n: int = SMALL_N,
    *,
    point: bool = True,
) -> Path:
    """A synthetic build at `db_dir/builds/<build_id>.duckdb` whose build_meta says
    `build_id`; `point` also makes it current."""
    db_path = db_dir / "builds" / f"{build_id}.duckdb"
    write_build(generate(n, SEED, registry), registry, db_path)
    with duckdb.connect(str(db_path)) as con:
        con.execute("UPDATE build_meta SET value = ? WHERE key = 'build_id'", [build_id])
    if point:
        point_at(db_dir, build_id)
    return db_path


def point_at(db_dir: Path, build_id: str, schema_version: int = DB_SCHEMA_VERSION) -> None:
    """Atomically replace current.json, as the pipeline does."""
    pointer = CurrentPointer(
        build_id=build_id,
        path=f"builds/{build_id}.duckdb",
        db_schema_version=schema_version,
        synthetic=True,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    tmp = db_dir / "current.json.tmp"
    tmp.write_text(pointer.model_dump_json())
    tmp.replace(db_dir / "current.json")


@pytest.fixture(scope="session")
def small_data_dir(tmp_path_factory: pytest.TempPathFactory, live_registry: MetricRegistry) -> Path:
    """A shared, read-only data dir with one small synthetic build."""
    data = tmp_path_factory.mktemp("api-small") / "data"
    write_test_build(data, "syn-small", live_registry)
    return data


@pytest.fixture(scope="session")
def perf_data_dir(tmp_path_factory: pytest.TempPathFactory, live_registry: MetricRegistry) -> Path:
    """A shared, read-only data dir with the 6,000-row synthetic build (§5.10 budgets)."""
    data = tmp_path_factory.mktemp("api-perf") / "data"
    write_test_build(data, "syn-perf", live_registry, PERF_N)
    return data


ClientFor = Callable[..., TestClient]


@pytest.fixture
def client_for(tmp_path: Path) -> ClientFor:
    """`client_for(db_dir, **manager_kwargs)`: a TestClient over the builds in `db_dir`."""

    def make(db_dir: Path, **kwargs: object) -> TestClient:
        manager = BuildManager(Paths(raw_dir=tmp_path / "raw", db_dir=db_dir), **kwargs)  # type: ignore[arg-type]
        return TestClient(create_app(manager))

    return make


@pytest.fixture
def client(client_for: ClientFor, small_data_dir: Path) -> TestClient:
    return client_for(small_data_dir)


@pytest.fixture
def perf_client(client_for: ClientFor, perf_data_dir: Path) -> TestClient:
    return client_for(perf_data_dir)
