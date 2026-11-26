"""Balance sheet and health: liquidity and interest coverage."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date
NOW = D(2026, 6, 30)


def rows_of(cik: str, basis: str, **items: float) -> list[tuple[object, ...]]:
    return [(cik, k, basis, NOW, v) for k, v in items.items()]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        *rows_of("B", "ttm", operating_income=150, interest_expense=30),
        *rows_of("B", "mrq", current_assets=500, current_liabilities=400),
        *rows_of("N", "ttm", operating_income=-20, revenue=10),  # no interest expense tag
        *rows_of("N", "mrq", current_assets=50, current_liabilities=0),
        *rows_of("Z", "ttm", operating_income=10, interest_expense=0),
        *rows_of("F", "ttm", operating_income=10),  # no interest expense tag, debt tagged as 0
        *rows_of("F", "mrq", total_debt=0),
        *rows_of("G", "ttm", operating_income=10),  # no interest expense tag, debt outstanding
        *rows_of("G", "mrq", total_debt=100),
    ]
    return run(rows, [{"cik": c} for c in "BNZFG"])


def test_values(out: pl.DataFrame) -> None:
    assert cell(out, "B", "current_ratio") == (1.25, None, None)
    assert cell(out, "B", "interest_coverage") == (5.0, None, None)


def test_no_interest_expense_needs_positive_evidence(out: pl.DataFrame) -> None:
    # interest expense tagged as zero
    assert cell(out, "Z", "interest_coverage") == (
        None, "NO_INTEREST_EXPENSE", "interest_coverage: interest expense is zero for the TTM to 2026-06-30",
    )  # fmt: skip
    # untagged, but total debt tagged as zero
    assert cell(out, "F", "interest_coverage") == (
        None, "NO_INTEREST_EXPENSE",
        "interest_coverage: no debt at 2026-06-30 and no interest expense reported for the TTM to "
        "2026-06-30",
    )  # fmt: skip
    # untagged with debt outstanding, or with debt unknown: missing, not n/m
    assert cell(out, "G", "interest_coverage") == (
        None, "MISSING_INPUT", "interest_expense_ttm: interest_expense is not reported",
    )  # fmt: skip
    assert cell(out, "N", "interest_coverage")[:2] == (None, "MISSING_INPUT")


def test_zero_current_liabilities(out: pl.DataFrame) -> None:
    assert cell(out, "N", "current_ratio") == (
        None, "NEGATIVE_DENOMINATOR", "current_liabilities_mrq ≤ 0",
    )  # fmt: skip
