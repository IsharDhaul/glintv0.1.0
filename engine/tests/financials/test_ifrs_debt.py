"""IFRS bonds and current financial assets (WT-03.md 2026-11-24): summed only per company, with
the balance-sheet lines in concepts.yaml `cik_sums`; elsewhere bond tags are fallbacks."""

from datetime import date

import pytest

from glint.contracts.enums import Basis, LineItem
from glint.financials.normalize import normalize_company
from tests.financials.conftest import concepts, fixture_facts

TSMC = "0001046179"
FY2024 = date(2024, 12, 31)


def _fy(cik: str, item: str) -> float:
    cf = normalize_company(cik, fixture_facts("TSM"), concepts())
    return cf.series(LineItem(item), Basis.FY)[FY2024].value


def test_tsmc_debt_adds_bonds_payable_to_bank_loans() -> None:
    # 20-F FY2024 balance sheet: bank loans 31,824.4 + bonds payable 926,604.5 (NT$ millions);
    # the current portion of both is one line, 59,857.9.
    assert _fy(TSMC, "debt_noncurrent") == pytest.approx(958_428.9e6)
    assert _fy(TSMC, "total_debt") == pytest.approx(1_018_286.8e6)


def test_tsmc_short_term_investments_add_three_lines() -> None:
    # FVTPL 207.7 + FVOCI 192,202.7 + amortised cost 101,971.3 (NT$ millions).
    assert _fy(TSMC, "st_investments") == pytest.approx(294_381.7e6)


def test_without_a_cik_sum_bonds_are_not_added_to_borrowings() -> None:
    # Another CIK with the same facts: borrowings win alone (bonds are a fallback, never summed),
    # and the component-only investment lines don't count on their own.
    assert _fy("0000000001", "debt_noncurrent") == pytest.approx(31_824.4e6)
    assert _fy("0000000001", "st_investments") == pytest.approx(207.7e6)
