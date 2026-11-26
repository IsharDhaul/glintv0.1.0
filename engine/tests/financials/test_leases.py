"""Finance leases in total_debt on the filing's own word (financials/leases.py)."""

from datetime import date

from glint.contracts.enums import LineItem, Taxonomy
from glint.financials.facts import Fact
from glint.financials.leases import (
    LeaseDeclaration,
    apply_finance_leases,
    outside_debt,
    parts_to_add,
)
from glint.financials.normalize import debt_tags
from glint.financials.periods import Period
from glint.financials.select import Value
from tests.financials.conftest import concepts

Q3, FY, OLD = date(2026, 9, 30), date(2025, 12, 31), date(2023, 12, 31)
DEBT = debt_tags(concepts())
OTHER = ("us-gaap:OtherLiabilitiesCurrent",), ("us-gaap:OtherLiabilitiesNoncurrent",)


def _fact(tag: str, val: float, end: date, unit: str = "USD") -> Fact:
    return Fact(Taxonomy.US_GAAP, tag, unit, None, end, val, "0000000001-26-000009", 2026, "Q3",
                "10-Q", date(2026, 11, 5))  # fmt: skip


def _value(item: LineItem, end: date, val: float, tag: str | None) -> Value:
    return Value(item, Period(end=end), val, "USD", tag, "a", date(2026, 11, 5), val,
                 date(2026, 11, 5), tag is None)  # fmt: skip


def _selected(nc_tag: str = "LongTermDebtNoncurrent", total_tag: str | None = None):
    sel: dict[LineItem, dict[Period, Value]] = {}
    for end, total in ((Q3, 1_000.0), (FY, 900.0), (OLD, 800.0)):
        sel.setdefault(LineItem.TOTAL_DEBT, {})[Period(end=end)] = _value(
            LineItem.TOTAL_DEBT, end, total, total_tag
        )
        sel.setdefault(LineItem.DEBT_NONCURRENT, {})[Period(end=end)] = _value(
            LineItem.DEBT_NONCURRENT, end, total - 100, nc_tag
        )
    return sel


LEASES = [
    _fact("FinanceLeaseLiabilityCurrent", 10, Q3),
    _fact("FinanceLeaseLiabilityNoncurrent", 90, Q3),
    _fact("FinanceLeaseLiabilityCurrent", 8, FY),
    _fact("FinanceLeaseLiabilityNoncurrent", 80, FY),
    _fact("FinanceLeaseLiabilityNoncurrent", 70, OLD),
]


def test_lines_outside_debt() -> None:
    assert outside_debt("us-gaap:OtherLiabilitiesNoncurrent", DEBT)
    assert outside_debt("us-gaap:AccruedLiabilitiesCurrent", DEBT)
    assert outside_debt("us-gaap:FinanceLeaseLiabilityNoncurrent", DEBT)  # its own line
    assert not outside_debt("us-gaap:LongTermDebtNoncurrent", DEBT)
    assert not outside_debt("us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent", DEBT)
    assert not outside_debt("us-gaap:OtherBorrowings", DEBT)
    assert not outside_debt("ext:TermLoanAndFinanceLeaseObligations", DEBT)


def test_parts_named_outside_debt_are_the_ones_added() -> None:
    both = LeaseDeclaration({"current": OTHER[0], "noncurrent": OTHER[1]}, FY, "k")
    assert parts_to_add(both, DEBT) == ["current", "noncurrent"]
    mixed = LeaseDeclaration(
        {"current": OTHER[0], "noncurrent": ("us-gaap:LongTermDebtNoncurrent",)}, FY, "k"
    )
    assert parts_to_add(mixed, DEBT) == ["current"]
    # one named line in debt is enough to leave that part out
    split = LeaseDeclaration(
        {"noncurrent": ("us-gaap:OtherLiabilitiesNoncurrent", "us-gaap:LongTermDebtNoncurrent")},
        FY,
        "k",
    )
    assert parts_to_add(split, DEBT) == []
    total = LeaseDeclaration({"total": ("us-gaap:OtherLiabilities",)}, FY, "k")
    assert parts_to_add(total, DEBT) == ["total"]


