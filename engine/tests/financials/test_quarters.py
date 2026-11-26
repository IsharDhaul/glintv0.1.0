"""Discrete quarters: filed 3-month facts first, else YTD differences (Q4 = FY − 9M)."""

import dataclasses
from datetime import date

import pytest

from glint.contracts.enums import LineItem, Taxonomy
from glint.financials.normalize import normalize_company
from glint.financials.periods import Period
from glint.financials.quarters import discrete_quarters, fiscal_years
from glint.financials.select import Rejections, Value, select_item, usable_facts
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat


def _v(
    start: str, end: str, value: float, *, filed: str = "2025-12-01", derived: bool = False
) -> Value:
    return Value(
        item=LineItem.CFO,
        period=Period(end=D(end), start=D(start)),
        value=value,
        unit="USD",
        source_tag="NetCashProvidedByUsedInOperatingActivities",
        source_accn=f"accn-{end}",
        filed=D(filed),
        first_filed_value=value,
        first_filed_date=D(filed),
        derived=derived,
    )


def _map(*vs: Value) -> dict[Period, Value]:
    return {v.period: v for v in vs}


def test_ytd_only_cash_flow_becomes_four_quarters() -> None:
    vals = _map(
        _v("2025-01-01", "2025-03-31", 10),
        _v("2025-01-01", "2025-06-30", 25),
        _v("2025-01-01", "2025-09-30", 45),
        _v("2025-01-01", "2025-12-31", 70),
    )
    q = discrete_quarters(vals, concepts().durations)
    assert [x.value for x in q.values()] == [10, 15, 20, 25]
    assert [x.quarter_derived for x in q.values()] == [False, True, True, True]
    q4 = q[D("2025-12-31")]
    assert q4.period == Period(end=D("2025-12-31"), start=D("2025-10-01"))
    assert q4.source_tag is None and not q4.derived
    assert q4.inputs == (
        "2025-01-01..2025-12-31 − 2025-01-01..2025-09-30 "
        "[NetCashProvidedByUsedInOperatingActivities]",
    )
    assert sum(x.value for x in q.values()) == 70


def test_filed_quarters_win_over_differences() -> None:
    vals = _map(
        _v("2025-01-01", "2025-03-31", 10),
        _v("2025-04-01", "2025-06-30", 16),  # filed discrete Q2
        _v("2025-01-01", "2025-06-30", 25),
    )
    q = discrete_quarters(vals, concepts().durations)
    assert q[D("2025-06-30")].value == 16 and not q[D("2025-06-30")].quarter_derived


def test_missing_ytd_uses_sum_of_quarters() -> None:
    """No H1 filed, but Q1 and Q2 are: Q3 = 9M − (Q1 + Q2)."""
    vals = _map(
        _v("2025-01-01", "2025-03-31", 10, filed="2025-05-01"),
        _v("2025-04-01", "2025-06-30", 15, filed="2025-08-01"),
        _v("2025-01-01", "2025-09-30", 45, filed="2025-11-01"),
    )
    q = discrete_quarters(vals, concepts().durations)
    q3 = q[D("2025-09-30")]
    assert q3.value == 20 and q3.quarter_derived
    assert q3.first_filed_value == 20 and q3.first_filed_date == D("2025-11-01")
    assert q3.source_accn == "accn-2025-09-30"


def test_gap_in_chain_leaves_quarter_missing() -> None:
    """FY and Q1 only: Q2–Q4 can't be split, so no quarter is invented."""
    vals = _map(_v("2025-01-01", "2025-03-31", 10), _v("2025-01-01", "2025-12-31", 70))
    q = discrete_quarters(vals, concepts().durations)
    assert list(q) == [D("2025-03-31")]


def test_derived_input_propagates() -> None:
    vals = _map(
        _v("2025-01-01", "2025-03-31", 10, derived=True), _v("2025-01-01", "2025-06-30", 25)
    )
    assert discrete_quarters(vals, concepts().durations)[D("2025-06-30")].derived


