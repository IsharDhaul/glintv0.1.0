"""data_coverage and days_since_filing."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date
NOW = D(2026, 6, 30)


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        ("A", "revenue", "ttm", NOW, 10),
        ("A", "net_income", "ttm", NOW, 1),
        ("A", "cfo", "ttm", D(2026, 3, 31), 1),  # behind the common TTM end: not counted
        ("A", "cash", "mrq", NOW, 5),
        ("A", "total_assets", "mrq", NOW, 50),
        ("A", "shares_outstanding", "mrq", D(2026, 7, 25), 3),
        ("A", "gross_profit", "ttm", NOW, 4),  # not a core item
    ]
    companies = [
        {"cik": "A", "last_annual_date": D(2026, 2, 20), "last_quarterly_date": D(2026, 8, 1)},
        {"cik": "B", "last_annual_date": None, "last_quarterly_date": None, "has_facts": False},
    ]
    return run(rows, companies)


def test_coverage(out: pl.DataFrame) -> None:
    # revenue, net_income, cash, total_assets, shares_outstanding = 5 of 20
    assert cell(out, "A", "data_coverage") == (0.25, None, None)
    assert cell(out, "B", "data_coverage") == (0.0, None, None)


def test_days_since_filing(out: pl.DataFrame) -> None:
    assert cell(out, "A", "days_since_filing") == (89.0, None, None)  # 2026-08-01 → 2026-10-29
    assert cell(out, "B", "days_since_filing") == (
        None, "MISSING_INPUT", "days_since_filing: no 10-K, 10-Q, 20-F or 40-F on file",
    )  # fmt: skip
