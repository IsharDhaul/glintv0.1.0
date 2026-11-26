"""Universe stage, relative stats and the filter compiler (steps 2–4)."""

import math
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pytest

from glint.contracts.metrics import MetricRegistry
from glint.core.errors import ContractError
from glint.fixtures.synthetic import generate, write_build
from glint.screen.compile import compile_screen
from glint.screen.config import ScreenConfig
from glint.screen.sql import AllowList, alias
from tests.screen.helpers import and_, compiled_rows, cond, or_, screen, snapshot

ALL_EXCHANGES = ["NYSE", "Nasdaq", "NYSE American", "TXSE", "CBOE", "OTC"]


def _open_universe(**overrides: Any) -> dict[str, Any]:
    """A universe that keeps every synthetic row unless overridden."""
    base: dict[str, Any] = {
        "exchanges": ALL_EXCHANGES,
        "exclude_kinds": [],
        "include_stale": True,
        "avg_dollar_volume_min": None,
    }
    return {**base, **overrides}


def _percent_rank(values: list[float], x: float) -> float:
    """Reference percent_rank: (rank − 1) / (n − 1), rank = 1 + count of smaller values."""
    if len(values) == 1:
        return 0.0
    return sum(1 for v in values if v < x) / (len(values) - 1)


# --- 2. universe -------------------------------------------------------------------------------