def test_non_additive_items_keep_only_filed_quarters() -> None:
    vals = _map(_v("2025-01-01", "2025-03-31", 1.5), _v("2025-01-01", "2025-06-30", 3.1))
    q = discrete_quarters(vals, concepts().durations, additive=False)
    assert list(q) == [D("2025-03-31")]


def test_first_filed_value_is_none_when_an_input_lacks_one() -> None:
    a = _v("2025-01-01", "2025-03-31", 10)
    b = _v("2025-01-01", "2025-06-30", 25)
    a = dataclasses.replace(a, first_filed_value=None)
    q = discrete_quarters(_map(a, b), concepts().durations)
    assert q[D("2025-06-30")].first_filed_value is None


def _item(ticker: str, item: LineItem) -> dict[Period, Value]:
    cm = concepts()
    usable = usable_facts(fixture_facts(ticker), cm, Taxonomy.US_GAAP, "USD", Rejections())
    return select_item(cm[item], Taxonomy.US_GAAP, usable[item])


@pytest.mark.parametrize(
    ("ticker", "fy_end", "q4_start", "expected_q4", "expected_fy"),
    [
        # AAPL FY2025 (Sept): Q4 revenue = 416,161 − 313,695 = 102,466 ($M).
        ("AAPL", "2025-09-27", "2025-06-29", 102_466e6, 416_161e6),
        # NVDA FY2026 (52 weeks to 25 Jan 2026).
        ("NVDA", "2026-01-25", "2025-10-27", None, None),
        # MSFT FY2026 (June).
        ("MSFT", "2026-06-30", "2026-04-01", None, None),
    ],
)
def test_q4_is_fy_minus_9m_on_real_filings(
    ticker: str,
    fy_end: str,
    q4_start: str,
    expected_q4: float | None,
    expected_fy: float | None,
) -> None:
    vals = _item(ticker, LineItem.REVENUE)
    bounds = concepts().durations
    fy = fiscal_years(vals, bounds)[D(fy_end)]
    q = discrete_quarters(vals, bounds)
    q4 = q[D(fy_end)]
    assert q4.quarter_derived
    assert q4.period.start == D(q4_start)
    year = [v for e, v in q.items() if fy.period.start and fy.period.start <= e <= D(fy_end)]
    assert len(year) == 4
    assert sum(v.value for v in year) == pytest.approx(fy.value, abs=0.5)
    if expected_q4 is not None:
        assert q4.value == expected_q4
        assert fy.value == expected_fy


def test_cash_flow_quarters_on_real_filings() -> None:
    """AAPL files operating cash flow year-to-date only; all four quarters still come out."""
    vals = _item("AAPL", LineItem.CFO)
    bounds = concepts().durations
    fy = fiscal_years(vals, bounds)[D("2025-09-27")]
    q = discrete_quarters(vals, bounds)
    year = [v for e, v in q.items() if D("2024-09-29") <= e <= D("2025-09-27")]
    assert len(year) == 4
    assert [v.quarter_derived for v in year] == [False, True, True, True]
    assert sum(v.value for v in year) == fy.value


