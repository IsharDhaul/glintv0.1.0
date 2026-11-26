# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Trust invariants (docs/glint-ui-upgrade.md, Phase 0): every number on screen agrees with every
other place it appears. The web mock has the same checks (web/src/mocks/invariants.test.ts).

Always runs against a small synthetic build. To also check a real build, point
GLINT_INVARIANTS_DATA_DIR at its data dir (the one holding current.json); it's opened read-only:

    GLINT_INVARIANTS_DATA_DIR=../data uv run pytest tests/api/test_invariants.py
"""

import itertools
import json
import os
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from glint.contracts.metrics import MetricRegistry
from glint.screen.config import load_screen_config
from glint.screen.presets import load_presets
from tests.api.conftest import ClientFor

DATA_DIR_ENV = "GLINT_INVARIANTS_DATA_DIR"
# Metrics whose sparkline sits next to the headline value on the company page.
HISTORY_METRICS = (
    "revenue_ttm",
    "gross_margin",
    "operating_margin",
    "fcf_margin",
    "share_count_change_yoy",
)
SIMPLE_CMPS = {"gt", "gte", "lt", "lte", "between"}
TEST_SCREEN: dict[str, Any] = {
    "dsl_version": 1,
    "name": "Invariants",
    "filters": {
        "op": "and",
        "children": [
            {"metric": "roic", "cmp": "gte", "value": 0.15},
            {"metric": "gross_margin", "cmp": "gte", "value": 0.4},
            {"metric": "net_debt_to_ebitda", "cmp": "lte", "value": 2, "missing": "pass"},
            {
                "op": "or",
                "children": [
                    {"metric": "revenue_growth_yoy", "cmp": "gte", "value": 0.05},
                    {"metric": "fcf_margin", "cmp": "between", "value": [0.05, 0.4]},
                ],
            },
            {"metric": "operating_margin", "cmp": "pct_rank_gte", "value": 0.5, "within": "sector"},
        ],
    },
    "columns": ["ticker", "name", "roic", "gross_margin"],
    "limit": 1000,
    "near_misses": True,
}


@pytest.fixture(params=["synthetic", "real"])
def data_dir(request: pytest.FixtureRequest, small_data_dir: Path) -> Path:
    if request.param == "synthetic":
        return small_data_dir
    env = os.environ.get(DATA_DIR_ENV)
    if not env:
        pytest.skip(f"set {DATA_DIR_ENV} to check a real build")
    return Path(env).resolve()


def _db_path(data_dir: Path) -> Path:
    pointer = json.loads((data_dir / "current.json").read_text())
    return data_dir / pointer["path"]


def _screens(live_registry: MetricRegistry) -> list[tuple[str, dict[str, Any]]]:
    presets = load_presets(live_registry)
    out = [("test-screen", TEST_SCREEN)]
    for pid, p in presets.items():
        screen = p.screen.model_dump(mode="json", exclude_none=True)
        out.append((pid, {**screen, "limit": 1000, "near_misses": True}))
    return out


# --- history ----------------------------------------------------------------------------------


def test_last_ttm_point_is_the_headline_value(data_dir: Path) -> None:
    """The company page's sparkline ends on the number printed beside it."""
    tol = load_screen_config().float_tolerance
    with duckdb.connect(str(_db_path(data_dir)), read_only=True) as con:
        cols = {r[0] for r in con.execute("DESCRIBE metrics_snapshot").fetchall()}
        metrics = [m for m in HISTORY_METRICS if m in cols]
        cols_sql = ", ".join(metrics)
        rows = con.execute(
            f"""
            WITH last AS (
                SELECT cik, metric_id, arg_max(value, period_end) AS v, max(period_end) AS period_end
                FROM metric_history WHERE basis = 'ttm' GROUP BY ALL
            ),
            head AS (
                UNPIVOT (SELECT cik, {cols_sql} FROM metrics_snapshot)
                ON COLUMNS(* EXCLUDE cik) INTO NAME metric_id VALUE v
            )
            SELECT l.cik, l.metric_id, l.period_end, l.v, h.v
            FROM last l JOIN head h USING (cik, metric_id)
            WHERE l.v IS NOT NULL
              AND abs(l.v - h.v) > {tol} * greatest(1, abs(h.v))
            ORDER BY l.metric_id, l.cik
            """
        ).fetchall()
        checked = con.execute(
            "SELECT count(DISTINCT cik) FROM metric_history WHERE basis = 'ttm'"
        ).fetchone()
    assert checked and checked[0] > 0
    assert rows == [], f"{len(rows)} sparklines end off their headline value, e.g. {rows[:5]}"


