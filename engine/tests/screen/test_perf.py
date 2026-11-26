"""Step 11: 10 filters with near misses on 6,000 synthetic rows, p95 < 100 ms in-process.

The timing test is marked `perf`: `make check` skips it, because on a loaded dev machine the p95
measures the other processes, not the engine. CI runs it as its own step; `make perf` runs it
locally."""

import os
import time
from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from glint.contracts.metrics import MetricRegistry
from glint.fixtures.synthetic import generate, write_build
from glint.screen.engine import run_screen
from tests.screen.helpers import and_, cond, or_, screen

ROWS = 6000
RUNS = 40
# The brief: p95 < 100 ms in-process on a dev machine. Shared CI runners are slower and noisy,
# so there the test guards SPEC §5.10's API budget (300 ms) instead; the number is recorded.
P95_BUDGET_MS = 300.0 if os.environ.get("CI") else 100.0

TEN_FILTERS = and_(
    cond("roic", "gte", 0.05),
    cond("gross_margin", "pct_rank_gte", 0.3, within="sector"),
    cond("operating_margin", "vs_sector_median_gte", -0.05),
    cond("pe_ttm", "between", [3, 60]),
    cond("net_debt_to_ebitda", "lte", 4, missing="pass"),
    cond("fcf_margin", "gt", 0),
    cond("revenue_growth_yoy", "gte", -0.1),
    cond("sector", "neq", "Utilities"),
    or_(cond("dividend_yield", "gte", 0.01), cond("buyback_yield", "gte", 0.0)),
    cond("current_ratio", "gte", 0.8),
)


PERF_SCREEN = screen(
    filters=TEN_FILTERS,
    rank={"factors": [{"metric": "roic", "weight": 0.5}, {"metric": "fcf_yield", "weight": 0.5}]},
    columns=["ticker", "name", "sector", "market_cap", "roic", "fcf_yield", "rank_score"],
    near_misses=True,
)


@pytest.fixture(scope="module")
def perf_db(tmp_path_factory: pytest.TempPathFactory, live_registry: MetricRegistry) -> Path:
    db = tmp_path_factory.mktemp("perf") / "synthetic.duckdb"
    write_build(generate(ROWS, 7, live_registry), live_registry, db)
    return db


@pytest.mark.slow
def test_ten_filters_shape(perf_db: Path, live_registry: MetricRegistry) -> None:
    """Untimed, so `make check` still covers the perf screen itself."""
    with duckdb.connect(str(perf_db), read_only=True) as con:
        r = run_screen(con, PERF_SCREEN, live_registry).response
    assert len(r.funnel) == 11 and r.near_misses


@pytest.mark.slow
@pytest.mark.perf
def test_ten_filters_p95_under_budget(
    perf_db: Path,
    live_registry: MetricRegistry,
    record_property: Callable[[str, object], None],
) -> None:
    with duckdb.connect(str(perf_db), read_only=True) as con:
        r = run_screen(con, PERF_SCREEN, live_registry).response  # warm-up: first-run caches
        timings: list[float] = []
        for _ in range(RUNS):
            start = time.perf_counter()
            run_screen(con, PERF_SCREEN, live_registry)
            timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    p50, p95 = timings[RUNS // 2], timings[int(RUNS * 0.95) - 1]
    record_property("p50_ms", round(p50, 1))
    record_property("p95_ms", round(p95, 1))
    assert len(r.funnel) == 11 and r.near_misses
    assert p95 < P95_BUDGET_MS, f"p50 {p50:.1f} ms, p95 {p95:.1f} ms on {ROWS} rows"
