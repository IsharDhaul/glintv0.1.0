"""Sieve, near misses, ranking and results (steps 5–8), plus seeded property tests."""

import itertools
import random
import statistics
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import duckdb
import pytest

from glint.contracts.api import ScreenResponse
from glint.contracts.enums import NoteCode
from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import Screen
from glint.fixtures.synthetic import generate, write_build
from glint.screen.compile import compile_screen
from glint.screen.config import ScreenConfig
from glint.screen.engine import MAX_NEAR_MISSES, registry_for_build, run_screen
from glint.screen.validate import InvalidScreenError
from tests.screen.helpers import and_, compiled_rows, cond, or_, screen, snapshot


@pytest.fixture
def con(synthetic_db: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect(str(synthetic_db), read_only=True) as c:
        yield c


def _run(con: duckdb.DuckDBPyConnection, s: Screen, registry: MetricRegistry) -> ScreenResponse:
    return run_screen(con, s, registry).response


# --- 5. sieve ----------------------------------------------------------------------------------


def test_funnel_counts_and_binding(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(
        filters=and_(
            cond("roic", "gte", 0.10),
            or_(cond("revenue_growth_yoy", "gte", 0.1), cond("pe_ttm", "lte", 15)),
            cond("net_debt_to_ebitda", "lte", 2.0, missing="pass"),
        ),
        limit=1000,
    )
    r = _run(con, s, live_registry)
    f = r.funnel
    assert [x.index for x in f] == [0, 1, 2, 3]  # the OR group is one step
    assert f[0].filter_path is None and f[0].remaining == r.universe_count
    assert f[0].removed + f[0].remaining == 800
    for prev, cur in itertools.pairwise(f):
        assert cur.remaining == prev.remaining - cur.removed
        assert 0 <= cur.removed_missing <= cur.removed
    assert f[-1].remaining == r.total == len(r.results)
    assert f[3].removed_missing == 0  # missing: pass never removes for missing data
    binding = [x for x in f if x.binding]
    assert len(binding) == 1
    assert binding[0].removed == max(x.removed for x in f[1:])
    assert f[1].label == "ROIC ≥ 10.0%"
    assert f[2].label.startswith("Any of: ")


def test_removed_missing_is_exact(
    con: duckdb.DuckDBPyConnection, synthetic_db: Path, live_registry: MetricRegistry
) -> None:
    """Only `roic` filter: removed_missing = universe rows with null roic."""
    base = _run(con, screen(limit=1000), live_registry)
    universe = {row.ticker for row in base.results}
    snap = {x["ticker"]: x for x in snapshot(synthetic_db, "ticker", "roic")}
    nulls = sum(1 for t in universe if snap[t]["roic"] is None)
    fails = sum(1 for t in universe if snap[t]["roic"] is not None and snap[t]["roic"] < 0.1)
    assert nulls > 0

    r = _run(con, screen(filters=and_(cond("roic", "gte", 0.1)), limit=1000), live_registry)
    assert r.funnel[1].removed == nulls + fails
    assert r.funnel[1].removed_missing == nulls

    r = _run(
        con,
        screen(filters=and_(cond("roic", "gte", 0.1, missing="pass")), limit=1000),
        live_registry,
    )
    assert r.funnel[1].removed == fails
    assert r.funnel[1].removed_missing == 0
    assert r.total == len(universe) - fails


# --- 6. near misses ----------------------------------------------------------------------------


def test_near_misses_fail_exactly_one_filter(
    con: duckdb.DuckDBPyConnection, synthetic_db: Path, live_registry: MetricRegistry
) -> None:
    s = screen(
        filters=and_(
            cond("roic", "gte", 0.15),
            cond("fcf_margin", "gte", 0.1),
            cond("pe_ttm", "between", [5, 25]),
        ),
    )
    r = _run(con, s, live_registry)
    assert 0 < len(r.near_misses) <= MAX_NEAR_MISSES
    snap = {
        x["ticker"]: x for x in snapshot(synthetic_db, "ticker", "roic", "fcf_margin", "pe_ttm")
    }
    tests: dict[int, Callable[[dict[str, Any]], bool]] = {
        0: lambda x: x["roic"] is not None and x["roic"] >= 0.15,
        1: lambda x: x["fcf_margin"] is not None and x["fcf_margin"] >= 0.1,
        2: lambda x: x["pe_ttm"] is not None and 5 <= x["pe_ttm"] <= 25,
    }
    distances = [nm.distance for nm in r.near_misses]
    known = [d for d in distances if d is not None]
    assert known == sorted(known)
    assert distances[: len(known)] == known  # unknown distances come last
    for nm in r.near_misses:
        row = snap[nm.ticker]
        failed = [i for i, t in tests.items() if not t(row)]
        assert failed == [nm.failed_filter_path[-1]]
        assert nm.value == row[nm.metric]
        if nm.metric == "pe_ttm":
            assert nm.threshold == [5.0, 25.0]


def test_near_miss_in_or_group_reports_closest_child(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(
        filters=and_(
            cond("sector", "neq", "Banks"),
            or_(cond("roic", "gte", 0.5), cond("revenue_growth_yoy", "gte", 0.6)),
        )
    )
    r = _run(con, s, live_registry)
    assert r.near_misses
    for nm in r.near_misses:
        assert nm.failed_filter_path == ["filters", "children", 1]
        assert nm.failed_label.startswith("Any of: ")
        assert nm.metric in {"roic", "revenue_growth_yoy"}


def test_percentile_and_vs_median_near_misses(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(
        filters=and_(
            cond("gross_margin", "pct_rank_gte", 0.8, within="sector"),
            cond("operating_margin", "vs_sector_median_gte", 0.05),
        )
    )
    r = _run(con, s, live_registry)
    for nm in r.near_misses:
        if nm.metric == "gross_margin":
            assert isinstance(nm.value, float) and nm.threshold == 0.8
            assert nm.distance == pytest.approx(0.8 - nm.value)
        else:
            assert isinstance(nm.value, float) and isinstance(nm.threshold, float)
            assert nm.value < nm.threshold  # raw value vs the raw value the median implies


def test_near_misses_can_be_turned_off(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(filters=and_(cond("roic", "gte", 0.15)), near_misses=False)
    assert _run(con, s, live_registry).near_misses == []


# --- 7. ranking --------------------------------------------------------------------------------


def _ranked(**rank: Any) -> Screen:
    return screen(rank=rank, columns=["ticker", "roic", "fcf_yield", "rank_score"], limit=1000)


def test_percentile_composite(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = _ranked(factors=[{"metric": "roic", "weight": 3}, {"metric": "fcf_yield", "weight": 1}])
    r = _run(con, s, live_registry)
    scored = [x for x in r.results if x.rank_score is not None]
    assert scored and scored[0].rank == 1
    assert [x.rank for x in scored] == list(range(1, len(scored) + 1))
    for x in scored:
        parts = [v for v in x.factor_contributions.values() if v is not None]
        assert sum(parts) == pytest.approx(x.rank_score)
        assert x.rank_score is not None and 0 <= x.rank_score <= 1
    scores = [x.rank_score for x in scored]
    assert scores == sorted(scores, reverse=True)  # pyright: ignore[reportArgumentType, reportCallIssue]
    unscored = [x for x in r.results if x.rank_score is None]
    assert all(x.rank is None for x in unscored)
    assert r.results[len(scored) :] == unscored  # unranked rows last


def test_weights_renormalize_over_present_factors(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = _ranked(
        factors=[{"metric": "roic", "weight": 0.5}, {"metric": "fcf_yield", "weight": 0.5}],
        min_factor_coverage=0.5,
    )
    r = _run(con, s, live_registry)
    half = [x for x in r.results if x.factor_contributions["roic"] is None and x.rank_score]
    assert half, "financials have no roic but have fcf_yield"
    for x in half:
        # Only fcf_yield present: its weight becomes 1, so score = its percentile.
        assert x.rank_score == x.factor_contributions["fcf_yield"]


def test_min_factor_coverage_nulls_the_score(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = _ranked(factors=[{"metric": "roic", "weight": 0.5}, {"metric": "fcf_yield", "weight": 0.5}])
    r = _run(con, s, live_registry)
    short = [x for x in r.results if x.factor_contributions["roic"] is None]
    assert short
    for x in short:
        assert x.rank_score is None and x.rank is None
        assert x.values["rank_score"] is None
        assert x.notes["rank_score"].code is NoteCode.MISSING_INPUT


def test_rank_sum_is_greenblatt_order(
    con: duckdb.DuckDBPyConnection, synthetic_db: Path, live_registry: MetricRegistry
) -> None:
    s = screen(
        rank={
            "method": "rank_sum",
            "factors": [
                {"metric": "ebit_ev", "weight": 1},
                {"metric": "greenblatt_roc", "weight": 1},
            ],
        },
        columns=["ticker", "ebit_ev", "greenblatt_roc", "rank_score"],
        limit=1000,
    )
    r = _run(con, s, live_registry)
    both = [x for x in r.results if x.rank_score is not None]
    # Reference: rank (1 = highest) of each factor among universe rows that have it.
    universe = [x.ticker for x in r.results]
    snap = {x["ticker"]: x for x in snapshot(synthetic_db, "ticker", "ebit_ev", "greenblatt_roc")}

    def ranks(metric: str) -> dict[str, int]:
        vals = [(snap[t][metric], t) for t in universe if snap[t][metric] is not None]
        return {t: 1 + sum(1 for v2, _ in vals if v2 > v) for v, t in vals}

    e, g = ranks("ebit_ev"), ranks("greenblatt_roc")
    for x in both:
        assert x.rank_score == e[x.ticker] + g[x.ticker]
    keys = [(x.rank_score, x.ticker) for x in both]
    assert keys == sorted(keys)  # lowest sum first, ties by ticker
    assert all(x.rank_score is None for x in r.results if x.values["ebit_ev"] is None)


def test_rank_is_deterministic(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(
        filters=and_(cond("revenue_growth_yoy", "gte", 0.0)),
        rank={
            "factors": [{"metric": "piotroski_f", "weight": 1}],  # integer score: many ties
            "within": "sector",
        },
        columns=["ticker", "piotroski_f", "rank_score"],
        limit=1000,
    )
    runs = [_run(con, s, live_registry).model_dump_json() for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    rows = _run(con, s, live_registry).results
    for a, b in itertools.pairwise(rows):
        if a.rank_score is not None and a.rank_score == b.rank_score:
            assert a.ticker < b.ticker


# --- 8. results --------------------------------------------------------------------------------


def test_columns_notes_sort_and_limit(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(
        columns=["ticker", "sector", "roic", "pe_ttm"],
        sort={"by": "pe_ttm", "dir": "asc"},
        limit=1000,
    )
    r = _run(con, s, live_registry)
    assert r.total == r.universe_count == len(r.results)
    pes = [x.values["pe_ttm"] for x in r.results]
    present = [p for p in pes if p is not None]
    assert present == sorted(present)  # pyright: ignore[reportArgumentType]
    assert pes[len(present) :] == [None] * (len(pes) - len(present))  # nulls last
    for x in r.results:
        assert set(x.values) == {"ticker", "sector", "roic", "pe_ttm"}
        for col in ("roic", "pe_ttm"):
            if x.values[col] is None:
                assert col in x.notes  # every null carries a reason code

    limited = _run(con, screen(limit=7), live_registry)
    assert len(limited.results) == 7 and limited.total == r.total
    assert [x.ticker for x in limited.results] == sorted(x.ticker for x in limited.results)


def test_secondary_sort_keys_break_ties_in_order(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    sort = {"by": "sector", "dir": "asc", "then": [{"by": "roic", "dir": "desc"}]}
    s = screen(columns=["ticker", "sector", "roic"], sort=sort, limit=1000)
    r = _run(con, s, live_registry)
    assert r.total == len(r.results)

    def key(x: Any) -> tuple[Any, ...]:
        roic = x.values["roic"]
        # sector asc; within it roic desc with nulls last; then ticker asc
        return (x.values["sector"], roic is None, -(roic or 0.0), x.ticker)

    assert [x.ticker for x in r.results] == [x.ticker for x in sorted(r.results, key=key)]
    sectors = [x.values["sector"] for x in r.results]
    assert len(set(sectors)) > 1  # the secondary key really is exercised within ties


def test_rank_score_as_a_secondary_key(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    rank = {"factors": [{"metric": "roic", "weight": 1}]}
    cols = ["ticker", "sector", "rank_score"]
    sort = {"by": "sector", "dir": "asc", "then": [{"by": "rank_score", "dir": "desc"}]}
    r = _run(con, screen(rank=rank, columns=cols, sort=sort, limit=1000), live_registry)

    def key(x: Any) -> tuple[Any, ...]:
        return (x.values["sector"], x.rank is None, x.rank or 0, x.ticker)  # best rank first

    assert [x.ticker for x in r.results] == [x.ticker for x in sorted(r.results, key=key)]


def test_rank_score_keeps_its_column_position(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    cols = ["ticker", "rank_score", "roic"]
    s = screen(rank={"factors": [{"metric": "roic", "weight": 1}]}, columns=cols, limit=3)
    for row in _run(con, s, live_registry).results:
        assert list(row.values) == cols


def test_rank_sorted_ascending_is_worst_first_unranked_last(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    rank = {"factors": [{"metric": "roic", "weight": 1}]}
    cols = ["ticker", "rank_score"]
    best = _run(con, screen(rank=rank, columns=cols, limit=1000), live_registry).results
    worst = _run(
        con,
        screen(rank=rank, columns=cols, sort={"by": "rank_score", "dir": "asc"}, limit=1000),
        live_registry,
    ).results
    ranked = [x.ticker for x in best if x.rank is not None]
    assert [x.ticker for x in worst if x.rank is not None] == ranked[::-1]
    n = len(ranked)
    assert all(x.rank is None for x in worst[n:]) and len(worst) > n


def test_small_peer_group_note_on_the_rank_cell(
    tmp_path: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    db = tmp_path / "tiny.duckdb"
    write_build(generate(60, 3, live_registry), live_registry, db)
    s = screen(
        universe={"exchanges": ["NYSE", "Nasdaq", "NYSE American"], "avg_dollar_volume_min": None},
        rank={"within": "sector", "factors": [{"metric": "fcf_yield", "weight": 1}]},
        columns=["ticker", "sector", "fcf_yield", "rank_score"],
        limit=1000,
    )
    with duckdb.connect(str(db), read_only=True) as c:
        r = run_screen(c, s, live_registry, screen_config).response
    per_sector: dict[str, int] = {}
    for x in r.results:
        if x.values["fcf_yield"] is not None:
            per_sector[x.sector] = per_sector.get(x.sector, 0) + 1
    small = {sec for sec, n in per_sector.items() if n < screen_config.small_peer_group_min}
    assert small, "the tiny build should have a sector with fewer than 5 values"
    for x in r.results:
        if x.sector in small and x.values["fcf_yield"] is not None:
            assert x.rank_score is None and x.rank is None
            assert x.notes["rank_score"].code is NoteCode.SMALL_PEER_GROUP


def test_near_miss_in_mixed_nesting(
    con: duckdb.DuckDBPyConnection, synthetic_db: Path, live_registry: MetricRegistry
) -> None:
    """Step 2 = OR(AND(roic ≥ 0.5, pe ≤ 10), growth ≥ 0.6): the AND reports its furthest
    failing leaf, the OR its closest child."""
    s = screen(
        filters=and_(
            cond("sector", "neq", "Banks"),
            or_(
                and_(cond("roic", "gte", 0.5), cond("pe_ttm", "lte", 10)),
                cond("revenue_growth_yoy", "gte", 0.6),
            ),
        )
    )
    r = _run(con, s, live_registry)
    snap = {
        x["ticker"]: x
        for x in snapshot(synthetic_db, "ticker", "roic", "pe_ttm", "revenue_growth_yoy")
    }

    def gap(x: float | None, t: float) -> float | None:
        return None if x is None else abs(x - t) / abs(t)

    step2 = [nm for nm in r.near_misses if nm.failed_filter_path == ["filters", "children", 1]]
    assert step2
    for nm in step2:
        row = snap[nm.ticker]
        failing_and = [
            gap(row["roic"], 0.5) if not (row["roic"] is not None and row["roic"] >= 0.5) else 0,
            gap(row["pe_ttm"], 10)
            if not (row["pe_ttm"] is not None and row["pe_ttm"] <= 10)
            else 0,
        ]
        failing_and = [d for d in failing_and if d != 0]
        and_d = None if None in failing_and else max(d for d in failing_and if d is not None)
        options = [d for d in (and_d, gap(row["revenue_growth_yoy"], 0.6)) if d is not None]
        expected = min(options) if options else None
        assert nm.distance == (pytest.approx(expected) if expected is not None else None)


def test_vs_median_ratio_with_non_positive_median_reads_as_missing(
    con: duckdb.DuckDBPyConnection, synthetic_db: Path, live_registry: MetricRegistry
) -> None:
    base = _run(con, screen(limit=1000), live_registry)
    universe = {x.ticker for x in base.results}
    tech = [
        x["net_debt"]
        for x in snapshot(synthetic_db, "ticker", "sector", "net_debt")
        if x["ticker"] in universe and x["sector"] == "Technology" and x["net_debt"] is not None
    ]
    assert len(tech) >= 5 and statistics.median(tech) <= 0  # precondition of the synthetic model
    s = screen(filters=and_(cond("net_debt", "vs_sector_median_gte", 0.5)), limit=1000)
    r = _run(con, s, live_registry)
    assert all(x.sector != "Technology" for x in r.results)
    assert r.funnel[1].removed_missing >= len(tech)


def test_not_null_removals_count_as_missing_data(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    r = _run(con, screen(filters=and_(cond("dividend_yield", "not_null"))), live_registry)
    assert r.funnel[1].removed > 0
    assert r.funnel[1].removed_missing == r.funnel[1].removed
    r = _run(con, screen(filters=and_(cond("dividend_yield", "is_null"))), live_registry)
    assert r.funnel[1].removed > 0 and r.funnel[1].removed_missing == 0


def test_response_metadata_and_warnings(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    r = _run(con, screen(filters=and_(cond("roic", "gte", 15))), live_registry)
    assert r.build_id == "synthetic"
    assert r.as_of.prices is not None and r.as_of.fundamentals is not None
    assert len(r.warnings) == 1 and "0.15" in r.warnings[0]
    # The threshold is applied as given (15 = 1,500%), never silently read as 0.15: at most the
    # rare synthetic outliers with tiny invested capital pass. A seed-free bound, not `== 0`.
    over = con.execute("SELECT count(*) FROM metrics_snapshot WHERE roic >= 15").fetchone()
    assert over is not None and r.total <= over[0]


def test_registry_for_build_treats_synthetic_as_live(con: duckdb.DuckDBPyConnection) -> None:
    assert registry_for_build(con).treat_all_as_live


def test_invalid_screen_raises(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    with pytest.raises(InvalidScreenError):
        run_screen(con, screen(filters=and_(cond("roic; DROP TABLE", "gte", 1))), live_registry)


# --- property tests ----------------------------------------------------------------------------

_NUMERIC = ["roic", "pe_ttm", "fcf_margin", "revenue_growth_yoy", "gross_margin", "net_debt",
            "debt_to_equity", "dividend_yield", "share_count_change_yoy", "operating_margin"]  # fmt: skip
_DIFF = {"roic", "fcf_margin", "revenue_growth_yoy", "gross_margin", "dividend_yield",
         "share_count_change_yoy", "operating_margin"}  # frac: vs-median is a difference  # fmt: skip
_SECTORS = ["Technology", "Industrials", "Health Care", "Banks", "Energy", "Utilities"]
_SMALL_PEERS = 5  # thresholds.yaml metrics.small_peer_group_min
_TOL = 1e-9


class _Reference:
    """Independent stats over the universe rows: percentiles and sector medians."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.values = {m: [x[m] for x in rows if x[m] is not None] for m in _NUMERIC}
        self.pct_u: dict[str, dict[str, float]] = {}
        self.pct_s: dict[str, dict[str, float | None]] = {}
        self.median: dict[str, dict[str, float | None]] = {}
        for m in _NUMERIC:
            self.pct_u[m] = {
                x["ticker"]: _pr(self.values[m], x[m]) for x in rows if x[m] is not None
            }
            by_sector: dict[str, list[float]] = {}
            for x in rows:
                if x[m] is not None:
                    by_sector.setdefault(x["sector"], []).append(x[m])
            self.median[m] = {
                s: statistics.median(v) if len(v) >= _SMALL_PEERS else None
                for s, v in by_sector.items()
            }
            self.pct_s[m] = {
                x["ticker"]: _pr(by_sector[x["sector"]], x[m])
                if len(by_sector[x["sector"]]) >= _SMALL_PEERS
                else None
                for x in rows
                if x[m] is not None
            }

    def compared(self, c: dict[str, Any], row: dict[str, Any]) -> Any:
        m, cmp = c["metric"], c["cmp"]
        if cmp.startswith("pct_rank"):
            table = self.pct_s[m] if c["within"] == "sector" else self.pct_u[m]
            return table.get(row["ticker"])
        if cmp.startswith("vs_sector_median"):
            med = self.median[m].get(row["sector"])
            if row[m] is None or med is None:
                return None
            if m in _DIFF:
                return row[m] - med
            return row[m] / med if med > 0 else None
        return row[m]


def _pr(values: list[float], x: float) -> float:
    return 0.0 if len(values) == 1 else sum(1 for v in values if v < x) / (len(values) - 1)


def _random_leaf(rng: random.Random, ref: _Reference) -> dict[str, Any]:
    kind = rng.random()
    missing = rng.choice(["fail", "pass"])
    metric = rng.choice(_NUMERIC)
    if kind < 0.08:
        return cond(metric, rng.choice(["is_null", "not_null"]))
    if kind < 0.14:
        return cond("sector", "in", rng.sample(_SECTORS, 2), missing=missing)
    if kind < 0.18:
        return cond("sector", rng.choice(["eq", "neq"]), rng.choice(_SECTORS), missing=missing)
    if kind < 0.22:
        return cond("dps_no_cut_5y", rng.choice(["eq", "neq"]), rng.random() < 0.5, missing=missing)
    if kind < 0.36:
        within = rng.choice(["universe", "sector"])
        cmp = rng.choice(["pct_rank_gte", "pct_rank_lte"])
        return cond(metric, cmp, rng.random(), within=within, missing=missing)
    if kind < 0.46:
        cmp = rng.choice(["vs_sector_median_gte", "vs_sector_median_lte"])
        value = rng.uniform(-0.1, 0.1) if metric in _DIFF else rng.uniform(0.5, 1.5)
        return cond(metric, cmp, value, missing=missing)
    q = sorted(rng.choice(ref.values[metric]) for _ in range(2))
    if kind < 0.6:
        return cond(metric, "between", q, missing=missing)
    return cond(metric, rng.choice(["gt", "gte", "lt", "lte"]), q[0], missing=missing)


def _random_node(rng: random.Random, ref: _Reference, depth: int) -> dict[str, Any]:
    """A leaf, or (below depth 3) a group of 2–3 nodes: AND inside OR and OR inside AND."""
    if depth < 3 and rng.random() < 0.3:
        op = or_ if depth % 2 else and_
        return op(*(_random_node(rng, ref, depth + 1) for _ in range(rng.randint(2, 3))))
    return _random_leaf(rng, ref)


def _random_screen(rng: random.Random, ref: _Reference) -> Screen:
    children = [_random_node(rng, ref, 1) for _ in range(rng.randint(1, 5))]
    return screen(filters=and_(*children), limit=1000)


def _reference_ok(c: dict[str, Any], row: dict[str, Any], ref: _Reference) -> bool:
    """Independent evaluation of one leaf on a universe row."""
    cmp, v = c["cmp"], c["value"]
    x = ref.compared(c, row)
    if cmp == "is_null":
        return x is None
    if cmp == "not_null":
        return x is not None
    if x is None:
        return c["missing"] == "pass"
    return {
        "gt": lambda: x > v + _TOL,
        "gte": lambda: x >= v - _TOL,
        "lt": lambda: x < v - _TOL,
        "lte": lambda: x <= v + _TOL,
        "between": lambda: v[0] - _TOL <= x <= v[1] + _TOL,
        "in": lambda: x in v,
        "eq": lambda: x == v,
        "neq": lambda: x != v,
        "pct_rank_gte": lambda: x >= v - _TOL,
        "pct_rank_lte": lambda: x <= v + _TOL,
        "vs_sector_median_gte": lambda: x >= v - _TOL,
        "vs_sector_median_lte": lambda: x <= v + _TOL,
    }[cmp]()


def _reference_node(node: dict[str, Any], row: dict[str, Any], ref: _Reference) -> bool:
    if "op" in node:
        results = [_reference_node(ch, row, ref) for ch in node["children"]]
        return all(results) if node["op"] == "and" else any(results)
    return _reference_ok(node, row, ref)


def test_property_random_screens(
    con: duckdb.DuckDBPyConnection,
    synthetic_db: Path,
    live_registry: MetricRegistry,
) -> None:
    base = _run(con, screen(limit=1000), live_registry)
    universe = {x.ticker for x in base.results}
    snap = [
        x
        for x in snapshot(synthetic_db, "ticker", "sector", "dps_no_cut_5y", *_NUMERIC)
        if x["ticker"] in universe
    ]
    by_ticker = {x["ticker"]: x for x in snap}
    ref = _Reference(snap)

    rng = random.Random(20261029)
    for _ in range(60):
        s = _random_screen(rng, ref)
        r = _run(con, s, live_registry)
        tops = s.model_dump(mode="json")["filters"]["children"]
        # Every result satisfies every filter, and nothing that does is left out.
        expected = {x["ticker"] for x in snap if all(_reference_node(t, x, ref) for t in tops)}
        assert {x.ticker for x in r.results} == expected
        # Sieve counts never increase.
        remaining = [f.remaining for f in r.funnel]
        assert remaining == sorted(remaining, reverse=True)
        assert all(0 <= f.removed_missing <= f.removed for f in r.funnel[1:])
        # Every near miss fails exactly one top-level filter.
        for nm in r.near_misses:
            row = by_ticker[nm.ticker]
            failed = [i for i, t in enumerate(tops) if not _reference_node(t, row, ref)]
            assert failed == [nm.failed_filter_path[-1]]


def _python_funnel(
    synthetic_db: Path, s: Screen, registry: MetricRegistry, config: ScreenConfig
) -> list[tuple[int, int, int]]:
    """(remaining, removed, removed_missing) per filter step, recounted from the full eval."""
    c = compile_screen(s, registry, config)
    rows = compiled_rows(synthetic_db, s, registry, config)
    out: list[tuple[int, int, int]] = []
    alive = rows
    for step in c.steps:
        ok, opt = f"s{step.index}_ok", f"s{step.index}_opt"
        kept = [r for r in alive if r[ok]]
        missing = sum(1 for r in alive if not r[ok] and r[opt])
        out.append((len(kept), len(alive) - len(kept), missing))
        alive = kept
    return out


@pytest.mark.parametrize(
    "filters",
    [
        # Rows come back: the funnel rides along on them.
        and_(cond("roic", "gte", 0.1), or_(cond("pe_ttm", "lte", 15), cond("pb", "lte", 1))),
        # Every row fails both steps: no rows, so the funnel comes from funnel_sql.
        and_(cond("roic", "gte", 50), cond("pe_ttm", "gte", 1e9)),
    ],
)
def test_funnel_matches_a_python_recount(
    con: duckdb.DuckDBPyConnection,
    synthetic_db: Path,
    live_registry: MetricRegistry,
    screen_config: ScreenConfig,
    filters: dict[str, Any],
) -> None:
    s = screen(filters=filters)
    r = _run(con, s, live_registry)
    got = [(f.remaining, f.removed, f.removed_missing) for f in r.funnel[1:]]
    assert got == _python_funnel(synthetic_db, s, live_registry, screen_config)


# --- near-miss notes (CONTRACT: NearMiss.note) -------------------------------------------------


def test_near_miss_note_small_peer_group(
    tmp_path: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    db = tmp_path / "tiny.duckdb"
    write_build(generate(60, 3, live_registry), live_registry, db)
    s = screen(
        universe={"exchanges": ["NYSE", "Nasdaq", "NYSE American"], "avg_dollar_volume_min": None},
        filters=and_(cond("fcf_yield", "pct_rank_gte", 0.0, within="sector")),
        limit=1000,
    )
    with duckdb.connect(str(db), read_only=True) as c:
        r = run_screen(c, s, live_registry, screen_config).response
    small = [nm for nm in r.near_misses if nm.note and nm.note.code is NoteCode.SMALL_PEER_GROUP]
    assert small, "the tiny build should have a sector with fewer than 5 fcf_yield values"
    for nm in r.near_misses:
        assert nm.value is None and nm.note is not None  # pct ≥ 0 fails only on a null
    min_peers = screen_config.small_peer_group_min
    assert all(
        f"Fewer than {min_peers} fcf_yield" in ((nm.note and nm.note.message) or "") for nm in small
    )


def test_near_miss_note_carries_the_stored_reason(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(filters=and_(cond("roic", "not_null", None)), limit=1000)
    r = _run(con, s, live_registry)
    assert r.near_misses
    stored = {
        (cik, code)
        for cik, code in con.execute(
            "SELECT cik, code FROM metric_notes WHERE metric_id = 'roic'"
        ).fetchall()
    }
    for nm in r.near_misses:
        assert nm.value is None and nm.note is not None
        assert (nm.cik, nm.note.code.value) in stored


def test_near_miss_note_non_positive_median(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(
        filters=and_(
            cond("sector", "eq", "Technology"), cond("net_debt", "vs_sector_median_gte", 0.5)
        ),
        limit=1000,
    )
    r = _run(con, s, live_registry)
    tech = [nm for nm in r.near_misses if nm.metric == "net_debt" and nm.value is not None]
    assert tech, "Technology's net_debt median is ≤ 0 in the synthetic model"
    for nm in tech:
        assert nm.threshold is None and nm.distance is None
        assert nm.note is not None and nm.note.code is NoteCode.NEGATIVE_DENOMINATOR


def test_near_miss_with_a_value_has_no_note(
    con: duckdb.DuckDBPyConnection, live_registry: MetricRegistry
) -> None:
    s = screen(filters=and_(cond("roic", "gte", 0.15), cond("fcf_margin", "gte", 0.1)))
    for nm in _run(con, s, live_registry).near_misses:
        assert (nm.note is None) == (nm.value is not None)
