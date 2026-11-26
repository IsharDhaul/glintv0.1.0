"""Zero total debt on real trimmed facts (debt_facts/, the extraction whitelist, facts since
2025-06): DUOL's and POWI's itemized balance sheets (golden rows, hand-checked against their
10-Qs), and two companies that must stay null —
SAIL (interest expense in the year before its debt-free balance sheet) and GM (debt tagged only
dimensionally at the 10-Q date, so its standard lines don't add up to total liabilities)."""

import csv
from datetime import date
from pathlib import Path

import orjson
import pytest

from glint.contracts.enums import Basis, LineItem
from glint.financials.facts import facts_from_companyfacts
from glint.financials.normalize import CompanyFinancials, normalize_company
from tests.financials.conftest import concepts

DATA_DIR = Path(__file__).resolve().parent / "debt_facts"
GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "golden_values.csv"


def _company(ticker: str) -> CompanyFinancials:
    doc = orjson.loads((DATA_DIR / f"{ticker}.companyfacts.json").read_bytes())
    return normalize_company(ticker, list(facts_from_companyfacts(doc)), concepts())


def _rows() -> list[dict[str, str]]:
    with GOLDEN.open(newline="") as f:
        return [
            r
            for r in csv.DictReader(f)
            if (DATA_DIR / f"{r['ticker']}.companyfacts.json").exists()
            and r["item"] == LineItem.TOTAL_DEBT.value
        ]


def test_rows_exist() -> None:
    rows = {r["ticker"]: r for r in _rows()}
    assert set(rows) >= {"DUOL", "POWI"}
    assert all(r["verified_by"] and r["verified_on"] for r in rows.values())


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r['ticker']}-{r['item']}")
def test_golden_zero_debt(row: dict[str, str]) -> None:
    cf = _company(row["ticker"])
    end = date.fromisoformat(row["period_end"])
    assert cf.balance_sheet_date == end  # the latest balance sheet only
    v = cf.series(LineItem.TOTAL_DEBT, Basis.MRQ)[end]
    assert v.value == float(row["expected"]) == 0.0
    assert v.unit == row["unit"]
    assert v.source_accn == row["accn"]
    assert v.derived and v.source_tag is None
    assert v.inputs[0].startswith("no debt: Liabilities ")
    assert row["accn"] in v.inputs[0]


@pytest.mark.parametrize("ticker", ["SAIL", "GM"])
def test_no_proof_stays_null(ticker: str) -> None:
    cf = _company(ticker)
    assert cf.balance_sheet_date is not None
    assert cf.balance_sheet_date not in cf.series(LineItem.TOTAL_DEBT, Basis.MRQ)
