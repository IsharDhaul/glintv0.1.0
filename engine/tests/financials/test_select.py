"""Dedupe and tag precedence: latest filed wins, earliest remembered, highest-priority tag per period."""

from datetime import date

from glint.contracts.enums import LineItem, Taxonomy
from glint.financials.facts import Fact
from glint.financials.periods import Period
from glint.financials.select import (
    Rejections,
    Value,
    as_lineage,
    company_taxonomy,
    dedupe,
    reporting_currency,
    select_all,
    select_alternatives,
    select_item,
    usable_facts,
)
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat


def _selected(facts: tuple[Fact, ...] | list[Fact]) -> dict[LineItem, dict[Period, Value]]:
    cm = concepts()
    tx = company_taxonomy(facts, cm)
    usable = usable_facts(facts, cm, tx, reporting_currency(facts, cm), Rejections())
    return select_all(usable, cm, tx)


def _fact(tag: str, val: float, filed: str, accn: str, **kw: object) -> Fact:
    base = Fact(
        taxonomy=Taxonomy.US_GAAP,
        tag=tag,
        unit="USD",
        start=D("2025-01-01"),
        end=D("2025-03-31"),
        val=val,
        accn=accn,
        fy=2025,
        fp="Q1",
        form="10-Q",
        filed=D(filed),
    )
    return base._replace(**kw)  # pyright: ignore[reportArgumentType]


def test_latest_filed_wins_and_first_filed_is_kept() -> None:
    """AAPL restated FY2009 total assets in a 10-K/A: 53,851M first, 47,501M after."""
    facts = fixture_facts("AAPL")
    cm = concepts()
    usable = usable_facts(facts, cm, Taxonomy.US_GAAP, "USD", Rejections())
    assets = select_item(cm[LineItem.TOTAL_ASSETS], Taxonomy.US_GAAP, usable[LineItem.TOTAL_ASSETS])
    v = assets[Period(end=D("2009-09-26"))]
    assert v.value == 47_501_000_000
    assert v.first_filed_value == 53_851_000_000
    assert v.first_filed_date == D("2009-10-27")
    assert v.filed == D("2011-10-26")
    assert v.source_tag == "Assets" and not v.derived


def test_highest_priority_tag_wins_per_period() -> None:
    cm = concepts()
    facts = [
        _fact("SalesRevenueNet", 90, "2025-05-01", "a"),
        _fact("Revenues", 100, "2025-05-01", "a"),
        _fact("SalesRevenueNet", 7, "2025-05-01", "a", start=D("2024-01-01"), end=D("2024-03-31")),
    ]
    out = select_item(cm[LineItem.REVENUE], Taxonomy.US_GAAP, facts)
    assert out[Period(end=D("2025-03-31"), start=D("2025-01-01"))].value == 100
    assert out[Period(end=D("2025-03-31"), start=D("2025-01-01"))].source_tag == "Revenues"
    # An older period only has the lower-priority tag: it is used there, never summed.
    assert out[Period(end=D("2024-03-31"), start=D("2024-01-01"))].value == 7


def test_interest_and_debt_expense_fills_only_when_no_higher_tag() -> None:
    cm = concepts()
    q1, q0 = (
        Period(end=D("2025-03-31"), start=D("2025-01-01")),
        Period(end=D("2024-03-31"), start=D("2024-01-01")),
    )
    facts = [
        _fact("InterestAndDebtExpense", 12, "2025-05-01", "a"),
        _fact("InterestExpense", 10, "2025-05-01", "a"),
        _fact("InterestExpenseBorrowings", 9, "2025-05-01", "a", start=q0.start, end=q0.end),
    ]
    out = select_item(cm[LineItem.INTEREST_EXPENSE], Taxonomy.US_GAAP, facts)
    assert (out[q1].value, out[q1].source_tag) == (10, "InterestExpense")
    assert (out[q0].value, out[q0].source_tag) == (9, "InterestExpenseBorrowings")


