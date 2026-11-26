"""concepts.yaml loads into typed structures that agree with the contracts."""

from collections.abc import Callable
from typing import Any

import pytest
import yaml

from glint.contracts.enums import LineItem, PeriodKind, Sector, Taxonomy
from glint.core.errors import ContractError
from glint.financials.concepts import (
    DEFAULT_CONCEPTS_PATH,
    Derivation,
    DurationClass,
    UnitKind,
    load_concepts,
    parse_concepts,
)


def _raw() -> dict[str, Any]:
    return yaml.safe_load(DEFAULT_CONCEPTS_PATH.read_text())


def test_every_line_item_is_typed() -> None:
    cm = load_concepts()
    assert set(cm.concepts) == set(LineItem)
    assert cm[LineItem.REVENUE].kind is PeriodKind.DURATION
    assert cm[LineItem.CASH].kind is PeriodKind.INSTANT
    assert cm[LineItem.EPS_DILUTED].unit is UnitKind.PER_SHARE
    assert not cm[LineItem.EPS_DILUTED].additive
    assert cm[LineItem.REVENUE].additive
    assert cm[LineItem.CAPEX].sign == "positive_outflow"


def test_tag_priority_is_kept_in_file_order() -> None:
    cm = load_concepts()
    tags = cm[LineItem.REVENUE].tags_for(Taxonomy.US_GAAP)
    assert tags[0] == (Taxonomy.US_GAAP, "Revenues")
    assert tags[1] == (Taxonomy.US_GAAP, "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert all(tx is Taxonomy.US_GAAP for tx, _ in tags)


def test_dei_cover_tags_come_first_for_shares() -> None:
    cm = load_concepts()
    for taxonomy in (Taxonomy.US_GAAP, Taxonomy.IFRS_FULL):
        tags = cm[LineItem.SHARES_OUTSTANDING].tags_for(taxonomy)
        assert tags[0] == (Taxonomy.DEI, "EntityCommonStockSharesOutstanding")
    assert cm[LineItem.SHARES_OUTSTANDING].fallback is LineItem.DILUTED_SHARES


def test_derivations_parse() -> None:
    cm = load_concepts()
    gp = cm[LineItem.GROSS_PROFIT].derive
    assert gp is not None
    assert gp.terms == ((1, LineItem.REVENUE), (-1, LineItem.COST_OF_REVENUE))
    assert str(gp) == "revenue − cost_of_revenue"
    for item in (LineItem.EBITDA, LineItem.FCF):
        assert cm[item].derive is not None
        assert not cm[item].tags and not cm[item].prefer_derived
    # total_debt: derived first; the filer's combined totals only fill periods it can't build.
    td = cm[LineItem.TOTAL_DEBT]
    assert td.derive is not None and td.prefer_derived
    assert td.tags_for(Taxonomy.US_GAAP) == (
        (Taxonomy.US_GAAP, "DebtLongtermAndShorttermCombinedAmount"),
        (Taxonomy.US_GAAP, "DebtAndCapitalLeaseObligations"),
    )


def test_debt_rules() -> None:
    cm = load_concepts()
    dc = cm[LineItem.DEBT_CURRENT]
    assert dc.total_tags == {"DebtCurrent"}
    assert set(dc.sum_groups) == {"current_ltd", "short_term"}
    nc = cm[LineItem.DEBT_NONCURRENT]
    including = "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"
    assert nc.includes_current == {"LongTermDebt", including}
    assert nc.tags_for(Taxonomy.US_GAAP)[-1] == (Taxonomy.US_GAAP, including)  # last resort
    note = cm[LineItem.TOTAL_DEBT].note
    assert note is not None and "isn't summed" in note
    assert cm[LineItem.REVENUE].note is None


def test_cost_of_revenue_ex_dna_is_last_and_explained() -> None:
    """Lowest priority (only when no inclusive tag is filed) and its definition is stated."""
    c = load_concepts()[LineItem.COST_OF_REVENUE]
    tag = "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"
    assert c.tags[Taxonomy.US_GAAP][-1] == tag
    assert "excludes D&A" in c.tag_notes[tag]


def test_interest_expense_gross_tags_only() -> None:
    """Gross expense tags, existing ones first; operating (interest already inside operating
    income), sub-line, net and cash-paid tags stay unmapped (decision 2026-11-22)."""
    tags = list(load_concepts()[LineItem.INTEREST_EXPENSE].tags[Taxonomy.US_GAAP])
    assert tags == [
        "InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
        "InterestAndDebtExpense", "InterestExpenseBorrowings",
    ]  # fmt: skip
    for unmapped in ("InterestExpenseOperating", "InterestExpenseOther",
                     "InterestIncomeExpenseNet", "InterestPaidNet"):  # fmt: skip
        assert unmapped not in tags


def test_not_applicable_sectors() -> None:
    cm = load_concepts()
    assert Sector.BANKS in cm[LineItem.GROSS_PROFIT].not_applicable
    assert not cm[LineItem.REVENUE].not_applicable


def test_tag_index_maps_each_tag_to_one_item() -> None:
    cm = load_concepts()
    assert cm.tag_index[(Taxonomy.US_GAAP, "LongTermDebt")] is LineItem.DEBT_NONCURRENT
    assert cm.tag_index[(Taxonomy.IFRS_FULL, "Revenue")] is LineItem.REVENUE
    assert cm.tag_index[(Taxonomy.DEI, "EntityCommonStockSharesOutstanding")] is (
        LineItem.SHARES_OUTSTANDING
    )


def test_duration_classes() -> None:
    d = load_concepts().durations
    assert d.classify(90) is DurationClass.QUARTER
    assert d.classify(181) is DurationClass.HALF_YEAR
    assert d.classify(272) is DurationClass.NINE_MONTHS
    assert d.classify(363) is DurationClass.FISCAL_YEAR  # 52-week year
    assert d.classify(370) is DurationClass.FISCAL_YEAR  # 53-week year
    assert d.classify(120) is DurationClass.OTHER
    assert d.classify(0) is DurationClass.OTHER
    # Memoized: a second call gives the same class; the cache doesn't affect equality.
    assert [d.classify(n) for n in (90, 120, 90)] == [
        DurationClass.QUARTER, DurationClass.OTHER, DurationClass.QUARTER
    ]  # fmt: skip
    assert d == load_concepts().durations


def test_forms_exclude_proxies() -> None:
    forms = load_concepts().forms
    assert {"10-K", "10-Q", "20-F", "10-K/A"} <= forms
    assert "DEF 14A" not in forms


Mutation = Callable[[dict[str, Any]], object]


def _cycle(raw: dict[str, Any]) -> None:
    raw["line_items"]["fcf"]["derive"] = "ebitda - capex"
    raw["line_items"]["ebitda"]["derive"] = "fcf + dna"


INVALID: list[tuple[Mutation, str]] = [
    (lambda r: r["line_items"].pop("revenue"), "missing"),
    (lambda r: r["line_items"]["fcf"].update(derive="cfo - fcf"), "itself"),
    (lambda r: r["line_items"]["fcf"].update(derive="cfo - nonsense"), "unknown line item"),
    (lambda r: r["line_items"]["fcf"].update(derive="cfo capex"), "bad derivation"),
    (lambda r: r["line_items"]["fcf"].update(derive="cfo - cash"), "mixes"),
    (lambda r: r["line_items"]["sbc"]["tags"]["us-gaap"].append("Revenues"), "both"),
    (
        lambda r: r["line_items"]["sbc"]["tags"]["us-gaap"].append("ShareBasedCompensation"),
        "duplicate",
    ),
    (lambda r: r["line_items"]["fcf"].pop("derive"), "tags or a derive"),
    (lambda r: r["line_items"]["debt_current"]["sum_groups"].update(x=["Nope"]), "unlisted"),
    (lambda r: r["line_items"]["debt_noncurrent"].update(includes_current=["Nope"]), "unlisted"),
    (lambda r: r["line_items"]["ebitda"].update(prefer_derived=True), "prefer_derived"),
    (lambda r: r["line_items"]["cash"].update(additive=False), "durations only"),
    (lambda r: r["line_items"]["shares_outstanding"].update(fallback="revenue"), "unit"),
    (lambda r: r["durations"].pop("quarter"), "durations"),
    (lambda r: r["line_items"]["revenue"].update(kind="sometimes"), "concepts.yaml"),
    (lambda r: r["core"]["flows"].append("cash"), "wrong kind"),
    (_cycle, "cycle"),
]


@pytest.mark.parametrize(("mutate", "message"), INVALID)
def test_invalid_maps_are_rejected(mutate: Mutation, message: str) -> None:
    raw = _raw()
    mutate(raw)
    with pytest.raises(ContractError, match=message):
        parse_concepts(raw)


def test_empty_derivation_is_rejected() -> None:
    with pytest.raises(ContractError):
        Derivation.parse("")
