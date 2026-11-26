"""Zero total debt only on positive balance-sheet evidence (glint/financials/zero_debt.py)."""

from datetime import date
from typing import Any

import pytest
import yaml

from glint.contracts.enums import Basis, LineItem, Taxonomy
from glint.core.errors import ContractError
from glint.financials.concepts import DEFAULT_CONCEPTS_PATH, ZeroDebtRule, parse_concepts
from glint.financials.facts import Fact
from glint.financials.normalize import normalize_company
from glint.financials.zero_debt import (
    is_current,
    is_unsuffixed,
    itemize,
    merge_breakdowns,
    merge_rollups,
    subset_sums_to,
    zero_debt,
)
from tests.financials.conftest import concepts

AT = date(2026, 6, 30)
ACCN = "0000000001-26-000010"
RULE = ZeroDebtRule(
    liability_lines=frozenset({
        "AccountsPayableCurrent", "AccruedLiabilitiesCurrent", "OperatingLeaseLiability",
        "OperatingLeaseLiabilityCurrent", "OperatingLeaseLiabilityNoncurrent",
        "OtherLiabilitiesNoncurrent", "DeferredIncomeTaxLiabilitiesNet",
        "EmployeeRelatedLiabilitiesCurrent", "AccruedSalariesCurrent", "AccruedBonusesCurrent",
        "DeferredRevenueCurrent", "AccruedLiabilitiesNoncurrent",
        "AccruedLiabilitiesCurrentAndNoncurrent",
    }),
    debt_lines=frozenset({"NotesPayable", "LongTermDebt", "LineOfCredit"}),
    interest=frozenset({"InterestExpense", "InterestPaidNet"}),
    interest_lookback_days=366,
    max_lines=22,
    forms=frozenset({"10-Q", "10-K"}),
    breakdowns={"AccruedLiabilitiesCurrent": (
        "EmployeeRelatedLiabilitiesCurrent", "AccruedSalariesCurrent", "AccruedBonusesCurrent",
    )},
)  # fmt: skip


def fact(tag: str, val: float, *, end: date = AT, start: date | None = None,
         accn: str = ACCN, form: str = "10-Q", filed: date = date(2026, 8, 5),
         unit: str = "USD") -> Fact:  # fmt: skip
    return Fact(Taxonomy.US_GAAP, tag, unit, start, end, val, accn, 2026, "Q2", form, filed)


def balance_sheet() -> list[Fact]:
    """Liabilities 10,270 = current 6,120 (AP 2,513 + accrued 3,607) + non-current 4,150
    (lease 3,041 + other 1,109). No line equals a sum of others (that would read as a roll-up)."""
    return [
        fact("Liabilities", 10_270),
        fact("LiabilitiesCurrent", 6_120),
        fact("AccountsPayableCurrent", 2_513),
        fact("AccruedLiabilitiesCurrent", 3_607),
        fact("OperatingLeaseLiabilityNoncurrent", 3_041),
        fact("OtherLiabilitiesNoncurrent", 1_109),
    ]


def test_itemized_balance_sheet_proves_zero_debt() -> None:
    v = zero_debt(balance_sheet(), AT, "USD", RULE)
    assert v is not None
    assert v.value == 0.0 and v.derived and v.item is LineItem.TOTAL_DEBT
    assert v.source_tag is None and v.source_accn == ACCN and v.period.end == AT
    assert "Liabilities 10,270; LiabilitiesCurrent 6,120" in v.inputs[0]
    assert "AccountsPayableCurrent 2,513" in v.inputs[0] and ACCN in v.inputs[0]


def test_unclassified_balance_sheet() -> None:
    facts = [f for f in balance_sheet() if f.tag != "LiabilitiesCurrent"]
    assert zero_debt(facts, AT, "USD", RULE) is not None


def test_a_missing_line_is_not_evidence() -> None:
    """A debt line under a custom or dimensional tag isn't in companyfacts: the sum falls short."""
    facts = [fact("Liabilities", 10_770), *balance_sheet()[1:]]  # 500 under a custom debt tag
    assert zero_debt(facts, AT, "USD", RULE) is None