def test_same_day_ties_are_deterministic() -> None:
    cm = concepts()
    a = [_fact("Revenues", 1, "2025-05-01", "b"), _fact("Revenues", 2, "2025-05-01", "a")]
    out1 = select_item(cm[LineItem.REVENUE], Taxonomy.US_GAAP, a)
    out2 = select_item(cm[LineItem.REVENUE], Taxonomy.US_GAAP, list(reversed(a)))
    assert out1 == out2
    assert next(iter(out1.values())).source_accn == "b"


def test_debt_current_total_beats_components() -> None:
    cm = concepts()
    inst = {"start": None, "end": D("2025-03-31")}
    facts = [
        _fact("DebtCurrent", 50, "2025-05-01", "a", **inst),
        _fact("LongTermDebtCurrent", 30, "2025-05-01", "a", **inst),
        _fact("CommercialPaper", 20, "2025-05-01", "a", **inst),
    ]
    out = select_item(cm[LineItem.DEBT_CURRENT], Taxonomy.US_GAAP, facts)
    v = next(iter(out.values()))
    assert v.value == 50 and v.source_tag == "DebtCurrent" and not v.derived


def test_debt_current_sums_distinct_components_once() -> None:
    """AAPL: commercial paper + current term debt; CP only counted when no ShortTermBorrowings."""
    sel = _selected(fixture_facts("AAPL"))
    v = sel[LineItem.DEBT_CURRENT][Period(end=D("2026-06-27"))]
    assert v.value == 11_007_000_000 + 1_997_000_000
    assert v.derived and v.source_tag is None
    assert v.inputs == ("LongTermDebtCurrent", "CommercialPaper")

    cm = concepts()
    inst = {"start": None, "end": D("2025-03-31")}
    facts = [
        _fact("ShortTermBorrowings", 40, "2025-05-01", "a", **inst),
        _fact("CommercialPaper", 25, "2025-04-01", "b", **inst),
        _fact("LongTermDebtCurrent", 10, "2025-05-01", "a", **inst),
    ]
    v2 = next(iter(select_item(cm[LineItem.DEBT_CURRENT], Taxonomy.US_GAAP, facts).values()))
    assert v2.value == 50 and v2.inputs == ("LongTermDebtCurrent", "ShortTermBorrowings")
    assert v2.first_filed_value == 50 and v2.first_filed_date == D("2025-05-01")


def test_rejections() -> None:
    cm = concepts()
    rej = Rejections()
    facts = [
        _fact("Revenues", 1, "2025-05-01", "a"),
        _fact("Revenues", 1, "2025-05-01", "a", unit="EUR"),
        _fact("Revenues", 1, "2025-05-01", "a", form="DEF 14A"),
        _fact("Revenues", 1, "2025-05-01", "a", start=None),
        _fact("Revenues", 1, "2025-05-01", "a", start=D("2025-02-01")),  # 58 days
        _fact("Revenue", 1, "2025-05-01", "a", taxonomy=Taxonomy.IFRS_FULL),
        _fact("NotMapped", 1, "2025-05-01", "a"),
    ]
    usable = usable_facts(facts, cm, Taxonomy.US_GAAP, "USD", rej)
    assert len(usable[LineItem.REVENUE]) == 1
    assert rej.counts == {
        "unit": 1,
        "form": 1,
        "period_kind": 1,
        "duration_length": 1,
        "other_taxonomy": 1,
    }


def test_taxonomy_and_currency() -> None:
    cm = concepts()
    assert company_taxonomy(fixture_facts("TSM"), cm) is Taxonomy.IFRS_FULL
    assert company_taxonomy(fixture_facts("AAPL"), cm) is Taxonomy.US_GAAP
    assert reporting_currency(fixture_facts("TSM"), cm) == "TWD"
    assert reporting_currency(fixture_facts("ASML"), cm) == "EUR"
    assert reporting_currency(fixture_facts("AAPL"), cm) == "USD"
    assert reporting_currency([], cm) is None
    # No revenue facts: fall back to the most common currency on any monetary fact.
    only_cash = [_fact("CashAndCashEquivalentsAtCarryingValue", 1, "2025-05-01", "a", unit="CAD")]
    assert reporting_currency(only_cash, cm) == "CAD"


