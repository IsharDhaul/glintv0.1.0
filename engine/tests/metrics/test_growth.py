"""Growth: TTM vs the TTM a year earlier, FY CAGRs, margin changes, share count change."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date
NOW, YEAR_AGO = D(2026, 6, 30), D(2025, 6, 30)
FY_ENDS = [D(2025, 12, 31), D(2024, 12, 31), D(2023, 12, 31), D(2022, 12, 31), D(2021, 12, 31),
           D(2020, 12, 31)]  # fmt: skip


def flows(cik: str, end: date, basis: str = "ttm", **items: float) -> list[tuple[object, ...]]:
    return [(cik, k, basis, end, v, k == "fcf") for k, v in items.items()]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        *flows("G", NOW, revenue=1200, gross_profit=600, operating_income=240, fcf=150),
        *flows("G", YEAR_AGO, revenue=1000, gross_profit=450, operating_income=150, fcf=100),
        *(r for e, v in zip(FY_ENDS, [1100, 1000, 900, 800, 700, 500], strict=True)
          for r in flows("G", e, "fy", revenue=v)),
        ("G", "diluted_shares", "q", NOW, 105),
        ("G", "diluted_shares", "q", YEAR_AGO, 100),
        # H: a zero prior revenue, a prior operating loss, only 2 fiscal years
        *flows("H", NOW, revenue=50, operating_income=5, fcf=-3),
        *flows("H", YEAR_AGO, revenue=0, operating_income=-5, fcf=2),
        *flows("H", FY_ENDS[0], "fy", revenue=40),
        *flows("H", FY_ENDS[1], "fy", revenue=-1),
        # J: no TTM a year earlier
        *flows("J", NOW, revenue=10),
    ]  # fmt: skip
    return run(rows, [{"cik": c} for c in "GHJ"])


@pytest.mark.parametrize(
    ("metric_id", "value", "code"),
    [
        ("revenue_growth_yoy", 0.2, None),  # 1,200 / 1,000 − 1
        ("revenue_cagr_3y", 0.111990, None),  # (1,100 / 800)^(1/3) − 1
        ("revenue_cagr_5y", 0.170804, None),  # (1,100 / 500)^(1/5) − 1
        ("ebit_growth_yoy", 0.6, None),  # 240 / 150 − 1
        ("fcf_growth_yoy", 0.5, "DERIVED_INPUT"),  # 150 / 100 − 1
        ("gross_margin_change_yoy", 0.05, None),  # 600/1,200 − 450/1,000
        ("operating_margin_change_yoy", 0.05, None),  # 240/1,200 − 150/1,000
        ("share_count_change_yoy", 0.05, None),  # 105 / 100 − 1
        ("rule_of_40", 0.325, "DERIVED_INPUT"),  # 0.2 + 150/1,200
    ],
)
def test_values(out: pl.DataFrame, metric_id: str, value: float, code: str | None) -> None:
    v, c, _ = cell(out, "G", metric_id)
    assert v == pytest.approx(value, abs=1e-6)
    assert c == code


def test_non_positive_prior(out: pl.DataFrame) -> None:
    assert cell(out, "H", "revenue_growth_yoy") == (
        None, "NEGATIVE_DENOMINATOR", "revenue_ttm_1y ≤ 0",
    )  # fmt: skip
    assert cell(out, "H", "ebit_growth_yoy")[:2] == (None, "NEGATIVE_DENOMINATOR")
    assert cell(out, "H", "fcf_growth_yoy")[0] == pytest.approx(-2.5)  # −3 / 2 − 1
    # a zero prior revenue makes last year's margin n/m, so the change is too
    assert cell(out, "H", "operating_margin_change_yoy")[:2] == (None, "NEGATIVE_DENOMINATOR")


def test_too_few_fiscal_years(out: pl.DataFrame) -> None:
    assert cell(out, "H", "revenue_cagr_3y") == (
        None, "INSUFFICIENT_HISTORY", "revenue_fy3: no fiscal year 3 years before the latest",
    )  # fmt: skip


def test_no_year_ago(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "J", "revenue_growth_yoy")
    assert (v, c) == (None, "INSUFFICIENT_HISTORY")
    assert m == "revenue_ttm_1y: no TTM period about a year before the latest"
    assert cell(out, "J", "share_count_change_yoy")[1] == "INSUFFICIENT_HISTORY"