def test_no_liability_lines_no_proof() -> None:
    assert zero_debt([fact("Liabilities", 10_270)], AT, "USD", RULE) is None
    assert zero_debt([], AT, "USD", RULE) is None


@pytest.mark.parametrize("tag", ["NotesPayable", "LongTermDebt", "LineOfCredit"])
def test_any_nonzero_debt_tag_blocks(tag: str) -> None:
    other_filing = fact(tag, 5, accn="0000000001-26-000099", form="10-K")
    assert zero_debt([*balance_sheet(), other_filing], AT, "USD", RULE) is None


def test_a_zero_debt_tag_does_not_block() -> None:
    assert zero_debt([*balance_sheet(), fact("LineOfCredit", 0)], AT, "USD", RULE) is not None


def test_interest_expense_in_the_year_blocks() -> None:
    recent = fact("InterestExpense", 1_000, start=date(2025, 7, 1), end=date(2026, 3, 31))
    assert zero_debt([*balance_sheet(), recent], AT, "USD", RULE) is None
    old = fact(
        "InterestExpense", 1_000, start=date(2024, 6, 29), end=date(2025, 6, 29)
    )  # 366 days before
    assert zero_debt([*balance_sheet(), old], AT, "USD", RULE) is not None
    zero = fact("InterestExpense", 0, start=date(2026, 4, 1), end=AT)
    assert zero_debt([*balance_sheet(), zero], AT, "USD", RULE) is not None


def test_roll_up_is_not_counted_twice() -> None:
    """Lease total 3,040 = 1,013 + 2,027 next to its parts; 3,040 of custom-tagged debt on the
    balance sheet must not be hidden by counting the lease twice."""
    facts = [
        fact("Liabilities", 9_081),
        fact("AccountsPayableCurrent", 3_001),
        fact("OperatingLeaseLiabilityCurrent", 1_013),
        fact("OperatingLeaseLiabilityNoncurrent", 2_027),
        fact("OperatingLeaseLiability", 3_040),
    ]
    assert zero_debt(facts, AT, "USD", RULE) is None


def test_only_the_first_10q_or_10k_counts() -> None:
    eight_k = [f._replace(form="8-K") for f in balance_sheet()]
    assert zero_debt(eight_k, AT, "USD", RULE) is None
    later = [
        f._replace(accn="0000000001-26-000020", filed=date(2026, 11, 1)) for f in balance_sheet()
    ]
    first = [fact("Liabilities", 10_270), fact("AccountsPayableCurrent", 1)]  # doesn't itemize
    assert zero_debt([*first, *later], AT, "USD", RULE) is None


def test_two_values_for_a_tag_in_one_filing() -> None:
    facts = [*balance_sheet(), fact("AccountsPayableCurrent", 2_514)]
    assert zero_debt(facts, AT, "USD", RULE) is None


def test_other_currency_and_date_ignored() -> None:
    assert zero_debt(balance_sheet(), date(2026, 3, 31), "USD", RULE) is None
    assert zero_debt(balance_sheet(), AT, "EUR", RULE) is None


def test_too_many_lines() -> None:
    lines = [(f"L{i}", 2**i) for i in range(5)]
    assert itemize(lines, 31, None, max_lines=4) is None
    assert itemize(lines, 31, None, max_lines=5) == ("L0", "L1", "L2", "L3", "L4")


def test_every_line_counts() -> None:
    """No line is left out to make the sum work (the review's finding): here the lines exceed
    Liabilities, and leaving out AP would 'prove' it."""
    lines = [("A", 300), ("B", 500), ("C", 200)]
    assert itemize(lines, 1_000, None, max_lines=22) == ("A", "B", "C")
    assert itemize(lines, 700, None, max_lines=22) is None  # B + C = 700, but A is a line too


