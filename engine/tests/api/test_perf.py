# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Step 10: SPEC §5.10 budgets, end to end through the app (HTTP layer, validation, JSON) on
the 6,000-row synthetic build: `/api/screen` with 10 filters + near misses p95 < 300 ms,
`/api/companies/{t}` p95 < 150 ms. Marked `perf`: CI only, or `make perf` (see
tests/screen/test_perf.py)."""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.screen.helpers import screen
from tests.screen.test_perf import TEN_FILTERS

RUNS = 40
SCREEN_P95_MS = 300.0
COMPANY_P95_MS = 150.0

PERF_SCREEN = screen(
    filters=TEN_FILTERS,
    rank={"factors": [{"metric": "roic", "weight": 0.5}, {"metric": "fcf_yield", "weight": 0.5}]},
    columns=["ticker", "name", "sector", "market_cap", "roic", "fcf_yield", "rank_score"],
    near_misses=True,
).model_dump(mode="json")


def _p50_p95(call: Callable[[int], Any]) -> tuple[float, float]:
    call(0)  # warm-up: build caches (registry, search index) and DuckDB's first-run work
    timings: list[float] = []
    for i in range(RUNS):
        start = time.perf_counter()
        call(i)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return timings[RUNS // 2], timings[int(RUNS * 0.95) - 1]


@pytest.mark.slow
@pytest.mark.perf
def test_screen_p95(
    perf_client: TestClient, record_property: Callable[[str, object], None]
) -> None:
    def call(_: int) -> None:
        r = perf_client.post("/api/screen", json=PERF_SCREEN)
        assert r.status_code == 200
        body = r.json()
        assert len(body["funnel"]) == 11 and body["near_misses"]

    p50, p95 = _p50_p95(call)
    record_property("screen_p50_ms", round(p50, 1))
    record_property("screen_p95_ms", round(p95, 1))
    assert p95 < SCREEN_P95_MS, f"/api/screen p50 {p50:.1f} ms, p95 {p95:.1f} ms"


@pytest.mark.slow
@pytest.mark.perf
def test_company_p95(
    perf_client: TestClient, record_property: Callable[[str, object], None]
) -> None:
    def call(i: int) -> None:
        r = perf_client.get(f"/api/companies/SYN{1 + i * 137 % 6000:04d}")
        assert r.status_code == 200

    p50, p95 = _p50_p95(call)
    record_property("company_p50_ms", round(p50, 1))
    record_property("company_p95_ms", round(p95, 1))
    assert p95 < COMPANY_P95_MS, f"/api/companies p50 {p50:.1f} ms, p95 {p95:.1f} ms"


@pytest.mark.slow
@pytest.mark.perf
def test_company_with_why_passed_p95(
    perf_client: TestClient, record_property: Callable[[str, object], None]
) -> None:
    vectors = json.loads((Path(__file__).parent / "lz_vectors.json").read_text())["vectors"]
    encoded = next(v["encoded"] for v in vectors if '"name":"Quality compounders"' in v["text"])

    def call(i: int) -> None:
        r = perf_client.get(
            f"/api/companies/SYN{1 + i * 137 % 6000:04d}", params={"screen": encoded}
        )
        assert r.status_code == 200 and r.json()["why_passed"]

    p50, p95 = _p50_p95(call)
    record_property("why_p50_ms", round(p50, 1))
    record_property("why_p95_ms", round(p95, 1))
    # Why-passed runs the whole screen for one company, so it gets the screen budget; the plain
    # drawer keeps §5.10's 150 ms.
    assert p95 < SCREEN_P95_MS, f"/api/companies?screen= p50 {p50:.1f} ms, p95 {p95:.1f} ms"
