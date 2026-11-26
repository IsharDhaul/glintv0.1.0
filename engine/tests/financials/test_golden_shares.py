"""Golden share counts (tests/golden/golden_values.csv) on the trimmed real facts in share_facts/:
WAT's diluted count (tagged ×1,000 in its 2026 10-Qs) and AVEX's count (pre-IPO 1,000 shares,
then the Up-C economic count from its cover page)."""

import csv
from datetime import date
from pathlib import Path

import orjson
import pytest

from glint.contracts.enums import Basis, LineItem
from glint.financials.facts import facts_from_companyfacts
from glint.financials.normalize import normalize_company
from glint.financials.shares import EconomicCount, apply_economic_count
from glint.ingest.sec.covers import Cover, parse_instance
from glint.universe.classify import load_rules
from glint.universe.upc import detect_up_c
from tests.financials.conftest import DATA_DIR, concepts

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "golden_values.csv"
TOLERANCE = 0.005  # §5.8
BASIS = {LineItem.DILUTED_SHARES: Basis.Q, LineItem.SHARES_OUTSTANDING: Basis.MRQ}
COVERS = Path(__file__).resolve().parents[1] / "ingest_sec" / "data"


def _up_c(name: str, cik: str, accn: str, filed: date) -> EconomicCount:
    """The economic count the build derives: real trimmed cover facts → Up-C detection."""
    classes, symbols, nci = parse_instance((COVERS / name).read_bytes())
    upc = detect_up_c(
        Cover(cik, accn, "10-Q", filed, name, classes, symbols, nci), load_rules().up_c
    )
    assert upc is not None
    return EconomicCount(upc.economic_shares, upc.as_of, upc.accn, upc.filed, upc.evidence)


UP_C = {
    "AVEX": _up_c(
        "avex-20260630-cover.xml", "0002096300", "0002096300-26-000022", date(2026, 8, 12)
    )
}


def _rows() -> list[dict[str, str]]:
    with GOLDEN.open(newline="") as f:
        return [
            r
            for r in csv.DictReader(f)
            if (DATA_DIR / f"{r['ticker']}.companyfacts.json").exists()
            and r["item"] in {i.value for i in BASIS}
        ]


def test_rows_exist() -> None:
    assert {(r["ticker"], r["item"]) for r in _rows()} >= {
        ("WAT", "diluted_shares"),
        ("AVEX", "shares_outstanding"),
    }


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r['ticker']}-{r['item']}")
def test_golden_share_count(row: dict[str, str]) -> None:
    doc = orjson.loads((DATA_DIR / f"{row['ticker']}.companyfacts.json").read_bytes())
    cf = normalize_company(row["ticker"], list(facts_from_companyfacts(doc)), concepts())
    apply_economic_count(cf, UP_C.get(row["ticker"]), concepts().params.shares_stale_days)
    item = LineItem(row["item"])
    v = cf.series(item, BASIS[item])[date.fromisoformat(row["period_end"])]
    assert v.value == pytest.approx(float(row["expected"]), rel=TOLERANCE)
    assert v.unit == row["unit"]
    assert v.source_accn == row["accn"]
    assert v.derived  # both are corrections, flagged DERIVED_INPUT