# --- screens ----------------------------------------------------------------------------------


def _simple_pass(node: dict[str, Any], values: dict[str, Any], tol: float) -> bool | None:
    """Plain comparisons on the company's own values, independent of the engine's SQL. None when
    the node needs universe stats (percentiles, sector medians) or a categorical test."""
    if "op" in node:
        parts = [_simple_pass(c, values, tol) for c in node["children"]]
        if any(p is None for p in parts):
            return None
        return any(parts) if node["op"] == "or" else all(parts)
    if node["cmp"] not in SIMPLE_CMPS:
        return None
    x, t = values.get(node["metric"]), node["value"]
    if x is None:
        return node.get("missing", "fail") == "pass"
    return {
        "gt": lambda: x > t + tol,
        "gte": lambda: x >= t - tol,
        "lt": lambda: x < t - tol,
        "lte": lambda: x <= t + tol,
        "between": lambda: t[0] - tol <= x <= t[1] + tol,
    }[node["cmp"]]()


def _values(data_dir: Path, ciks: list[str], metrics: set[str]) -> dict[str, dict[str, Any]]:
    if not ciks:
        return {}
    with duckdb.connect(str(_db_path(data_dir)), read_only=True) as con:
        cols = {r[0] for r in con.execute("DESCRIBE metrics_snapshot").fetchall()}
        wanted = sorted(m for m in metrics if m in cols)
        cur = con.execute(
            f"SELECT cik, {', '.join(wanted)} FROM metrics_snapshot WHERE list_contains($c, cik)",
            {"c": ciks},
        )
        return {r[0]: dict(zip(wanted, r[1:], strict=True)) for r in cur.fetchall()}


def _metrics_in(node: dict[str, Any]) -> set[str]:
    if "op" in node:
        return set().union(*(_metrics_in(c) for c in node["children"]))
    return {node["metric"]}


def test_screen_invariants(
    client_for: ClientFor, data_dir: Path, live_registry: MetricRegistry
) -> None:
    client: TestClient = client_for(data_dir)
    tol = load_screen_config().float_tolerance
    companies = client.get("/api/meta").json()["universe_counts"]["companies"]
    for name, screen in _screens(live_registry):
        res = client.post("/api/screen", json=screen)
        assert res.status_code == 200, (name, res.text)
        body = res.json()
        funnel = body["funnel"]

        # Sieve: at every stage kept + failed + no data = the previous stage.
        assert funnel[0]["remaining"] + funnel[0]["removed"] == companies, name
        for prev, step in itertools.pairwise(funnel):
            failed = step["removed"] - step["removed_missing"]
            assert failed >= 0, (name, step)
            assert step["remaining"] + failed + step["removed_missing"] == prev["remaining"], (
                name,
                step,
            )
        assert body["total"] == funnel[-1]["remaining"], name
        assert len(body["results"]) == min(screen["limit"], body["total"]), name

        top: list[dict[str, Any]] = screen["filters"]["children"]
        metrics = set().union(*(_metrics_in(n) for n in top)) if top else set()
        ciks = [r["cik"] for r in body["results"]] + [m["cik"] for m in body["near_misses"]]
        values = _values(data_dir, ciks, metrics)

        # Every company shown as passing passes every active filter.
        for r in body["results"]:
            for i, node in enumerate(top):
                ok = _simple_pass(node, values[r["cik"]], tol)
                assert ok in (True, None), f"{name}: {r['ticker']} fails filter {i}"

        # Every near miss fails exactly one filter, and the value shown fails it.
        for m in body["near_misses"]:
            idx = m["failed_filter_path"][2]
            for i, node in enumerate(top):
                if _simple_pass(node, values[m["cik"]], tol) is False:
                    assert i == idx, f"{name}: {m['ticker']} also fails filter {i}"
            x, t, cmp = m["value"], m["threshold"], m["cmp"]
            if not isinstance(x, int | float) or isinstance(x, bool) or t is None:
                continue
            if cmp in ("gte", "pct_rank_gte", "vs_sector_median_gte"):
                assert x < t - tol, (name, m)
            elif cmp in ("lte", "pct_rank_lte", "vs_sector_median_lte"):
                assert x > t + tol, (name, m)
            elif cmp == "gt":
                assert x <= t + tol, (name, m)
            elif cmp == "lt":
                assert x >= t - tol, (name, m)
            elif cmp == "between":
                assert x < t[0] - tol or x > t[1] + tol, (name, m)
