"""Flags: questions with evidence, thresholds from config/thresholds.yaml."""

import json
from datetime import date

import polars as pl
import pytest

from glint.flags.engine import evaluate_flags, load_rules
from tests.metrics.frames import run
from tests.metrics.helpers import fin

D = date
NOW, YEAR_AGO = D(2026, 6, 30), D(2025, 6, 30)
FY0, FY1 = D(2025, 12, 31), D(2024, 12, 31)

ROWS = [
    # F1: 7.3% more diluted shares
    ("F1", "diluted_shares", "q", NOW, 107.3),
    ("F1", "diluted_shares", "q", YEAR_AGO, 100),
    # F2: profits without cash two years running; receivables and inventory racing revenue
    ("F2", "net_income", "fy", FY0, 10), ("F2", "cfo", "fy", FY0, -5),
    ("F2", "net_income", "fy", FY1, 8), ("F2", "cfo", "fy", FY1, -2),
    ("F2", "revenue", "ttm", NOW, 1000), ("F2", "revenue", "ttm", YEAR_AGO, 950),
    ("F2", "receivables", "mrq", NOW, 120), ("F2", "receivables", "mrq", YEAR_AGO, 90),
    ("F2", "inventory", "mrq", NOW, 150), ("F2", "inventory", "mrq", YEAR_AGO, 100),
    # F3: negative equity
    ("F3", "equity", "mrq", NOW, -10),
    # F4: thin coverage, heavy SBC, goodwill-heavy
    ("F4", "operating_income", "ttm", NOW, 30), ("F4", "interest_expense", "ttm", NOW, 20),
    ("F4", "revenue", "ttm", NOW, 100), ("F4", "sbc", "ttm", NOW, 20),
    ("F4", "goodwill", "mrq", NOW, 400), ("F4", "intangibles", "mrq", NOW, 200),
    ("F4", "total_assets", "mrq", NOW, 1000),
    # F5: FY2025 revenue revised from 95 to 100 in a later filing
    ("F5", "revenue", "fy", FY0, 100, False, 95), ("F5", "revenue", "ttm", NOW, 110),
    # F6: nothing to ask
    ("F6", "revenue", "ttm", NOW, 100),
]  # fmt: skip

COMPANIES = [
    {"cik": "F1"}, {"cik": "F2"},
    {"cik": "F3", "nt_filing_12m": True, "fy_end_changed": True,
     "last_annual_date": D(2025, 6, 1)},
    {"cik": "F4"}, {"cik": "F5"}, {"cik": "F6"},
]  # fmt: skip


@pytest.fixture(scope="module")
def flags() -> pl.DataFrame:
    return evaluate_flags(run(ROWS, COMPANIES), fin(ROWS), load_rules())


def of(flags: pl.DataFrame, cik: str) -> dict[str, tuple[str, dict[str, object]]]:
    rows = flags.filter(pl.col("cik") == cik).iter_rows(named=True)
    return {r["flag_id"]: (r["question"], json.loads(r["evidence"])) for r in rows}


def test_dilution(flags: pl.DataFrame) -> None:
    q, ev = of(flags, "F1")["dilution"]
    assert q == "Share count is up 7.3% in a year. What's driving the dilution?"
    assert ev == {"share_count_change_yoy": pytest.approx(0.073)}


def test_earnings_receivables_inventory(flags: pl.DataFrame) -> None:
    f = of(flags, "F2")
    assert set(f) == {"earnings_without_cash", "receivables_outpacing", "inventory_build"}
    assert f["earnings_without_cash"][1] == {
        "net_income_fy0": 10.0, "cfo_fy0": -5.0, "net_income_fy1": 8.0, "cfo_fy1": -2.0,
    }  # fmt: skip
    ev = f["receivables_outpacing"][1]
    # DSO 120/1,000×365 = 43.8 vs 90/950×365 = 34.58 → +26.7%; revenue +5.3%
    assert ev["dso_change_yoy"] == pytest.approx((120 / 1000) / (90 / 950) - 1)
    assert ev["revenue_growth_yoy"] == pytest.approx(1000 / 950 - 1)
    # inventory +50% vs revenue +5.3% → 44.7 pp
    assert f["inventory_build"][1]["inventory_minus_revenue_growth"] == pytest.approx(
        0.5 - (1000 / 950 - 1)
    )


def test_filing_flags(flags: pl.DataFrame) -> None:
    f = of(flags, "F3")
    assert set(f) == {"negative_equity", "late_filer", "fy_change", "stale_filing"}
    assert f["negative_equity"][1] == {"equity_mrq": -10.0}
    assert f["stale_filing"][1] == {"last_annual_date": "2025-06-01"}


def test_coverage_sbc_goodwill(flags: pl.DataFrame) -> None:
    f = of(flags, "F4")
    assert set(f) == {"thin_coverage", "heavy_sbc", "goodwill_heavy"}
    assert f["thin_coverage"][1] == {"interest_coverage": 1.5}
    assert f["goodwill_heavy"][1] == {"goodwill_to_assets": pytest.approx(0.6)}


def test_restated(flags: pl.DataFrame) -> None:
    q, ev = of(flags, "F5")["restated"]
    assert q == "Prior figures were revised. What changed?"
    assert ev == {
        "line_item": "revenue", "period_end": "2025-12-31", "first_filed_value": 95.0,
        "value": 100.0, "change": pytest.approx(100 / 95 - 1),
    }  # fmt: skip


def test_quiet_company(flags: pl.DataFrame) -> None:
    assert of(flags, "F6") == {}


def test_zero_or_negative_denominators_never_flag() -> None:
    rows = [
        ("Z", "revenue", "ttm", NOW, 100), ("Z", "revenue", "ttm", YEAR_AGO, 100),
        ("Z", "inventory", "mrq", NOW, 0), ("Z", "inventory", "mrq", YEAR_AGO, 0),
        ("Z", "receivables", "mrq", NOW, 0), ("Z", "receivables", "mrq", YEAR_AGO, 0),
        ("Y", "revenue", "ttm", NOW, 100), ("Y", "revenue", "ttm", YEAR_AGO, 100),
        ("Y", "inventory", "mrq", NOW, 50), ("Y", "inventory", "mrq", YEAR_AGO, 0),
        ("X", "revenue", "ttm", NOW, 100), ("X", "revenue", "ttm", YEAR_AGO, -10),
        ("X", "inventory", "mrq", NOW, 50), ("X", "inventory", "mrq", YEAR_AGO, 40),
    ]  # fmt: skip
    flags = evaluate_flags(run(rows, [{"cik": c} for c in "ZYX"]), fin(rows), load_rules())
    assert flags.height == 0