def test_default_universe_matches_a_hand_filter(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    rows = compiled_rows(synthetic_db, screen(), live_registry, screen_config)
    snap = snapshot(
        synthetic_db, "ticker", "exchange", "kind", "is_stale", "has_facts", "avg_dollar_volume_3m"
    )
    expected = [
        r["ticker"]
        for r in snap
        if r["exchange"] in {"NYSE", "Nasdaq", "NYSE American", "TXSE"}
        and r["kind"] not in {"spac", "fund", "shell", "no_common_equity"}
        and not r["is_stale"]
        and r["has_facts"]
        and r["avg_dollar_volume_3m"] is not None
        and r["avg_dollar_volume_3m"] >= 1_000_000
    ]
    assert [r["ticker"] for r in rows] == expected
    assert 0 < len(expected) < len(snap)


def test_universe_options(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    snap = snapshot(
        synthetic_db, "ticker", "sector", "is_foreign_filer", "market_cap", "days_since_filing"
    )
    u = _open_universe(
        sectors_exclude=["Banks", "Utilities"],
        include_foreign_filers=False,
        market_cap_min=5e8,
        market_cap_max=2e10,
        max_days_since_filing=200,
    )
    rows = compiled_rows(synthetic_db, screen(universe=u), live_registry, screen_config)
    expected = [
        r["ticker"]
        for r in snap
        if r["sector"] not in {"Banks", "Utilities"}
        and not r["is_foreign_filer"]
        and r["market_cap"] is not None  # a null never satisfies a bound
        and 5e8 <= r["market_cap"] <= 2e10
        and r["days_since_filing"] is not None
        and r["days_since_filing"] <= 200
    ]
    assert [r["ticker"] for r in rows] == expected

    rows = compiled_rows(
        synthetic_db,
        screen(universe=_open_universe(sectors_include=["Technology"])),
        live_registry,
        screen_config,
    )
    assert rows
    assert {r["sector"] for r in rows} == {"Technology"}


def test_universe_counts_report_null_bound_exclusions(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    s = screen(universe=_open_universe(market_cap_min=1.0))
    c = compile_screen(s, live_registry, screen_config)
    with duckdb.connect(str(synthetic_db), read_only=True) as con:
        used = {k: v for k, v in c.params.items() if f"${k}" in c.counts_sql}
        total, universe, if_nulls_passed = con.execute(c.counts_sql, used).fetchone() or (0, 0, 0)
    null_mcap = sum(1 for r in snapshot(synthetic_db, "market_cap") if r["market_cap"] is None)
    assert null_mcap > 0  # foreign filers: FOREIGN_PRICE_BASIS
    assert universe == total - null_mcap
    assert if_nulls_passed == total


# --- 3. relative stats -------------------------------------------------------------------------


def test_percentiles_are_computed_after_universe_filters(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    f = and_(cond("gross_margin", "pct_rank_gte", 0.0))
    wide = compiled_rows(
        synthetic_db, screen(universe=_open_universe(), filters=f), live_registry, screen_config
    )
    narrow = compiled_rows(
        synthetic_db,
        screen(universe=_open_universe(market_cap_min=2e9), filters=f),
        live_registry,
        screen_config,
    )
    # Reference: percent_rank over the non-null values of each universe.
    for rows in (wide, narrow):
        values = [r["gross_margin"] for r in rows if r["gross_margin"] is not None]
        for r in rows:
            if r["gross_margin"] is None:
                assert r["l0_v"] is None
            else:
                assert r["l0_v"] == pytest.approx(_percent_rank(values, r["gross_margin"]))
    narrow_pct = {r["ticker"]: r["l0_v"] for r in narrow}
    changed = [
        r for r in wide if r["ticker"] in narrow_pct and r["l0_v"] != narrow_pct[r["ticker"]]
    ]
    assert changed, "narrowing the universe must change percentiles"


def test_sector_percentiles_and_medians(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    f = and_(
        cond("operating_margin", "pct_rank_gte", 0.0, within="sector"),
        cond("operating_margin", "vs_sector_median_gte", 0.0),
        cond("pe_ttm", "vs_sector_median_lte", 1.0),
    )
    rows = compiled_rows(
        synthetic_db, screen(universe=_open_universe(), filters=f), live_registry, screen_config
    )
    by_sector: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_sector.setdefault(r["sector"], []).append(r)
    checked = 0
    for members in by_sector.values():
        om = [r["operating_margin"] for r in members if r["operating_margin"] is not None]
        pe = sorted(r["pe_ttm"] for r in members if r["pe_ttm"] is not None)
        for r in members:
            if r["operating_margin"] is None:
                continue
            if len(om) < screen_config.small_peer_group_min:
                assert r["l0_v"] is None and r["l1_v"] is None
                continue
            checked += 1
            assert r["l0_v"] == pytest.approx(_percent_rank(om, r["operating_margin"]))
            # frac → difference from the median
            om_sorted = sorted(om)
            mid = len(om_sorted) // 2
            med = (
                om_sorted[mid] if len(om_sorted) % 2 else (om_sorted[mid - 1] + om_sorted[mid]) / 2
            )
            assert r["l1_v"] == pytest.approx(r["operating_margin"] - med)
        for r in members:
            if r["pe_ttm"] is None or len(pe) < screen_config.small_peer_group_min:
                continue
            mid = len(pe) // 2
            med = pe[mid] if len(pe) % 2 else (pe[mid - 1] + pe[mid]) / 2
            # x → ratio to the median, and the raw threshold it implies
            assert r["l2_v"] == pytest.approx(r["pe_ttm"] / med)
            assert r["l2_t"] == pytest.approx(med * 1.0)
    assert checked > 100


def test_small_sector_percentile_is_null(
    tmp_path: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    db = tmp_path / "tiny.duckdb"
    write_build(generate(60, 3, live_registry), live_registry, db)
    f = and_(cond("revenue_ttm", "pct_rank_gte", 0.0, within="sector", missing="pass"))
    rows = compiled_rows(
        db, screen(universe=_open_universe(), filters=f), live_registry, screen_config
    )
    counts: dict[str, int] = {}
    for r in rows:
        if r["revenue_ttm"] is not None:
            counts[r["sector"]] = counts.get(r["sector"], 0) + 1
    small = {s for s, n in counts.items() if n < screen_config.small_peer_group_min}
    assert small, "the tiny build should have a sector with fewer than 5 companies"
    for r in rows:
        if r["sector"] in small:
            assert r["l0_v"] is None
            assert r["l0_ok"] is True  # missing: pass


# --- 4. filters --------------------------------------------------------------------------------


def _check(
    rows: list[dict[str, Any]], i: int, test: Callable[[Any], bool], *, missing_passes: bool
) -> int:
    seen = 0
    for r in rows:
        v = r[f"l{i}_v"]
        if v is None:
            assert r[f"l{i}_ok"] is missing_passes
            assert r[f"l{i}_opt"] is True
        else:
            seen += 1
            assert r[f"l{i}_ok"] is bool(test(v)), (r["ticker"], v)
    return seen


def test_every_comparator(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    tol = screen_config.float_tolerance
    f = and_(
        cond("roic", "gt", 0.1),
        cond("roic", "gte", 0.1),
        cond("pe_ttm", "lt", 15),
        cond("pe_ttm", "lte", 15, missing="pass"),
        cond("pe_ttm", "between", [8, 20]),
        cond("sector", "eq", "Technology"),
        cond("sector", "neq", "Technology"),
        cond("exchange", "in", ["NYSE", "Nasdaq"]),
        cond("dividend_yield", "is_null"),
        cond("dividend_yield", "not_null"),
        cond("dps_no_cut_5y", "eq", True),
        cond("gross_margin", "pct_rank_lte", 0.25),
    )
    rows = compiled_rows(
        synthetic_db, screen(universe=_open_universe(), filters=f), live_registry, screen_config
    )
    assert _check(rows, 0, lambda v: v > 0.1 + tol, missing_passes=False)
    assert _check(rows, 1, lambda v: v >= 0.1 - tol, missing_passes=False)
    assert _check(rows, 2, lambda v: v < 15 - tol, missing_passes=False)
    assert _check(rows, 3, lambda v: v <= 15 + tol, missing_passes=True)
    assert _check(rows, 4, lambda v: 8 - tol <= v <= 20 + tol, missing_passes=False)
    assert _check(rows, 5, lambda v: v == "Technology", missing_passes=False)
    assert _check(rows, 6, lambda v: v != "Technology", missing_passes=False)
    assert _check(rows, 7, lambda v: v in {"NYSE", "Nasdaq"}, missing_passes=False)
    assert _check(rows, 11, lambda v: v <= 0.25 + tol, missing_passes=False)
    for r in rows:
        assert r["l8_ok"] is (r["dividend_yield"] is None) is r["l8_opt"]
        assert r["l9_ok"] is (r["dividend_yield"] is not None)
        assert r["l10_ok"] is (r["dps_no_cut_5y"] is True)


def test_float_tolerance_at_the_threshold(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    """A value a hair under the threshold (float noise) still passes `gte`."""
    target = next(r for r in snapshot(synthetic_db, "ticker", "roic") if r["roic"] is not None)
    x = target["roic"]
    noisy = x + screen_config.float_tolerance / 10
    s = screen(
        universe=_open_universe(),
        filters=and_(
            cond("ticker", "eq", target["ticker"]),
            cond("roic", "gte", noisy),
            cond("roic", "lte", x - screen_config.float_tolerance / 10),
            cond("roic", "gt", x),
        ),
    )
    (row,) = [r for r in compiled_rows(synthetic_db, s, live_registry, screen_config) if r["l0_ok"]]
    assert row["l1_ok"] is True
    assert row["l2_ok"] is True
    assert row["l3_ok"] is False


def test_and_or_nesting(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    f = and_(
        or_(cond("roic", "gte", 0.2), and_(cond("pe_ttm", "lte", 12), cond("pb", "lte", 2))),
        cond("sector", "neq", "Banks"),
    )
    rows = compiled_rows(
        synthetic_db, screen(universe=_open_universe(), filters=f), live_registry, screen_config
    )
    for r in rows:
        inner = r["l1_ok"] and r["l2_ok"]
        assert r["s1_ok"] is bool(r["l0_ok"] or inner)
        assert r["s2_ok"] is r["l3_ok"]


def test_missing_policy_pass_and_fail(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    f = and_(
        cond("net_debt_to_ebitda", "lte", 2.0, missing="pass"),
        cond("net_debt_to_ebitda", "lte", 2.0, missing="fail"),
    )
    rows = compiled_rows(
        synthetic_db, screen(universe=_open_universe(), filters=f), live_registry, screen_config
    )
    nulls = [r for r in rows if r["net_debt_to_ebitda"] is None]
    assert nulls  # banks etc. are n/m
    assert all(r["l0_ok"] and not r["l1_ok"] and r["l1_opt"] for r in nulls)


def test_near_miss_distances(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    f = and_(
        cond("roic", "gte", 0.15),
        cond("pe_ttm", "between", [8, 20]),
        cond("gross_margin", "pct_rank_gte", 0.7),
        cond("net_debt", "lte", 0),
    )
    rows = compiled_rows(
        synthetic_db, screen(universe=_open_universe(), filters=f), live_registry, screen_config
    )
    for r in rows:
        if r["roic"] is not None:
            assert r["l0_d"] == pytest.approx(abs(r["roic"] - 0.15) / 0.15)
        if r["pe_ttm"] is not None:
            bound = 8 if r["pe_ttm"] < 8 else 20
            assert r["l1_d"] == pytest.approx(abs(r["pe_ttm"] - bound) / bound)
        if r["l2_v"] is not None:
            assert r["l2_d"] == pytest.approx(abs(r["l2_v"] - 0.7))
        if r["net_debt"] is not None:  # threshold 0: the absolute gap
            assert r["l3_d"] == pytest.approx(abs(r["net_debt"]))
        else:
            assert r["l3_d"] is None
        assert all(not (isinstance(v, float) and math.isnan(v)) for v in r.values())


# --- injection --------------------------------------------------------------------------------


def test_identifiers_come_only_from_the_allow_list(live_registry: MetricRegistry) -> None:
    allow = AllowList.for_registry(live_registry)
    assert allow.ident("roic") == '"roic"'
    for bad in ("roic; DROP TABLE", 'roic"', "ROIC", "build_meta", "roic --"):
        with pytest.raises(ContractError):
            allow.ident(bad)
    with pytest.raises(ContractError):
        alias("l0_", 'v"; --')


def test_text_values_are_bound_not_spliced(
    synthetic_db: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    evil = "x'); DROP TABLE metrics_snapshot; --"
    s = screen(filters=and_(cond("name", "eq", evil), cond("ticker", "in", [evil, "SYN0001"])))
    c = compile_screen(s, live_registry, screen_config)
    assert evil not in c.sql
    assert evil in c.params.values()
    assert compiled_rows(synthetic_db, s, live_registry, screen_config)
    with duckdb.connect(str(synthetic_db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM metrics_snapshot").fetchone() == (800,)


def test_null_exchange_counts_as_missing_in_the_universe(
    synthetic_db: Path, tmp_path: Path, live_registry: MetricRegistry, screen_config: ScreenConfig
) -> None:
    db = tmp_path / "copy.duckdb"
    shutil.copy(synthetic_db, db)
    with duckdb.connect(str(db)) as con:
        con.execute(
            "UPDATE metrics_snapshot SET exchange = NULL WHERE ticker IN ('SYN0001', 'SYN0002')"
        )
    c = compile_screen(screen(universe=_open_universe()), live_registry, screen_config)
    with duckdb.connect(str(db), read_only=True) as con:
        used = {k: v for k, v in c.params.items() if f"${k}" in c.counts_sql}
        total, universe, if_nulls_passed = con.execute(c.counts_sql, used).fetchone() or (0, 0, 0)
    assert universe == total - 2
    assert if_nulls_passed == total