def test_footnote_cannot_stand_in_for_custom_debt() -> None:
    """The reviewer's case: AP 4,100, accrued 3,700, deferred revenue 1,450, leases 530 / 1,070
    and 2,100 of custom-tagged current debt; the accrued note tags salaries 1,300 and bonuses 800
    (its third part is custom). Salaries + bonuses = 2,100 = the debt, but they are inside
    accrued (≤ 3,700), so they are dropped as a footnote and the sum falls short."""
    facts = [
        fact("Liabilities", 12_950),
        fact("LiabilitiesCurrent", 11_880),
        fact("AccountsPayableCurrent", 4_100),
        fact("AccruedLiabilitiesCurrent", 3_700),
        fact("DeferredRevenueCurrent", 1_450),
        fact("OperatingLeaseLiabilityCurrent", 530),
        fact("OperatingLeaseLiabilityNoncurrent", 1_070),
        fact("AccruedSalariesCurrent", 1_300),
        fact("AccruedBonusesCurrent", 800),
    ]
    assert zero_debt(facts, AT, "USD", RULE) is None
    no_debt = [fact("Liabilities", 10_850), fact("LiabilitiesCurrent", 9_780), *facts[2:]]
    v = zero_debt(no_debt, AT, "USD", RULE)  # same lines, no debt: the footnote is not counted
    assert v is not None and "AccruedSalariesCurrent" not in v.inputs[0]


def test_footnote_rules() -> None:
    bd = RULE.breakdowns
    parent = ("AccruedLiabilitiesCurrent", 1_000)
    sal, bon = ("AccruedSalariesCurrent", 400), ("AccruedBonusesCurrent", 700)
    assert merge_breakdowns([parent, sal], bd) == [parent]  # contained: footnote
    assert merge_breakdowns([parent, sal, bon], bd) == [parent, sal, bon]  # 1,100 > 1,000: kept
    assert merge_breakdowns([sal, bon], bd) == [sal, bon]  # no parent: face lines


def test_rollups_by_name() -> None:
    lease = [("OperatingLeaseLiability", 30), ("OperatingLeaseLiabilityCurrent", 10),
             ("OperatingLeaseLiabilityNoncurrent", 20)]  # fmt: skip
    assert merge_rollups(lease) == lease[1:]
    assert merge_rollups([("OperatingLeaseLiability", 31), *lease[1:]]) is None  # disagrees
    mixed = [("AccruedLiabilitiesCurrentAndNoncurrent", 9), ("AccruedLiabilitiesNoncurrent", 9)]
    assert merge_rollups(mixed) == mixed[1:]
    unrelated = [("OtherLiabilities", 30), ("A", 10), ("B", 20)]  # equal by value only: kept
    assert merge_rollups(unrelated) == unrelated


def test_suffix_rules() -> None:
    assert is_current("AccruedLiabilitiesCurrent")
    assert not is_current("OtherLiabilitiesNoncurrent")
    assert not is_current("AccruedLiabilitiesCurrentAndNoncurrent")
    assert not is_current("DeferredIncomeTaxLiabilitiesNet")
    assert is_unsuffixed("DeferredIncomeTaxLiabilitiesNet")
    assert is_unsuffixed("AccruedLiabilitiesCurrentAndNoncurrent")
    assert not is_unsuffixed("OtherLiabilitiesNoncurrent")


def test_current_block_must_match() -> None:
    """All lines add up, but the …Current lines plus unsuffixed ones can't make LiabilitiesCurrent."""
    lines = [("AccountsPayableCurrent", 600), ("OtherLiabilitiesNoncurrent", 400)]
    assert itemize(lines, 1_000, 600, max_lines=22) is not None
    assert itemize(lines, 1_000, 700, max_lines=22) is None
    free = [("AccountsPayableCurrent", 600), ("DeferredIncomeTaxLiabilitiesNet", 100),
            ("OtherLiabilitiesNoncurrent", 300)]  # fmt: skip
    assert itemize(free, 1_000, 700, max_lines=22) is not None  # deferred tax on the current side
    assert itemize(free, 1_000, 650, max_lines=22) is None


def test_subset_sums_to() -> None:
    assert subset_sums_to([("a", 1), ("b", 2)], 3)
    assert subset_sums_to([], 0)
    assert not subset_sums_to([("a", 1)], 5)


