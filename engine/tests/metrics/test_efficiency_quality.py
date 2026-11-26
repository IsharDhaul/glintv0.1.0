"""Efficiency (days, turnover, capex) and quality (accruals, payout, dividend record)."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date
NOW, YEAR_AGO = D(2026, 6, 30), D(2025, 6, 30)
FY_ENDS = [D(2025, 12, 31), D(2024, 12, 31), D(2023, 12, 31), D(2022, 12, 31), D(2021, 12, 31)]


def rows_of(cik: str, basis: str, end: date, **items: float) -> list[tuple[object, ...]]:
    return [(cik, k, basis, end, v, k == "fcf") for k, v in items.items()]


def dps(cik: str, values: list[float]) -> list[tuple[object, ...]]:
    return [(cik, "dps_declared", "fy", e, v) for e, v in zip(FY_ENDS, values, strict=False)]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        *rows_of("E", "ttm", NOW, revenue=1000, cost_of_revenue=600, capex=80, dna=40,
                 net_income=100, cfo=180, dividends_paid=40, fcf=130),
        *rows_of("E", "mrq", NOW, receivables=100, inventory=120, accounts_payable=60,
                 total_assets=2000),
        *rows_of("E", "mrq", YEAR_AGO, total_assets=1800),
        *dps("E", [0.995, 1.00, 0.90, 0.85, 0.80]),  # newest first: −0.5% is within 1%
        # F: no inventory tag; a loss; a 5% dividend cut
        *rows_of("F", "ttm", NOW, revenue=500, cost_of_revenue=100, net_income=-20,
                 dividends_paid=10, fcf=-5),
        *rows_of("F", "mrq", NOW, receivables=50, accounts_payable=10),
        *dps("F", [0.95, 1.00, 1.00, 1.00, 1.00]),
        # S: three fiscal years of dividends
        *rows_of("S", "ttm", NOW, revenue=10),
        *dps("S", [0.3, 0.3, 0.3]),
    ]  # fmt: skip
    return run(rows, [{"cik": c} for c in "EFS"])


@pytest.mark.parametrize(
    ("metric_id", "value", "code"),
    [
        ("asset_turnover", 1000 / 1900, None),
        ("dso", 36.5, None),  # 100 / 1,000 × 365
        ("dio", 73.0, None),  # 120 / 600 × 365
        ("dpo", 36.5, None),  # 60 / 600 × 365
        ("cash_conversion_cycle", 73.0, None),  # 36.5 + 73 − 36.5
        ("capex_to_revenue", 0.08, None),
        ("capex_to_dna", 2.0, None),
        ("accruals_ratio", -80 / 1900, None),  # (100 − 180) / ((2,000 + 1,800) / 2)
        ("payout_ratio", 0.4, None),
        ("fcf_payout_ratio", 40 / 130, "DERIVED_INPUT"),
    ],
)
def test_values(out: pl.DataFrame, metric_id: str, value: float, code: str | None) -> None:
    v, c, _ = cell(out, "E", metric_id)
    assert v == pytest.approx(value, rel=1e-12)
    assert c == code


def test_dividend_record(out: pl.DataFrame) -> None:
    assert cell(out, "E", "dps_no_cut_5y") == (True, None, None)
    assert cell(out, "F", "dps_no_cut_5y") == (False, None, None)
    v, c, m = cell(out, "S", "dps_no_cut_5y")
    assert (v, c) == (None, "INSUFFICIENT_HISTORY")
    assert m == "dps_declared_fy3: no fiscal year 3 years before the latest"


def test_missing_inventory_carries_into_the_cycle(out: pl.DataFrame) -> None:
    assert cell(out, "F", "dso")[0] == pytest.approx(36.5)
    v, c, m = cell(out, "F", "dio")
    assert (v, c) == (None, "MISSING_INPUT")
    assert m is not None and m.startswith("inventory_mrq: inventory is not reported")
    assert cell(out, "F", "cash_conversion_cycle")[1:] == (c, m)


def test_payout_with_loss_or_negative_fcf(out: pl.DataFrame) -> None:
    assert cell(out, "F", "payout_ratio") == (None, "NEGATIVE_DENOMINATOR", "net_income_ttm ≤ 0")
    assert cell(out, "F", "fcf_payout_ratio") == (None, "NEGATIVE_DENOMINATOR", "fcf_ttm ≤ 0")