def test_tsm_usd_convenience_facts_are_rejected() -> None:
    facts = fixture_facts("TSM")
    cm = concepts()
    rej = Rejections()
    usable = usable_facts(facts, cm, Taxonomy.IFRS_FULL, "TWD", rej)
    assert rej.counts["unit"] > 0
    assert all(f.unit in {"TWD", "TWD/shares", "shares"} for fs in usable.values() for f in fs)


def test_comparatives_do_not_use_fy_fp() -> None:
    """FY2024 revenue comes out the same whether or not fy/fp are scrambled on every fact."""
    facts = fixture_facts("AAPL")
    fy2024 = Period(end=D("2024-09-28"), start=D("2023-10-01"))
    sel = _selected(facts)
    assert sel[LineItem.REVENUE][fy2024].value == 391_035_000_000
    # The latest filing carrying FY2024 is the FY2025 10-K (a comparative tagged fy=2025).
    assert sel[LineItem.REVENUE][fy2024].source_accn == "0000320193-25-000079"
    scrambled = [f._replace(fy=1900 + i % 7, fp="Q4") for i, f in enumerate(facts)]
    assert _selected(scrambled) == sel


def test_alternatives_hold_every_total_tag_but_no_components() -> None:
    cm = concepts()
    usable = usable_facts(fixture_facts("AAPL"), cm, Taxonomy.US_GAAP, "USD", Rejections())
    alts = select_alternatives(
        cm[LineItem.DEBT_CURRENT], Taxonomy.US_GAAP, usable[LineItem.DEBT_CURRENT]
    )
    components = {t for g in cm[LineItem.DEBT_CURRENT].sum_groups.values() for t in g}
    assert all(not (set(by_tag) & components) for by_tag in alts.values())
    rev = select_alternatives(cm[LineItem.REVENUE], Taxonomy.US_GAAP, usable[LineItem.REVENUE])
    assert rev and all(v.source_tag == tag for by_tag in rev.values() for tag, v in by_tag.items())
    assert as_lineage(next(iter(next(iter(rev.values())).values())), "NoSuchTag", rev) is None


def test_dedupe_order_and_ties() -> None:
    """Keys in first-seen order; per key, ordered by (filed, accn, val), and on a full tie the
    later fact is the value and the earlier the first value (a stable sort)."""
    q1 = _fact("Revenues", 1.0, "2025-05-01", "a")
    restated = _fact("Revenues", 2.0, "2026-05-01", "b")
    tie = _fact("Revenues", 2.0, "2026-05-01", "b", fy=2026)  # equal key, differs in fy
    other = _fact("SalesRevenueNet", 9.0, "2025-05-01", "a")
    instant = _fact("Revenues", 5.0, "2025-05-01", "a", start=None)
    got = dedupe([restated, other, tie, q1, instant])
    q = Period(end=D("2025-03-31"), start=D("2025-01-01"))
    assert list(got) == [
        (q, "Revenues"),
        (q, "SalesRevenueNet"),
        (Period(D("2025-03-31")), "Revenues"),
    ]
    tv = got[(q, "Revenues")]
    assert tv.latest is tie and tv.first is q1 and tv.tag == "Revenues"
    assert got[(q, "SalesRevenueNet")].latest is other is got[(q, "SalesRevenueNet")].first
    assert dedupe([]) == {}


def test_selection_from_deduped_matches_selection_from_facts() -> None:
    cm = concepts()
    facts = fixture_facts("AAPL")
    usable = usable_facts(facts, cm, Taxonomy.US_GAAP, "USD", Rejections())
    deduped = {item: dedupe(fs) for item, fs in usable.items()}
    assert select_all(deduped, cm, Taxonomy.US_GAAP) == select_all(usable, cm, Taxonomy.US_GAAP)
    c = cm[LineItem.REVENUE]
    assert select_alternatives(c, Taxonomy.US_GAAP, deduped[LineItem.REVENUE]) == (
        select_alternatives(c, Taxonomy.US_GAAP, usable[LineItem.REVENUE])
    )