def test_unsuffixed_line_cap() -> None:
    many = [(f"Line{i}", 3**i) for i in range(13)]  # 13 unsuffixed lines > MAX_FREE
    total = sum(v for _, v in many)
    assert itemize(many, total, 1, max_lines=22) is None


def test_restated_liabilities_block() -> None:
    restated = fact("Liabilities", 10_300, accn="0000000001-26-000030", form="10-K/A")
    assert zero_debt([*balance_sheet(), restated], AT, "USD", RULE) is None
    same = fact("Liabilities", 10_270, accn="0000000001-26-000030", form="10-K")
    assert zero_debt([*balance_sheet(), same], AT, "USD", RULE) is not None


def test_debt_tag_in_another_unit_blocks() -> None:
    eur = fact("NotesPayable", 5, unit="EUR")
    assert zero_debt([*balance_sheet(), eur], AT, "USD", RULE) is None


@pytest.mark.parametrize(("tag", "val"), [("InterestPaidNet", 50), ("InterestExpense", -50)])
def test_unmapped_or_negative_interest_blocks(tag: str, val: float) -> None:
    paid = fact(tag, val, start=date(2026, 1, 1), end=AT)
    assert zero_debt([*balance_sheet(), paid], AT, "USD", RULE) is None


def test_normalize_fills_only_the_latest_balance_sheet() -> None:
    earlier = [
        f._replace(end=date(2026, 3, 31), accn="0000000001-26-000005") for f in balance_sheet()
    ]
    cf = normalize_company("1", [*earlier, *balance_sheet()], concepts())
    series = cf.series(LineItem.TOTAL_DEBT, Basis.MRQ)
    assert list(series) == [AT]
    assert series[AT].value == 0.0 and series[AT].derived


def test_normalize_skips_ifrs_filers() -> None:
    ifrs = [fact("Revenue", 1, start=date(2026, 1, 1)), fact("Equity", 5)]
    ifrs = [f._replace(taxonomy=Taxonomy.IFRS_FULL) for f in ifrs]
    cf = normalize_company("1", [*ifrs * 3, *balance_sheet()], concepts())
    assert cf.taxonomy is Taxonomy.IFRS_FULL
    assert cf.series(LineItem.TOTAL_DEBT, Basis.MRQ) == {}


def test_normalize_keeps_a_tagged_total() -> None:
    cf = normalize_company("1", [*balance_sheet(), fact("LongTermDebtNoncurrent", 7)], concepts())
    v = cf.latest(LineItem.TOTAL_DEBT, Basis.MRQ)
    assert v is not None and v.value == 7


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(DEFAULT_CONCEPTS_PATH.read_text())
    return raw


def test_config_loads_the_rule() -> None:
    rule = concepts().zero_debt
    assert rule is not None
    assert {"LongTermDebt", "NotesPayable", "FinanceLeaseLiabilityNoncurrent"} <= rule.debt_lines
    assert {"InterestExpense", "InterestPaidNet"} <= rule.interest
    assert "AccountsPayableCurrent" in rule.liability_lines


def test_config_rejects_a_debt_tag_as_liability_line() -> None:
    raw = _raw()
    raw["evidence_tags"]["us-gaap"]["liability_lines"].append("LongTermDebt")
    with pytest.raises(ContractError, match="debt tags listed as liability lines"):
        parse_concepts(raw)


def test_config_rejects_a_tag_in_two_groups() -> None:
    raw = _raw()
    raw["evidence_tags"]["us-gaap"]["interest"].append("NotesPayable")
    with pytest.raises(ContractError, match="listed twice"):
        parse_concepts(raw)


def test_config_breakdowns() -> None:
    rule = concepts().zero_debt
    assert rule is not None
    assert "OtherAccruedLiabilitiesCurrent" in rule.breakdowns["AccruedLiabilitiesCurrent"]
    raw = _raw()
    raw["liability_breakdowns"]["AccruedLiabilitiesCurrent"].append("NotATag")
    with pytest.raises(ContractError, match="not liability_lines"):
        parse_concepts(raw)


def test_no_evidence_tags_no_rule() -> None:
    raw = _raw()
    del raw["evidence_tags"]
    assert parse_concepts(raw).zero_debt is None
