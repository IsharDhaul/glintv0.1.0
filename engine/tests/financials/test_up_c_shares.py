"""The Up-C economic count in the share series (financials/shares.py `apply_economic_count`)."""

from datetime import date

import orjson
import polars as pl

from glint.contracts.enums import Basis, LineItem
from glint.financials.build import economic_counts
from glint.financials.facts import facts_from_companyfacts
from glint.financials.normalize import CompanyFinancials, normalize_company
from glint.financials.shares import ECONOMIC_LINEAGE, EconomicCount, apply_economic_count
from tests.financials.conftest import DATA_DIR, concepts

SHARES = LineItem.SHARES_OUTSTANDING
STALE = concepts().params.shares_stale_days
AVEX = EconomicCount(
    shares=114_041_700,
    as_of=date(2026, 8, 12),
    accn="0002096300-26-000022",
    filed=date(2026, 8, 12),
    evidence="10-Q 0002096300-26-000022: cover page CommonClassA 56,470,333 + CommonClassB ...",
)


def avex() -> CompanyFinancials:
    doc = orjson.loads((DATA_DIR / "AVEX.companyfacts.json").read_bytes())
    return normalize_company("0002096300", list(facts_from_companyfacts(doc)), concepts())


def test_economic_count_becomes_the_market_cap_count() -> None:
    cf = avex()
    before = cf.latest(SHARES, Basis.MRQ)
    assert before is not None and before.value == 52_805_593  # Class A only (diluted fallback)
    apply_economic_count(cf, AVEX, STALE)
    v = cf.latest(SHARES, Basis.MRQ)
    assert v is not None and v.value == 114_041_700
    assert cf.shares_as_of == date(2026, 8, 12)
    assert v.derived and v.lineage == ECONOMIC_LINEAGE and v.source_accn == AVEX.accn
    assert v.inputs[0].startswith("Up-C economic shares: 10-Q 0002096300-26-000022")
    assert not cf.shares_stale
    assert cf.series(SHARES, Basis.MRQ)[date(2026, 6, 30)].value == 52_805_593  # history kept


def test_no_economic_count_changes_nothing() -> None:
    """GOOGL, BRK and every non-Up-C company: no economic count, no change."""
    cf, ref = avex(), avex()
    apply_economic_count(cf, None, STALE)
    assert cf.series(SHARES, Basis.MRQ) == ref.series(SHARES, Basis.MRQ)
    assert cf.shares_stale == ref.shares_stale and cf.warnings == ref.warnings


def test_later_listed_class_counts_are_replaced() -> None:
    cf = avex()
    early = EconomicCount(100.0, date(2026, 6, 30), "x", date(2026, 8, 12), "e")
    apply_economic_count(cf, early, STALE)
    assert cf.latest(SHARES, Basis.MRQ).value == 100.0  # type: ignore[union-attr]
    assert any("replaces 1 listed-class count" in w for w in cf.warnings)


def test_an_old_economic_count_is_stale() -> None:
    cf = avex()
    old = EconomicCount(100.0, date(2024, 1, 31), "x", date(2024, 2, 1), "e")
    apply_economic_count(cf, old, STALE)
    assert cf.shares_stale


def test_economic_counts_from_companies() -> None:
    row = {
        "cik": ["0002096300", "0001652044"],
        "is_up_c": [True, False],
        "economic_shares": [114_041_700.0, None],
        "economic_shares_as_of": [date(2026, 8, 12), None],
        "economic_shares_accn": ["0002096300-26-000022", None],
        "economic_shares_filed": [date(2026, 8, 12), None],
        "up_c_evidence": ["10-Q ...", None],
    }
    counts = economic_counts(pl.DataFrame(row))
    assert list(counts) == ["0002096300"] and counts["0002096300"].shares == 114_041_700
    # companies.parquet from before the Up-C columns: nothing to apply
    assert economic_counts(pl.DataFrame({"cik": ["1"], "has_facts": [True]})) == {}
