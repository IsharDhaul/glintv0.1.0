"""Hand-verified filing values (tests/golden/golden_values.csv) match the normalized FY series."""

import csv
from datetime import date
from pathlib import Path

import pytest

from glint.contracts.enums import Basis, LineItem
from glint.financials.normalize import normalize_company
from tests.financials.conftest import concepts, fixture_facts

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "golden_values.csv"
TOLERANCE = 0.005  # §5.8
FIXTURE_TICKERS = {"AAPL", "KO", "NVDA"}  # rows this worktree verified against its fixtures


def _rows() -> list[dict[str, str]]:
    with GOLDEN.open(newline="") as f:
        items = {li.value for li in LineItem}  # metric rows (WT-06) are checked in tests/metrics
        return [
            r for r in csv.DictReader(f) if r["ticker"] in FIXTURE_TICKERS and r["item"] in items
        ]


@pytest.mark.parametrize(
    "row", _rows(), ids=lambda r: f"{r['ticker']}-{r['item']}-{r['period_end']}"
)
def test_golden_value(row: dict[str, str]) -> None:
    cf = normalize_company(row["ticker"], fixture_facts(row["ticker"]), concepts())
    v = cf.series(LineItem(row["item"]), Basis.FY)[date.fromisoformat(row["period_end"])]
    assert v.value == pytest.approx(float(row["expected"]), rel=TOLERANCE)
    assert v.unit == row["unit"]
    assert v.source_accn == row["accn"]
