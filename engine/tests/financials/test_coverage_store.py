"""Gaps carry reasons; coverage aggregates by group; rows land in the `financials` table."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from glint.contracts.enums import Basis, LineItem, NoteCode, Sector
from glint.financials.coverage import Group, coverage, gaps, latest_end
from glint.financials.normalize import CompanyFinancials, keep_from, normalize_company
from glint.financials.store import write_financials
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat

APPENDIX_D = {
    "AAPL": None,
    "MSFT": None,
    "NVDA": None,
    "KO": None,
    "MU": None,
    "KHC": None,
    "RIVN": None,
    "SBUX": None,
    "XOM": None,
    "F": None,
    "JPM": Sector.BANKS,
    "O": Sector.REAL_ESTATE,
    "BRK.B": Sector.INSURANCE,
    "GOOGL": None,
    "TSM": None,
    "ASML": None,
}


def _cf(ticker: str) -> CompanyFinancials:
    return normalize_company(ticker, fixture_facts(ticker), concepts())


@pytest.mark.parametrize("ticker", sorted(APPENDIX_D))
def test_every_core_gap_at_latest_fy_has_a_reason(ticker: str) -> None:
    """Acceptance: core items for the latest FY are present, or there's a reason."""
    g = gaps(_cf(ticker), concepts(), concepts().core, Basis.FY, APPENDIX_D[ticker])
    for gap in g.values():
        assert gap.code in NoteCode and gap.message.startswith(gap.item.value)


def test_clean_filers_have_no_core_gaps() -> None:
    for t in ("AAPL", "NVDA", "KO", "MU", "ASML"):
        assert gaps(_cf(t), concepts(), concepts().core, Basis.FY) == {}, t


def test_bank_gaps_are_not_applicable_by_design() -> None:
    g = gaps(
        _cf("JPM"), concepts(), [*concepts().core, LineItem.GROSS_PROFIT], Basis.FY, Sector.BANKS
    )
    assert g[LineItem.GROSS_PROFIT].code is NoteCode.NOT_APPLICABLE_SECTOR
    assert g[LineItem.INVENTORY].code is NoteCode.NOT_APPLICABLE_SECTOR
    assert g[LineItem.OPERATING_INCOME].code is NoteCode.MISSING_INPUT
    assert "OperatingIncomeLoss" in g[LineItem.OPERATING_INCOME].message


def test_new_registrant_without_a_fiscal_year() -> None:
    g = gaps(_cf("XOM"), concepts(), [LineItem.REVENUE], Basis.FY)
    assert g[LineItem.REVENUE].code is NoteCode.INSUFFICIENT_HISTORY


def test_ttm_gap_after_a_fiscal_year_change() -> None:
    cf = _cf("ANAB")
    end = latest_end(cf, Basis.Q)
    assert end is not None and end > D("2025-12-31")
    g = gaps(cf, concepts(), [LineItem.REVENUE], Basis.Q)
    assert g == {}  # discrete quarters still exist
    ttm_end = latest_end(cf, Basis.TTM)
    assert ttm_end == D("2025-12-31")


def test_ttm_gap_reasons() -> None:
    cf = _cf("ANAB")
    cf.ttm[LineItem.REVENUE] = {}
    g = gaps(cf, concepts(), [LineItem.REVENUE], Basis.TTM)
    assert g[LineItem.REVENUE].code is NoteCode.INSUFFICIENT_HISTORY
    assert "fiscal-year change" in g[LineItem.REVENUE].message
    aapl = _cf("AAPL")
    aapl.ttm[LineItem.CFO] = {}
    g = gaps(aapl, concepts(), [LineItem.CFO], Basis.TTM)
    assert "no 4 contiguous quarters" in g[LineItem.CFO].message


def test_stale_share_count_is_a_gap() -> None:
    g = gaps(_cf("BRK.B"), concepts(), [LineItem.SHARES_OUTSTANDING], Basis.TTM, Sector.INSURANCE)
    assert g[LineItem.SHARES_OUTSTANDING].code is NoteCode.MISSING_INPUT
    assert "2011-04-29" in g[LineItem.SHARES_OUTSTANDING].message
    assert gaps(_cf("AAPL"), concepts(), [LineItem.SHARES_OUTSTANDING], Basis.TTM) == {}


def test_coverage_by_group() -> None:
    companies = [
        (Group.DOMESTIC, _cf("AAPL")),
        (Group.DOMESTIC, _cf("MSFT")),
        (Group.FINANCIAL, _cf("JPM")),
        (Group.FOREIGN, _cf("TSM")),
    ]
    rep = coverage(companies, concepts(), Basis.TTM)
    assert rep.companies == {Group.DOMESTIC: 2, Group.FINANCIAL: 1, Group.FOREIGN: 1}
    assert rep.share(LineItem.REVENUE, Group.DOMESTIC) == 1.0
    assert rep.share(LineItem.DNA, Group.DOMESTIC) == 1.0  # MSFT: Depreciation + amortization
    assert rep.tags[LineItem.DNA]["derived"] >= 1
    assert rep.share(LineItem.INVENTORY, Group.FINANCIAL) == 0.0
    assert rep.tags[LineItem.REVENUE]["RevenueFromContractWithCustomerExcludingAssessedTax"] >= 1
    core = rep.core_share(concepts().core, Group.DOMESTIC)
    assert core is not None and 0.9 < core <= 1.0
    empty = coverage([], concepts())
    assert empty.share(LineItem.REVENUE, Group.DOMESTIC) is None
    assert empty.core_share(concepts().core, Group.DOMESTIC) is None


def test_rows_are_written_to_the_financials_table(tmp_path: Path) -> None:
    cf = normalize_company("0000320193", fixture_facts("AAPL"), concepts())
    rows = cf.rows(keep_from(concepts()))
    with duckdb.connect(str(tmp_path / "b.duckdb")) as con:
        assert write_financials(con, rows) == len(rows)
        got = con.execute(
            "SELECT value, source_tag, derived FROM financials "
            "WHERE line_item='revenue' AND basis='q' AND period_end='2025-09-27'"
        ).fetchall()
        assert got == [(102_466e6, None, True)]
        n_derived = con.execute("SELECT count(*) FROM financials WHERE derived").fetchone()
        assert n_derived is not None and n_derived[0] > 0


def test_missing_input_message_carries_the_item_note() -> None:
    """Ford tags automotive debt only as components after 2020: null, and the gap says why."""
    g = gaps(_cf("F"), concepts(), [LineItem.TOTAL_DEBT], Basis.FY)
    gap = g[LineItem.TOTAL_DEBT]
    assert gap.code is NoteCode.MISSING_INPUT
    assert gap.message.endswith(f". {concepts()[LineItem.TOTAL_DEBT].note}")
    assert "isn't summed" in gap.message
