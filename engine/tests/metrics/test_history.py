"""metric_history: per-period series for the drawer sparklines (FY last 10, TTM last 12)."""

from datetime import date, timedelta

import polars as pl
import pytest

from glint.metrics.history import HISTORY_METRICS, build_history
from glint.metrics.params import Params
from tests.metrics.helpers import companies, fin

D = date
E0, E1 = D(2026, 6, 30), D(2025, 6, 30)


@pytest.fixture(scope="module")
def hist() -> pl.DataFrame:
    rows: list[tuple[object, ...]] = []
    for basis, end, scale in (("ttm", E0, 1.0), ("ttm", E1, 0.8), ("fy", D(2025, 12, 31), 0.9)):
        rows += [
            ("A", "revenue", basis, end, 1000 * scale),
            ("A", "gross_profit", basis, end, 400 * scale),
            ("A", "operating_income", basis, end, 100 * scale),
            ("A", "fcf", basis, end, 50 * scale, True),
            ("A", "pretax_income", basis, end, 80 * scale),
            ("A", "income_tax", basis, end, 16 * scale),
            ("A", "ebitda", basis, end, 120 * scale, True),
        ]
    rows += [
        ("A", "diluted_shares", "q", E0, 105),
        ("A", "diluted_shares", "q", E1, 100),
        ("A", "total_debt", "mrq", E0, 300, True),
        ("A", "equity", "mrq", E0, 500),
        ("A", "cash", "mrq", E0, 100),
        ("A", "total_debt", "mrq", E1, 300, True),
        ("A", "equity", "mrq", E1, 400),
        ("A", "cash", "mrq", E1, 100),
        ("K", "revenue", "ttm", E0, 10),
        ("K", "gross_profit", "ttm", E0, 5),
    ]
    cos = companies([{"cik": "A"}, {"cik": "K", "sector": "Banks"}])
    return build_history(cos, fin(rows), Params(), window=45)


def point(h: pl.DataFrame, cik: str, mid: str, basis: str, end: date) -> float | None:
    hit = h.filter(
        (pl.col("cik") == cik) & (pl.col("metric_id") == mid) & (pl.col("basis") == basis)
        & (pl.col("period_end") == end)
    )  # fmt: skip
    return hit["value"][0] if hit.height else None


def test_series(hist: pl.DataFrame) -> None:
    assert set(hist["metric_id"].unique()) <= set(HISTORY_METRICS)
    assert point(hist, "A", "revenue_ttm", "ttm", E0) == 1000
    assert point(hist, "A", "revenue_ttm", "ttm", E1) == 800
    assert point(hist, "A", "revenue_ttm", "fy", D(2025, 12, 31)) == 900
    assert point(hist, "A", "operating_margin", "ttm", E1) == pytest.approx(0.1)
    assert point(hist, "A", "gross_margin", "fy", D(2025, 12, 31)) == pytest.approx(0.4)
    assert point(hist, "A", "fcf_margin", "ttm", E0) == pytest.approx(0.05)
    assert point(hist, "A", "share_count_change_yoy", "ttm", E0) == pytest.approx(0.05)


def test_growth_and_leverage_points(hist: pl.DataFrame) -> None:
    assert point(hist, "A", "revenue_growth_yoy", "ttm", E0) == pytest.approx(0.25)  # 1,000/800
    # net debt 300 − 100 = 200 over EBITDA 100 + D&A 20 = 120 (TTM to E0)
    assert point(hist, "A", "net_debt_to_ebitda", "ttm", E0) == pytest.approx(200 / 120)


def test_roic_point(hist: pl.DataFrame) -> None:
    # NOPAT 100 × (1 − 16/80) = 80; IC (300 + 500 − 100) = 700 and (300 + 400 − 100) = 600
    assert point(hist, "A", "roic", "ttm", E0) == pytest.approx(80 / 650)
    assert point(hist, "A", "roic", "ttm", E1) is None  # no balance sheet a year before


def test_applicability_and_no_null_rows(hist: pl.DataFrame) -> None:
    assert point(hist, "K", "gross_margin", "ttm", E0) is None  # n/m for banks: no series
    assert point(hist, "K", "revenue_ttm", "ttm", E0) == 10
    assert hist["value"].null_count() == 0


def test_share_count_point_without_a_flow_row() -> None:
    """The latest diluted count's date has no TTM row (here a 16-week quarter ends 2026-09-05):
    the series still ends there, as the snapshot's share_count_change_yoy does."""
    q_end, ago = D(2026, 9, 5), D(2025, 9, 6)
    rows: list[tuple[object, ...]] = [
        ("A", "revenue", "ttm", E0, 1000),
        ("A", "diluted_shares", "q", E0, 104),
        ("A", "diluted_shares", "q", E1, 100),
        ("A", "diluted_shares", "q", q_end, 99),
        ("A", "diluted_shares", "q", ago, 110),
    ]
    h = build_history(companies([{"cik": "A"}]), fin(rows), Params(), window=45)
    assert point(h, "A", "share_count_change_yoy", "ttm", q_end) == pytest.approx(-0.1)
    assert point(h, "A", "share_count_change_yoy", "ttm", E0) == pytest.approx(0.04)
    assert point(h, "A", "revenue_ttm", "ttm", q_end) is None  # no flow at that date: no point
    assert h.filter(pl.col("metric_id") == "revenue_ttm").height == 1


def test_cap_currency_and_eligibility() -> None:
    fy_end = D(2025, 12, 31)
    rows: list[tuple[object, ...]] = []
    for k in range(15):  # 15 fiscal years and 15 TTM ends
        rows.append(("A", "revenue", "fy", D(2025 - k, 12, 31), 100 + k))
        rows.append(("A", "revenue", "ttm", E0 - timedelta(days=91 * k), 100))
    rows += [("E", "revenue", "fy", fy_end, 100), ("E", "operating_income", "fy", fy_end, 10)]
    rows += [
        ("C", "revenue", "fy", fy_end, 100), ("C", "ebitda", "fy", fy_end, 50),
        ("C", "total_debt", "fy", fy_end, 80), ("C", "cash", "fy", fy_end, 30),
    ]  # fmt: skip
    cos = companies([
        {"cik": "A"},
        {"cik": "E", "reporting_currency": "EUR"},
        {"cik": "C", "is_foreign_filer": True, "last_annual_form": "40-F"},
    ])  # fmt: skip
    h = build_history(cos, fin(rows), Params(), window=45)
    a = h.filter((pl.col("cik") == "A") & (pl.col("metric_id") == "revenue_ttm"))
    assert a.filter(pl.col("basis") == "fy").height == 10
    assert a.filter(pl.col("basis") == "ttm").height == 12
    assert a.filter(pl.col("basis") == "fy")["period_end"].min() == D(2016, 12, 31)
    e = h.filter(pl.col("cik") == "E")
    assert "revenue_ttm" not in e["metric_id"].to_list()  # a EUR amount is not a USD series
    assert point(h, "E", "operating_margin", "fy", fy_end) == pytest.approx(0.1)
    assert point(h, "C", "net_debt_to_ebitda", "fy", fy_end) == pytest.approx(1.0)  # 40-F USD
