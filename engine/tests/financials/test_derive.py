"""Derived items (§4.3 rule 9) and sign conventions (rule 8)."""

from datetime import date

import pytest

from glint.contracts.enums import Basis, LineItem
from glint.financials.derive import derive_items, total_debt
from glint.financials.normalize import normalize_company
from glint.financials.periods import Period
from glint.financials.select import Value
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat
Q = Period(end=D("2025-03-31"), start=D("2025-01-01"))
INST = Period(end=D("2025-03-31"))


def _v(item: LineItem, value: float, period: Period = Q, tag: str | None = "T") -> Value:
    return Value(
        item=item,
        period=period,
        value=value,
        unit="USD",
        source_tag=tag,
        source_accn=f"a-{item}",
        filed=D("2025-05-01"),
        first_filed_value=value,
        first_filed_date=D("2025-05-01"),
        derived=tag is None,
    )


def test_gross_profit_derived_only_where_untagged() -> None:
    other = Period(end=D("2024-03-31"), start=D("2024-01-01"))
    sel = {
        LineItem.REVENUE: {Q: _v(LineItem.REVENUE, 100), other: _v(LineItem.REVENUE, 90, other)},
        LineItem.COST_OF_REVENUE: {
            Q: _v(LineItem.COST_OF_REVENUE, 60),
            other: _v(LineItem.COST_OF_REVENUE, 50, other),
        },
        LineItem.GROSS_PROFIT: {other: _v(LineItem.GROSS_PROFIT, 41, other, tag="GrossProfit")},
    }
    out = derive_items(sel, concepts())
    gp = out[LineItem.GROSS_PROFIT]
    assert gp[Q].value == 40 and gp[Q].derived and gp[Q].source_tag is None
    assert gp[Q].inputs == ("+ revenue (T)", "− cost_of_revenue (T)")
    assert gp[other].value == 41 and not gp[other].derived  # the tag wins


def test_no_derivation_without_every_input_for_the_same_period() -> None:
    sel = {LineItem.CFO: {Q: _v(LineItem.CFO, 10)}}
    assert LineItem.FCF not in derive_items(sel, concepts())


def test_fcf_subtracts_positive_capex() -> None:
    """Capex is tagged as a positive payment: FCF = CFO − capex."""
    sel = {LineItem.CFO: {Q: _v(LineItem.CFO, 100)}, LineItem.CAPEX: {Q: _v(LineItem.CAPEX, 30)}}
    assert derive_items(sel, concepts())[LineItem.FCF][Q].value == 70


def test_ebitda_and_total_liabilities() -> None:
    sel = {
        LineItem.OPERATING_INCOME: {Q: _v(LineItem.OPERATING_INCOME, -5)},
        LineItem.DNA: {Q: _v(LineItem.DNA, 8)},
        LineItem.LIABILITIES_AND_EQUITY: {INST: _v(LineItem.LIABILITIES_AND_EQUITY, 500, INST)},
        LineItem.EQUITY_INCL_NCI: {INST: _v(LineItem.EQUITY_INCL_NCI, 120, INST)},
    }
    out = derive_items(sel, concepts())
    assert out[LineItem.EBITDA][Q].value == 3
    assert out[LineItem.TOTAL_LIABILITIES][INST].value == 380


@pytest.mark.parametrize(
    ("current", "noncurrent", "short_term", "expected"),
    [
        ((30, None), (70, "LongTermDebtNoncurrent"), None, 100),  # current + noncurrent
        ((30, None), (100, "LongTermDebt"), (5, "ShortTermBorrowings"), 105),  # no double count
        ((30, "DebtCurrent"), (100, "LongTermDebt"), None, 100),  # current LTD inside LongTermDebt
        (None, (70, "LongTermDebtNoncurrent"), None, 70),  # nothing due within a year
    ],
)
def test_total_debt_rule(
    current: tuple[float, str | None] | None,
    noncurrent: tuple[float, str] | None,
    short_term: tuple[float, str] | None,
    expected: float,
) -> None:
    sel: dict[LineItem, dict[Period, Value]] = {}
    if current:
        sel[LineItem.DEBT_CURRENT] = {INST: _v(LineItem.DEBT_CURRENT, current[0], INST, current[1])}
    if noncurrent:
        sel[LineItem.DEBT_NONCURRENT] = {
            INST: _v(LineItem.DEBT_NONCURRENT, noncurrent[0], INST, noncurrent[1])
        }
    st = {INST: _v(LineItem.DEBT_CURRENT, short_term[0], INST, short_term[1])} if short_term else {}
    out = total_debt(sel, st, frozenset({"LongTermDebt"}))
    assert out[INST].value == expected and out[INST].derived


def test_no_debt_tags_means_no_total_debt() -> None:
    assert total_debt({}, {}, frozenset({"LongTermDebt"})) == {}


def test_current_debt_alone_is_not_total_debt() -> None:
    """A missing long-term side is usually an unmapped tag, not zero (principle 3)."""
    sel = {LineItem.DEBT_CURRENT: {INST: _v(LineItem.DEBT_CURRENT, 30, INST, "DebtCurrent")}}
    st = {INST: _v(LineItem.DEBT_CURRENT, 5, INST, "ShortTermBorrowings")}
    assert total_debt(sel, st, frozenset({"LongTermDebt"})) == {}


