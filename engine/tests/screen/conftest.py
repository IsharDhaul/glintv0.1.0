"""Screen-engine fixtures: the real registry and small synthetic builds in temp dirs."""

from pathlib import Path

import pytest

from glint.contracts.enums import MetricStatus
from glint.contracts.metrics import MetricRegistry, load_registry
from glint.fixtures.synthetic import generate, write_build
from glint.screen.config import ScreenConfig, load_screen_config

SMALL_N = 800
SEED = 7


@pytest.fixture(scope="session")
def live_registry() -> MetricRegistry:
    """The real registry with every id treated as live, as on a synthetic build."""
    return load_registry(treat_all_as_live=True)


@pytest.fixture(scope="session")
def strict_registry() -> MetricRegistry:
    """The real registry with every metric `planned` (since WT-06 every real metric is live)."""
    return MetricRegistry(
        [m.model_copy(update={"status": MetricStatus.PLANNED}) for m in load_registry()]
    )


@pytest.fixture(scope="session")
def screen_config() -> ScreenConfig:
    return load_screen_config()


@pytest.fixture(scope="session")
def synthetic_db(tmp_path_factory: pytest.TempPathFactory, live_registry: MetricRegistry) -> Path:
    path = tmp_path_factory.mktemp("synthetic") / "synthetic.duckdb"
    write_build(generate(SMALL_N, SEED, live_registry), live_registry, path)
    return path
