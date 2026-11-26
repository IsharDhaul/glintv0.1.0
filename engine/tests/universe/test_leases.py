"""Finance-lease presentation from the filing's own ASC 842 declaration (universe/leases.py)."""

from datetime import date
from pathlib import Path

from glint.ingest.sec.covers import Cover, InstanceFact, LeaseLine, parse_balance_facts
from glint.universe.leases import finance_lease_presentation

COVERS = Path(__file__).parents[1] / "ingest_sec" / "data"
Q3, FY = date(2026, 9, 30), date(2025, 12, 31)
CUR = "FinanceLeaseLiabilityCurrentStatementOfFinancialPositionExtensibleList"
NONCUR = "FinanceLeaseLiabilityNoncurrentStatementOfFinancialPositionExtensibleList"


def _cover(form: str, accn: str, facts: list[InstanceFact], leases: list[LeaseLine]) -> Cover:
    return Cover("0000000001", accn, form, date(2026, 11, 5), "x_htm.xml", [], {}, [],
                 facts, leases)  # fmt: skip


def _lease(end: date, value: float, **dims: str) -> InstanceFact:
    return InstanceFact("us-gaap:FinanceLeaseLiabilityNoncurrent", value, end, "USD", dims)


def test_lng_10k_presents_its_finance_lease_outside_debt() -> None:
    """Cheniere's FY2025 10-K (real, trimmed): current and non-current finance leases sit in
    other liabilities, so WT-03 will add them to debt."""
    facts, leases = parse_balance_facts((COVERS / "lng-20251231-leases.xml").read_bytes())
    lng = Cover("0000003570", "0000003570-26-000005", "10-K", date(2026, 2, 24), "lng_htm.xml",
                [], {}, [], facts, leases)  # fmt: skip
    p = finance_lease_presentation(lng)
    assert p is not None and p.status == "stated"
    assert p.lines == {
        "current": ["us-gaap:OtherLiabilitiesCurrent"],
        "noncurrent": ["us-gaap:OtherLiabilitiesNoncurrent"],
    }
    assert (p.accn, p.as_of) == ("0000003570-26-000005", FY)
    assert p.since == date(2024, 12, 31)  # the comparative column names the same lines
    assert p.evidence == (
        "10-K 0000003570-26-000005 (2025-12-31): finance lease current in "
        "us-gaap:OtherLiabilitiesCurrent; noncurrent in us-gaap:OtherLiabilitiesNoncurrent"
    )


def test_the_10k_speaks_when_the_10q_does_not() -> None:
    q = _cover("10-Q", "q", [_lease(Q3, 5e8), _lease(FY, 4e8)], [])
    k = _cover(
        "10-K", "k", [_lease(FY, 4e8)], [LeaseLine(NONCUR, ["us-gaap:LongTermDebtNoncurrent"], FY)]
    )
    p = finance_lease_presentation(q, k)
    assert p is not None and p.status == "stated" and p.accn == "k"
    assert p.lines == {"noncurrent": ["us-gaap:LongTermDebtNoncurrent"]}


def test_the_latest_filing_wins_and_only_its_latest_declaration_counts() -> None:
    q = _cover("10-Q", "q", [_lease(Q3, 5e8)], [
        LeaseLine(NONCUR, ["us-gaap:OtherLiabilitiesNoncurrent"], Q3),
        LeaseLine(NONCUR, ["us-gaap:LongTermDebtNoncurrent"], FY),  # comparative column
    ])  # fmt: skip
    k = _cover("10-K", "k", [], [LeaseLine(NONCUR, ["us-gaap:LongTermDebtNoncurrent"], FY)])
    p = finance_lease_presentation(q, k)
    assert p is not None and (p.accn, p.as_of) == ("q", Q3)
    assert p.lines == {"noncurrent": ["us-gaap:OtherLiabilitiesNoncurrent"]}
    assert p.since == Q3  # the comparative named another line: not carried back


def test_not_stated_anywhere() -> None:
    q = _cover("10-Q", "q", [_lease(Q3, 5e8)], [
        LeaseLine("FinanceLeaseRightOfUseAssetStatementOfFinancialPositionExtensibleList",
                  ["us-gaap:PropertyPlantAndEquipmentNet"], Q3),  # asset side says nothing
    ])  # fmt: skip
    p = finance_lease_presentation(q, _cover("10-K", "k", [], []))
    assert p is not None and p.status == "not_stated" and p.lines == {} and p.accn is None
    assert p.evidence == (
        "FinanceLeaseLiabilityNoncurrent 500,000,000 at 2026-09-30; no filing names its "
        "balance-sheet line (10-Q q, 10-K k)"
    )


def test_no_finance_lease_at_the_balance_sheet_date() -> None:
    debt = InstanceFact("us-gaap:LongTermDebtNoncurrent", 1e9, Q3, "USD")
    decl = [LeaseLine(NONCUR, ["us-gaap:OtherLiabilitiesNoncurrent"], Q3)]
    assert finance_lease_presentation(_cover("10-Q", "q", [debt], decl)) is None
    # paid off: only the comparative column has a lease
    assert finance_lease_presentation(_cover("10-Q", "q", [debt, _lease(FY, 4e8)], decl)) is None
    # a lease of a segment or a VIE alone isn't the registrant's total
    seg = _lease(
        Q3,
        4e8,
        **{
            "srt:ConsolidatedEntitiesAxis": "us-gaap:VariableInterestEntityPrimaryBeneficiaryMember"
        },
    )
    assert finance_lease_presentation(_cover("10-Q", "q", [seg], decl)) is None
    assert finance_lease_presentation(None) is None