def test_combined_total_fills_only_periods_the_components_cannot() -> None:
    """total_debt is prefer_derived: a tagged combined total never overrides the component sum
    (AMD 2023: 2,467M tagged vs 3,217M summed), and fills a period with no non-current side."""
    other = Period(end=D("2024-03-31"))
    sel = {
        LineItem.DEBT_CURRENT: {INST: _v(LineItem.DEBT_CURRENT, 30, INST, "DebtCurrent"),
                                other: _v(LineItem.DEBT_CURRENT, 25, other, "DebtCurrent")},
        LineItem.DEBT_NONCURRENT: {INST: _v(LineItem.DEBT_NONCURRENT, 70, INST,
                                            "LongTermDebtNoncurrent")},
        LineItem.TOTAL_DEBT: {
            INST: _v(LineItem.TOTAL_DEBT, 80, INST, "DebtLongtermAndShorttermCombinedAmount"),
            other: _v(LineItem.TOTAL_DEBT, 90, other, "DebtLongtermAndShorttermCombinedAmount"),
        },
    }  # fmt: skip
    td = derive_items(sel, concepts())[LineItem.TOTAL_DEBT]
    assert td[INST].value == 100 and td[INST].derived  # components win
    assert (
        td[other].value == 90 and td[other].source_tag == "DebtLongtermAndShorttermCombinedAmount"
    )
    assert not td[other].derived


def test_including_current_maturities_adds_only_short_term_borrowings() -> None:
    """CVX 10-Q 2026-06-30 style: LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities
    already holds the current portion, so only short-term borrowings are added."""
    including = "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"
    sel = {
        LineItem.DEBT_CURRENT: {INST: _v(LineItem.DEBT_CURRENT, 30, INST, None)},
        LineItem.DEBT_NONCURRENT: {INST: _v(LineItem.DEBT_NONCURRENT, 36_674, INST, including)},
    }
    st = {INST: _v(LineItem.DEBT_CURRENT, 401, INST, "ShortTermBorrowings")}
    includes = concepts()[LineItem.DEBT_NONCURRENT].includes_current
    assert total_debt(sel, st, includes)[INST].value == 36_674 + 401


def test_real_jpm_has_no_total_debt_from_short_term_borrowings_alone() -> None:
    """JPM tags ShortTermBorrowings but no mapped long-term debt tag: null, not ~65B."""
    cf = normalize_company("0000019617", fixture_facts("JPM"), concepts())
    current = cf.latest(LineItem.DEBT_CURRENT, Basis.MRQ)
    assert current is not None and current.period.end == D("2026-06-30")
    assert D("2026-06-30") not in cf.series(LineItem.TOTAL_DEBT, Basis.MRQ)
    last = cf.latest(LineItem.TOTAL_DEBT, Basis.MRQ)  # 2014, while LongTermDebt was still tagged
    assert last is not None and last.period.end == D("2014-06-30")


def test_real_total_debt_aapl() -> None:
    """AAPL 10-Q, 27 Jun 2026: CP 1,997 + current term debt 11,007 + non-current 71,340 ($M)."""
    cf = normalize_company("0000320193", fixture_facts("AAPL"), concepts())
    td = cf.latest(LineItem.TOTAL_DEBT, Basis.MRQ)
    assert td is not None and td.period.end == D("2026-06-27")
    assert td.value == (1_997 + 11_007 + 71_340) * 1e6
    assert td.derived


def test_real_total_liabilities_ko_is_derived() -> None:
    """KO doesn't tag Liabilities: L&E − equity incl. NCI."""
    cf = normalize_company("0000021344", fixture_facts("KO"), concepts())
    tl = cf.latest(LineItem.TOTAL_LIABILITIES, Basis.MRQ)
    le = cf.latest(LineItem.LIABILITIES_AND_EQUITY, Basis.MRQ)
    eq = cf.latest(LineItem.EQUITY_INCL_NCI, Basis.MRQ)
    assert tl is not None and le is not None and eq is not None
    assert tl.derived and tl.value == le.value - eq.value


def test_real_signs() -> None:
    """Rule 8: capex/dividends/buybacks are positive payments; losses are negative."""
    aapl = normalize_company("0000320193", fixture_facts("AAPL"), concepts())
    fy = D("2025-09-27")
    for item in (LineItem.CAPEX, LineItem.DIVIDENDS_PAID, LineItem.BUYBACKS):
        assert aapl.series(item, Basis.FY)[fy].value > 0, item
    fcf = aapl.series(LineItem.FCF, Basis.FY)[fy]
    cfo = aapl.series(LineItem.CFO, Basis.FY)[fy]
    capex = aapl.series(LineItem.CAPEX, Basis.FY)[fy]
    assert fcf.value == cfo.value - capex.value < cfo.value
    rivn = normalize_company("0001874178", fixture_facts("RIVN"), concepts())
    rfy = D("2025-12-31")
    assert rivn.series(LineItem.NET_INCOME, Basis.FY)[rfy].value < 0
    assert rivn.series(LineItem.OPERATING_INCOME, Basis.FY)[rfy].value < 0
    assert rivn.series(LineItem.FCF, Basis.FY)[rfy].value < 0