def test_no_difference_across_different_tags() -> None:
    """FY under one tag minus 9M under another mixes alternative tags: the quarter stays unknown."""
    fy = _v("2025-01-01", "2025-12-31", 100)
    nine = dataclasses.replace(
        _v("2025-01-01", "2025-09-30", 70),
        source_tag="NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    )
    assert D("2025-12-31") not in discrete_quarters(_map(fy, nine), concepts().durations)
    # Summed quarters must match too: Q1-Q3 filed under the other tag.
    other = "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
    qs = [
        dataclasses.replace(_v(s, e, 20), source_tag=other)
        for s, e in [
            ("2025-01-01", "2025-03-31"),
            ("2025-04-01", "2025-06-30"),
            ("2025-07-01", "2025-09-30"),
        ]
    ]
    out = discrete_quarters(_map(fy, *qs), concepts().durations)
    assert D("2025-12-31") not in out and len(out) == 3


def test_derived_quarter_keeps_its_lineage() -> None:
    fy, nine = _v("2025-01-01", "2025-12-31", 100), _v("2025-01-01", "2025-09-30", 70)
    q4 = discrete_quarters(_map(fy, nine), concepts().durations)[D("2025-12-31")]
    assert q4.value == 30 and q4.tag_key == "NetCashProvidedByUsedInOperatingActivities"


def test_real_khc_options_fy_minus_issuance_9m_is_not_a_quarter() -> None:
    """KHC FY2015 stock_issued is ProceedsFromStockOptionsExercised (29M) but its 9M is
    ProceedsFromIssuanceOfCommonStock (10,000M, the merger issuance): Q4 was −9,971M."""
    cm = concepts()
    usable = usable_facts(fixture_facts("KHC"), cm, Taxonomy.US_GAAP, "USD", Rejections())
    vals = select_item(cm[LineItem.STOCK_ISSUED], Taxonomy.US_GAAP, usable[LineItem.STOCK_ISSUED])
    assert vals[Period(end=D("2016-01-03"), start=D("2014-12-29"))].source_tag == (
        "ProceedsFromStockOptionsExercised"
    )
    assert D("2016-01-03") not in discrete_quarters(vals, cm.durations)


def test_same_tag_alternative_is_used_when_winners_differ() -> None:
    """GD: the 10-K tags FY under both Revenues (wins) and RevenueFromContract…; its 10-Qs only
    the latter. Q4 = FY − 9M is taken under the shared tag."""
    rfc = "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
    fy = _v("2025-01-01", "2025-12-31", 100)
    fy_alt = dataclasses.replace(fy, source_tag=rfc, value=100)
    nine = dataclasses.replace(_v("2025-01-01", "2025-09-30", 70), source_tag=rfc)
    alts = {fy.period: {fy.source_tag or "": fy, rfc: fy_alt}, nine.period: {rfc: nine}}
    assert D("2025-12-31") not in discrete_quarters(_map(fy, nine), concepts().durations)
    q4 = discrete_quarters(_map(fy, nine), concepts().durations, alternatives=alts)[D("2025-12-31")]
    assert q4.value == 30 and q4.tag_key == rfc and q4.quarter_derived


def test_summed_quarters_stand_in_when_the_filed_ytd_has_another_tag() -> None:
    """FY and Q1-Q3 under tag A, the 9M only under tag B: Q4 = FY_A − ΣQ1..Q3_A."""
    other = "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
    fy = _v("2025-01-01", "2025-12-31", 100)
    nine = dataclasses.replace(_v("2025-01-01", "2025-09-30", 70), source_tag=other)
    qs = [
        _v("2025-01-01", "2025-03-31", 20),
        _v("2025-04-01", "2025-06-30", 25),
        _v("2025-07-01", "2025-09-30", 26),
    ]
    q4 = discrete_quarters(_map(fy, nine, *qs), concepts().durations)[D("2025-12-31")]
    assert q4.value == 100 - 71 and q4.tag_key == fy.source_tag


def test_real_aapl_q4_uses_one_tag_and_names_it() -> None:
    """AAPL FY2013 D&A: the FY winner (DepreciationAndAmortization, 5,800M) has no 9M; the 9M is
    DepreciationAmortizationAndAccretionNet (4,974M), also filed for the FY (6,757M). Q4 is taken
    under that one tag (1,783M; mixing the two gave 826M), and the tag is named in its inputs."""
    cf = normalize_company("0000320193", fixture_facts("AAPL"), concepts())
    q4 = cf.q[LineItem.DNA][D("2013-09-28")]
    assert q4.value == pytest.approx(1_783e6) and q4.quarter_derived
    assert q4.tag_key == "DepreciationAmortizationAndAccretionNet"
    assert q4.inputs[0].endswith("[DepreciationAmortizationAndAccretionNet]")
    assert cf.fy[LineItem.DNA][D("2013-09-28")].source_tag == "DepreciationAndAmortization"
