"""WT-11 golden set: values typed in from the filings (golden_values.csv) vs Glint's numbers.

Every line-item row with an `expected` value is checked against the normalized series of the
committed trimmed fixture, at the row's basis and period: value within 0.5% (§5.8), the same
unit, and the same accession when the row gives one. A row without `expected` is pending: it is
skipped with a pointer to `python -m tests.golden.lookup`, never passed. Metric rows (WT-06) are
checked in tests/metrics/test_golden_metrics.py; rows for companies outside the Appendix D
fixtures by the tests that carry their facts.
"""

import csv
from datetime import date
from pathlib import Path

import pytest

from glint.contracts.enums import Basis, LineItem
from glint.financials.normalize import normalize_company
from glint.fixtures.sec import FIXTURE_DIR, fixture_name
from tests.financials.conftest import concepts, fixture_facts
from tests.golden.lookup import person_verified

GOLDEN = Path(__file__).resolve().parent / "golden_values.csv"
TOLERANCE = 0.005  # §5.8
COLUMNS = ["ticker", "item", "basis", "period_end", "expected", "unit", "accn",
           "where_in_filing", "verified_by", "verified_on"]  # fmt: skip


def in_fixtures(ticker: str) -> bool:
    """Appendix D fixture companies. Rows for others (WAT, AVEX, DUOL, POWI) are checked by the
    tests that carry their facts (tests/financials/share_facts, debt_facts)."""
    return (FIXTURE_DIR / f"{fixture_name(ticker)}.companyfacts.json").exists()


def _rows() -> list[dict[str, str]]:
    items = {li.value for li in LineItem}
    with GOLDEN.open(newline="") as f:
        return [r for r in csv.DictReader(f) if r["item"] in items and in_fixtures(r["ticker"])]


def _id(r: dict[str, str]) -> str:
    return f"{r['ticker']}-{r['item']}-{r['basis']}-{r['period_end']}"


def test_csv_has_the_brief_columns() -> None:
    with GOLDEN.open(newline="") as f:
        assert next(csv.reader(f)) == COLUMNS


@pytest.mark.parametrize("row", _rows(), ids=_id)
def test_golden_value(row: dict[str, str]) -> None:
    if not row["expected"].strip():
        pytest.skip(f"pending: enter from the filing (python -m tests.golden.lookup "
                    f"{row['ticker']} {row['item']} --basis {row['basis']})")  # fmt: skip
    assert row["verified_by"].strip() and row["verified_on"].strip(), "who verified it, and when"
    assert row["where_in_filing"].strip(), "where in the filing the value is"
    cf = normalize_company(row["ticker"], fixture_facts(row["ticker"]), concepts())
    series = cf.series(LineItem(row["item"]), Basis(row["basis"]))
    end = date.fromisoformat(row["period_end"])
    assert end in series, f"Glint has no {row['basis']} value at {end}"
    v = series[end]
    assert v.value == pytest.approx(float(row["expected"]), rel=TOLERANCE)
    assert v.unit == row["unit"]
    if row["accn"].strip():
        assert v.source_accn == row["accn"]


def test_recheck_lists_rows_no_person_verified() -> None:
    base = {"verified_on": "2026-11-24"}
    assert person_verified({**base, "verified_by": "A Person"})
    assert not person_verified({**base, "verified_by": ""})
    assert not person_verified({**base, "verified_by": "Claude (independent check), accepted"})
    assert person_verified({**base, "verified_by": "claude-chat, confirmed by Ishar"})
    assert not person_verified({**base, "verified_by": "claude-chat, confirmed by"})
    assert not person_verified({"verified_by": "A Person", "verified_on": ""})