def test_added_from_since_onward_with_evidence() -> None:
    sel = _selected()
    decl = LeaseDeclaration(
        {"current": OTHER[0], "noncurrent": OTHER[1]}, FY, "0000003570-26-000005"
    )
    assert apply_finance_leases(sel, LEASES, decl, DEBT, "USD") == []
    debt = sel[LineItem.TOTAL_DEBT]
    assert debt[Period(end=Q3)].value == 1_100 and debt[Period(end=FY)].value == 988
    assert debt[Period(end=OLD)].value == 800  # before the filing's own comparatives: unchanged
    v = debt[Period(end=Q3)]
    assert v.derived and v.source_tag is None
    assert "+ finance lease (FinanceLeaseLiabilityNoncurrent, 0000000001-26-000009)" in v.inputs
    assert v.inputs[-1] == ("finance lease presented outside debt: current in "
        "us-gaap:OtherLiabilitiesCurrent; noncurrent in us-gaap:OtherLiabilitiesNoncurrent "
        "(0000003570-26-000005)")  # fmt: skip


def test_never_added_twice() -> None:
    decl = LeaseDeclaration({"current": OTHER[0], "noncurrent": OTHER[1]}, FY, "k")
    # Glint's non-current pick already includes finance leases: only the current part is added
    sel = _selected(nc_tag="LongTermDebtAndCapitalLeaseObligations")
    apply_finance_leases(sel, LEASES, decl, DEBT, "USD")
    assert sel[LineItem.TOTAL_DEBT][Period(end=Q3)].value == 1_010
    # the filer's own combined total includes them: nothing added
    sel = _selected(total_tag="DebtAndCapitalLeaseObligations")
    apply_finance_leases(sel, LEASES, decl, DEBT, "USD")
    assert sel[LineItem.TOTAL_DEBT][Period(end=Q3)].value == 1_000


def test_unstated_other_currency_and_missing_values() -> None:
    sel = _selected()
    assert apply_finance_leases(sel, LEASES, None, DEBT, "USD") == []
    assert sel[LineItem.TOTAL_DEBT][Period(end=Q3)].value == 1_000
    decl = LeaseDeclaration({"noncurrent": OTHER[1]}, FY, "k")
    apply_finance_leases(sel, LEASES, decl, DEBT, "EUR")  # USD lease facts, EUR reporter
    assert sel[LineItem.TOTAL_DEBT][Period(end=Q3)].value == 1_000
    sel = _selected()
    warns = apply_finance_leases(sel, LEASES[:1], decl, DEBT, "USD")
    assert warns == [
        "total_debt: finance lease (noncurrent) not tagged at 2026-09-30; not added",
        "total_debt: finance lease (noncurrent) not tagged at 2025-12-31; not added",
    ]


def test_undivided_total_uses_its_parts_when_untagged() -> None:
    sel = _selected()
    decl = LeaseDeclaration({"total": ("us-gaap:OtherLiabilities",)}, Q3, "k")
    apply_finance_leases(sel, LEASES, decl, DEBT, "USD")
    assert sel[LineItem.TOTAL_DEBT][Period(end=Q3)].value == 1_100


def test_a_lease_never_creates_debt() -> None:
    sel: dict[LineItem, dict[Period, Value]] = {}
    decl = LeaseDeclaration({"noncurrent": OTHER[1]}, FY, "k")
    assert apply_finance_leases(sel, LEASES, decl, DEBT, "USD") == []
    assert LineItem.TOTAL_DEBT not in sel


def test_a_10q_tagging_only_the_undivided_total_uses_it_when_both_parts_are_outside_debt() -> None:
    """LNG: the 10-K declares current and non-current in other liabilities; its 10-Qs tag only
    FinanceLeaseLiability. Counted once."""
    both = LeaseDeclaration({"current": OTHER[0], "noncurrent": OTHER[1]}, FY, "k")
    only_total = [_fact("FinanceLeaseLiability", 140, Q3)]
    sel = _selected()
    assert apply_finance_leases(sel, only_total, both, DEBT, "USD") == [
        "total_debt: finance lease (current) not tagged at 2025-12-31; not added",
        "total_debt: finance lease (noncurrent) not tagged at 2025-12-31; not added",
    ]
    assert sel[LineItem.TOTAL_DEBT][Period(end=Q3)].value == 1_140
    # one part inside debt: the undivided total can't be split, so nothing is added
    mixed = LeaseDeclaration(
        {"current": OTHER[0], "noncurrent": ("us-gaap:LongTermDebtNoncurrent",)}, FY, "k"
    )
    sel = _selected()
    apply_finance_leases(sel, only_total, mixed, DEBT, "USD")
    assert sel[LineItem.TOTAL_DEBT][Period(end=Q3)].value == 1_000
