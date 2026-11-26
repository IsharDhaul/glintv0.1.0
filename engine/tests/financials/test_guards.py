"""Guarded short-term borrowings (NotesAndLoansPayable) and per-CIK component sums."""

from datetime import date

from glint.contracts.enums import LineItem
from glint.financials.concepts import CikSum
from glint.financials.guards import apply_cik_sum, apply_notes_and_loans
from glint.financials.periods import Period
from glint.financials.select import Value

P = Period(end=date(2025, 12, 31))
L = LineItem


def v(item: LineItem, value: float, tag: str | None) -> Value:
    return Value(
        item=item, period=P, value=value, unit="USD", source_tag=tag, source_accn="0000-25-1",
        filed=date(2026, 2, 20), first_filed_value=value, first_filed_date=date(2026, 2, 20),
        derived=tag is None,
    )  # fmt: skip


Series = dict[Period, Value]


def ko(
    nlp: float, *, ltd: float = 42_119, cur: float = 1_822, cp: float = 1_495
) -> tuple[Series, Series, Series, Series, Series]:
    """KO FY2025 (in $M): current LTD 1,822, commercial paper 1,495, NotesAndLoansPayable 1,551."""
    current_ltd = {P: v(L.DEBT_CURRENT, cur, "LongTermDebtAndCapitalLeaseObligationsCurrent")}
    short_term = {P: v(L.DEBT_CURRENT, cp, "CommercialPaper")}
    debt_current = {P: v(L.DEBT_CURRENT, cur + cp, None)}
    noncurrent = {P: v(L.DEBT_NONCURRENT, ltd, "LongTermDebtAndCapitalLeaseObligations")}
    notes = {P: v(L.DEBT_CURRENT, nlp, "NotesAndLoansPayable")}
    return debt_current, short_term, current_ltd, notes, noncurrent


def test_ko_uses_notes_and_loans() -> None:
    dc, st = apply_notes_and_loans(*ko(1_551), tolerance=0.005)
    assert dc[P].value == 3_373 and dc[P].derived
    assert "NotesAndLoansPayable" in " ".join(dc[P].inputs)
    assert st[P].value == 1_551 and st[P].source_tag == "NotesAndLoansPayable"


def test_guard_rejects_totals_and_double_counts() -> None:
    for nlp in (
        50_000,  # ≥ long-term debt: a total of all notes
        1_822,  # equals current LTD: would count it twice
        1_400,  # smaller than commercial paper: keep CP
    ):
        dc, st = apply_notes_and_loans(*ko(nlp), tolerance=0.005)
        assert dc[P].value == 3_317 and st[P].value == 1_495, nlp


def test_guard_needs_long_term_debt() -> None:
    debt_current, short_term, current_ltd, notes, _ = ko(1_551)
    dc, _st = apply_notes_and_loans(
        debt_current, short_term, current_ltd, notes, {}, tolerance=0.005
    )
    assert dc[P].value == 3_317


def test_a_tagged_total_wins() -> None:
    _, short_term, current_ltd, notes, noncurrent = ko(1_551)
    total = {P: v(L.DEBT_CURRENT, 3_400, "DebtCurrent")}
    dc, st = apply_notes_and_loans(
        total, short_term, current_ltd, notes, noncurrent, tolerance=0.005
    )
    assert dc[P].value == 3_400 and st[P].value == 1_551  # the short-term part still updates


NVDA = CikSum(
    tags=("DebtSecuritiesCurrent", "EquitySecuritiesFvNi"),
    evidence="10-K FY2026 balance sheet: Marketable securities 51,951",
    keyed_by="Ishar Dhaul, 2026-10-30",
)


def test_cik_sum_for_a_listed_company() -> None:
    sel = {P: v(L.ST_INVESTMENTS, 39_065, "DebtSecuritiesCurrent")}
    parts = {
        "DebtSecuritiesCurrent": {P: v(L.ST_INVESTMENTS, 39_065, "DebtSecuritiesCurrent")},
        "EquitySecuritiesFvNi": {P: v(L.ST_INVESTMENTS, 12_886, "EquitySecuritiesFvNi")},
    }
    out = apply_cik_sum(L.ST_INVESTMENTS, sel, parts, NVDA)
    assert out[P].value == 51_951 and out[P].derived and out[P].source_tag is None


def test_cik_sum_never_overrides_a_tagged_line() -> None:
    sel = {P: v(L.ST_INVESTMENTS, 50_000, "MarketableSecuritiesCurrent")}
    parts = {
        "DebtSecuritiesCurrent": {P: v(L.ST_INVESTMENTS, 39_065, "DebtSecuritiesCurrent")},
        "EquitySecuritiesFvNi": {P: v(L.ST_INVESTMENTS, 12_886, "EquitySecuritiesFvNi")},
    }
    assert apply_cik_sum(L.ST_INVESTMENTS, sel, parts, NVDA)[P].value == 50_000


def test_cik_sum_needs_every_component() -> None:
    sel = {P: v(L.ST_INVESTMENTS, 39_065, "DebtSecuritiesCurrent")}
    parts = {"DebtSecuritiesCurrent": sel}
    assert apply_cik_sum(L.ST_INVESTMENTS, sel, parts, NVDA)[P].value == 39_065
