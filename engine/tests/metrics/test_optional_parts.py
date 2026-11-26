"""Untagged balance-sheet parts count as none only if they weren't tagged a year earlier either
(user decision 2026-10-30, after the NVDA hand-check: FY2026 marketable securities untagged)."""

from datetime import date

import polars as pl
import pytest

from glint.financials.concepts import load_concepts
from glint.metrics.history import build_history
from glint.metrics.params import Params
from tests.metrics.frames import cell, run
from tests.metrics.helpers import companies, fin

D = date
NOW, Y1, Y2 = D(2026, 6, 30), D(2025, 6, 30), D(2024, 6, 30)


def bs(cik: str, end: date, **items: float) -> list[tuple[object, ...]]:
    return [(cik, k, "mrq", end, v, k == "total_debt") for k, v in items.items()]


def base(cik: str) -> list[tuple[object, ...]]:
    return [
        (cik, "operating_income", "ttm", NOW, 100),
        (cik, "ebitda", "ttm", NOW, 120, True),
        (cik, "pretax_income", "ttm", NOW, 100),
        (cik, "income_tax", "ttm", NOW, 20),
        *bs(cik, NOW, total_debt=200, cash=50, equity=300),
        *bs(cik, Y1, total_debt=200, cash=50, equity=300),
        *bs(cik, Y2, total_debt=200, cash=50, equity=300),
    ]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        *base("N"),  # never tags short-term investments: none
        *base("G"), *bs("G", Y1, st_investments=40),  # tagged a year ago, gone now: missing
        *base("H"), *bs("H", Y2, st_investments=40),  # tagged two years ago only
    ]  # fmt: skip
    return run(rows, [{"cik": c} for c in "NGH"])


def test_never_tagged_counts_as_none(out: pl.DataFrame) -> None:
    assert cell(out, "N", "net_debt_to_ebitda")[0] == pytest.approx(150 / 120)


def test_tagged_a_year_ago_is_missing_now(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "G", "net_debt_to_ebitda")
    assert (v, c) == (None, "MISSING_INPUT")
    assert m == "st_investments_mrq: tagged at 2025-06-30 but not at 2026-06-30"


def test_year_ago_side_checks_two_years_back(out: pl.DataFrame) -> None:
    # H: now fine (nothing a year ago), but the year-ago side had it two years back → ROIC missing
    assert cell(out, "H", "net_debt_to_ebitda")[0] == pytest.approx(150 / 120)
    v, c, m = cell(out, "H", "roic")
    assert (v, c) == (None, "MISSING_INPUT")
    assert m == "st_investments_mrq_1y: tagged at 2024-06-30 but not at 2025-06-30"


def test_current_debt_keeps_counting_as_none_with_last_years_value() -> None:
    """User decision: debt_current is excluded from the rule (nothing due within a year is
    common); the ⓘ note gives the value a year earlier instead."""
    rows = [
        ("D", "operating_income", "ttm", NOW, 100),
        *bs("D", NOW, current_assets=500, cash=100, current_liabilities=200, ppe_net=300),
        *bs("D", Y1, debt_current=40),
    ]
    out = run(rows, [{"cik": "D"}])
    v, c, m = cell(out, "D", "greenblatt_roc")
    assert v == pytest.approx(100 / ((500 - 100) - (200 - 0) + 300))  # debt_current as none
    assert c == "DERIVED_INPUT"
    assert (
        m is not None and "debt_current_mrq (not tagged, counted as none; 40 a year earlier)" in m
    )


def test_history_follows_the_same_rule() -> None:
    fy0, fy1 = D(2025, 12, 31), D(2024, 12, 31)
    rows = [
        ("A", "revenue", "fy", fy0, 100), ("A", "ebitda", "fy", fy0, 50),
        ("A", "total_debt", "fy", fy0, 80), ("A", "cash", "fy", fy0, 30),
        ("A", "revenue", "fy", fy1, 90), ("A", "st_investments", "fy", fy1, 10),
    ]  # fmt: skip
    h = build_history(companies([{"cik": "A"}]), fin(rows), Params(), window=45)
    hit = h.filter((pl.col("metric_id") == "net_debt_to_ebitda") & (pl.col("period_end") == fy0))
    assert hit.is_empty()  # tagged at FY2024, untagged at FY2025: no point, not a guess
    _ = load_concepts
