"""Piotroski F-score: the 9 tests on FY0 vs FY1 (assets at the start of each year).

P (FY ends 2025, 2024, 2023):        FY0     FY1     FY2
  net income                         120      80
  CFO                                150     100
  total assets                     1,100   1,000     900
  long-term debt                     200     250
  current assets / liabilities   500/250 400/250
  diluted shares                     100     100
  gross profit / revenue       450/1,000 380/900
 1 ROA 120/1,000 > 0 ✓   2 CFO > 0 ✓   3 ΔROA 0.12 − 80/900 > 0 ✓   4 CFO > NI ✓
 5 leverage 200/1,050 < 250/950 ✓   6 current ratio 2.0 > 1.6 ✓   7 shares 100 ≤ 100 ✓
 8 gross margin 0.45 > 0.422 ✓   9 turnover 1,000/1,000 = 900/900, not up ✗   → 8
"""

from datetime import date

import polars as pl
import pytest

from glint.metrics.defs.composites import PIOTROSKI_TESTS, piotroski_parts
from glint.metrics.params import Params
from tests.metrics.frames import cell, run

D = date
FY0, FY1, FY2 = D(2025, 12, 31), D(2024, 12, 31), D(2023, 12, 31)


def fy(cik: str, end: date, **items: float) -> list[tuple[object, ...]]:
    return [(cik, k, "fy", end, v) for k, v in items.items()]


def company(cik: str, *, drop: str | None = None) -> list[tuple[object, ...]]:
    rows = [
        *fy(cik, FY0, net_income=120, cfo=150, total_assets=1100, debt_noncurrent=200,
            current_assets=500, current_liabilities=250, diluted_shares=100, gross_profit=450,
            revenue=1000),
        *fy(cik, FY1, net_income=80, cfo=100, total_assets=1000, debt_noncurrent=250,
            current_assets=400, current_liabilities=250, diluted_shares=100, gross_profit=380,
            revenue=900),
        *fy(cik, FY2, total_assets=900, revenue=850),
    ]  # fmt: skip
    return [r for r in rows if not (drop and r[1] == drop and r[3] == FY1)]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [*company("P"), *company("R", drop="debt_noncurrent"), *company("K"), *company("M")]
    cos = [{"cik": "P"}, {"cik": "R"}, {"cik": "K", "sector": "Banks"},
           {"cik": "M", "sector": "Capital Markets"}]  # fmt: skip
    return run(rows, cos)


def test_score(out: pl.DataFrame) -> None:
    assert cell(out, "P", "piotroski_f") == (8.0, None, None)
    assert cell(out, "M", "piotroski_f")[0] == 8.0  # capital markets: ok (§4.5)


def test_parts(out: pl.DataFrame) -> None:
    parts = out.filter(pl.col("cik") == "P").select(**piotroski_parts(Params())).row(0, named=True)
    assert list(parts) == list(PIOTROSKI_TESTS)
    assert [parts[t] for t in PIOTROSKI_TESTS] == [1.0] * 8 + [0.0]


def test_missing_component(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "R", "piotroski_f")
    assert (v, c) == (None, "MISSING_INPUT")
    assert m is not None and m.startswith("debt_noncurrent_fy1: nothing for 2024-12-31")


def test_bank(out: pl.DataFrame) -> None:
    assert cell(out, "K", "piotroski_f")[1] == "NOT_APPLICABLE_SECTOR"
