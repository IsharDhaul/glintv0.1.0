"""Period engine: periods are keyed by (start, end) and classified by length, never by fy/fp."""

from datetime import date

from glint.contracts.enums import Taxonomy
from glint.financials.concepts import DurationClass
from glint.financials.facts import Fact, facts_from_companyfacts
from glint.financials.periods import Period, by_period, classify, is_contiguous, period_of
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat


def test_period_basics() -> None:
    q = Period(end=D("2025-03-29"), start=D("2024-12-29"))
    assert q.days == 90 and not q.is_instant
    assert q.label() == "2024-12-29..2025-03-29"
    i = Period(end=D("2025-03-29"))
    assert i.is_instant and i.days == 0 and i.label() == "2025-03-29"
    assert classify(i, concepts().durations) is None
    assert classify(q, concepts().durations) is DurationClass.QUARTER
    # Ordered, compared and hashed as (end, start).
    q_next = Period(end=D("2025-06-28"), start=D("2025-03-30"))
    assert sorted([q_next, q]) == [q, q_next] and Period(D("2025-03-29")) == i
    assert len({q, Period(end=D("2025-03-29"), start=D("2024-12-29"))}) == 1


def test_contiguity() -> None:
    q1 = Period(end=D("2025-12-27"), start=D("2025-09-28"))
    q2 = Period(end=D("2026-03-28"), start=D("2025-12-28"))
    assert is_contiguous(q1, q2)
    assert not is_contiguous(q2, q1)
    assert not is_contiguous(q1, Period(end=D("2026-03-28")))
    assert is_contiguous(q1, Period(end=D("2026-03-28"), start=D("2025-12-29")), gap_days=2)


def _aapl_revenue() -> list[Fact]:
    return [
        f
        for f in fixture_facts("AAPL")
        if f.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]


def test_10k_comparatives_are_keyed_by_their_own_dates() -> None:
    """AAPL's FY2025 10-K also carries FY2024 and FY2023 revenue, all tagged fy=2025 fp=FY."""
    facts = _aapl_revenue()
    fy2025_10k = [f for f in facts if f.form == "10-K" and f.fy == 2025 and f.fp == "FY"]
    ends = {f.end for f in fy2025_10k if f.start is not None}
    assert {D("2025-09-27"), D("2024-09-28"), D("2023-09-30")} <= ends

    groups = by_period(facts)
    fy2024 = Period(end=D("2024-09-28"), start=D("2023-10-01"))
    assert classify(fy2024, concepts().durations) is DurationClass.FISCAL_YEAR
    filings = {(f.fy, f.accn) for f in groups[fy2024]}
    # The FY2024 period is one bucket holding its own 10-K and later filings' comparatives.
    assert {fy for fy, _ in filings} >= {2024, 2025}
    assert {f.val for f in groups[fy2024]} == {391_035_000_000}


def test_grouping_ignores_fy_and_fp() -> None:
    facts = fixture_facts("AAPL")
    scrambled = [f._replace(fy=1999, fp="Q9") for f in facts]
    a = {p: sorted((f.accn, f.tag, f.val) for f in fs) for p, fs in by_period(facts).items()}
    b = {p: sorted((f.accn, f.tag, f.val) for f in fs) for p, fs in by_period(scrambled).items()}
    assert a == b


def test_52_53_week_years_classify_as_fiscal_years() -> None:
    """NVDA years end on the last Sunday of January: 52 or 53 weeks (end − start = 363 or 370)."""
    bounds = concepts().durations
    lengths = {
        period_of(f).days
        for f in fixture_facts("NVDA")
        if f.tag == "NetIncomeLoss"
        and f.form == "10-K"
        and f.start is not None
        and classify(period_of(f), bounds) is DurationClass.FISCAL_YEAR
    }
    assert {363, 370} <= lengths


def test_companyfacts_reader_skips_unknown_taxonomies_and_blank_rows() -> None:
    doc = {
        "facts": {
            "srt": {"X": {"units": {"USD": [{"end": "2025-01-01", "val": 1}]}}},
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2025-01-01", "filed": "2025-02-01", "val": None, "accn": "a"},
                            {"end": "2025-01-01", "filed": "2025-02-01", "val": 5, "accn": "a"},
                        ]
                    }
                }
            },
        }
    }
    facts = list(facts_from_companyfacts(doc))
    assert len(facts) == 1
    assert facts[0].taxonomy is Taxonomy.US_GAAP and facts[0].start is None and facts[0].val == 5.0
