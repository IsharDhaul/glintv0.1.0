"""TTM: 4 contiguous quarters, FY at a fiscal year end, never across a fiscal-year change."""

from dataclasses import replace
from datetime import date

import pytest

from glint.contracts.enums import LineItem, Taxonomy
from glint.financials.periods import Period
from glint.financials.quarters import discrete_quarters, fiscal_years
from glint.financials.select import Rejections, Value, select_item, usable_facts
from glint.financials.ttm import four_quarters, ttm_series
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat


def _v(start: str, end: str, value: float, *, derived: bool = False) -> Value:
    return Value(
        item=LineItem.REVENUE,
        period=Period(end=D(end), start=D(start)),
        value=value,
        unit="USD",
        source_tag="Revenues",
        source_accn=f"a-{end}",
        filed=D(end),
        first_filed_value=value,
        first_filed_date=D(end),
        derived=derived,
    )


QUARTERS = [
    _v("2024-10-01", "2024-12-31", 9),
    _v("2025-01-01", "2025-03-31", 10),
    _v("2025-04-01", "2025-06-30", 11),
    _v("2025-07-01", "2025-09-30", 12),
    _v("2025-10-01", "2025-12-31", 13, derived=True),
]


def _q(*vs: Value) -> dict[date, Value]:
    return {v.period.end: v for v in vs}


def test_sum_of_four_contiguous_quarters() -> None:
    res = ttm_series({}, _q(*QUARTERS), concepts().durations)
    assert list(res.values) == [D("2025-09-30"), D("2025-12-31")]
    t = res.values[D("2025-12-31")]
    assert t.value == 10 + 11 + 12 + 13
    assert t.period == Period(end=D("2025-12-31"), start=D("2025-01-01"))
    assert t.derived and t.source_tag is None and t.source_accn == "a-2025-12-31"
    assert len(t.inputs) == 4
    assert not res.values[D("2025-09-30")].derived


def test_missing_quarter_means_no_ttm() -> None:
    qs = _q(*(q for q in QUARTERS if q.period.end != D("2025-06-30")))
    assert ttm_series({}, qs, concepts().durations).values == {}
    assert four_quarters(D("2026-03-31"), qs) is None


def test_fy_end_uses_fy_and_checks_quarters() -> None:
    fy = _v("2025-01-01", "2025-12-31", 46)
    res = ttm_series({fy.period.end: fy}, _q(*QUARTERS), concepts().durations)
    assert res.values[D("2025-12-31")] == fy
    assert res.warnings == []
    off = _v("2025-01-01", "2025-12-31", 50)
    res = ttm_series({off.period.end: off}, _q(*QUARTERS), concepts().durations)
    assert res.values[D("2025-12-31")].value == 50
    assert len(res.warnings) == 1 and "2025-12-31" in res.warnings[0]


def test_fy_alone_still_gives_ttm() -> None:
    """A semiannual or annual-only filer: TTM exists at fiscal year ends only."""
    fy = _v("2025-01-01", "2025-12-31", 46)
    assert ttm_series({fy.period.end: fy}, {}, concepts().durations).values == {fy.period.end: fy}


def test_non_additive_has_ttm_only_at_fy() -> None:
    fy = _v("2025-01-01", "2025-12-31", 46)
    res = ttm_series({fy.period.end: fy}, _q(*QUARTERS), concepts().durations, additive=False)
    assert list(res.values) == [D("2025-12-31")]


def test_no_ttm_across_a_fiscal_year_change() -> None:
    res = ttm_series({}, _q(*QUARTERS), concepts().durations, breaks=[D("2025-06-30")])
    assert res.values == {}
    res = ttm_series({}, _q(*QUARTERS), concepts().durations, breaks=[D("2025-09-30")])
    assert list(res.values) == [D("2025-09-30")]


def test_four_quarters_that_do_not_span_a_year_are_rejected() -> None:
    """Contiguous but short (e.g. a 2-month stub): no TTM."""
    qs = [
        _v("2025-01-01", "2025-03-31", 1),
        _v("2025-04-01", "2025-06-30", 1),
        _v("2025-07-01", "2025-09-30", 1),
        _v("2025-10-01", "2025-11-20", 1),
    ]
    assert ttm_series({}, _q(*qs), concepts().durations).values == {}


@pytest.mark.parametrize(
    ("ticker", "fy_end"),
    [("AAPL", "2025-09-27"), ("MSFT", "2026-06-30"), ("KO", "2025-12-31"), ("NVDA", "2026-01-25")],
)
@pytest.mark.parametrize("item", [LineItem.REVENUE, LineItem.NET_INCOME, LineItem.CFO])
def test_ttm_at_fy_end_matches_fy_and_quarters(ticker: str, fy_end: str, item: LineItem) -> None:
    """Acceptance: TTM at the last FY end = FY (within 0.5%), and Σ4 discrete quarters = TTM."""
    cm = concepts()
    usable = usable_facts(fixture_facts(ticker), cm, Taxonomy.US_GAAP, "USD", Rejections())
    vals = select_item(cm[item], Taxonomy.US_GAAP, usable[item])
    fys = fiscal_years(vals, cm.durations)
    qs = discrete_quarters(vals, cm.durations)
    res = ttm_series(fys, qs, cm.durations)
    end = D(fy_end)
    assert res.values[end].value == pytest.approx(fys[end].value, rel=0.005)
    four = four_quarters(end, qs)
    assert four is not None
    assert sum(q.value for q in four) == res.values[end].value
    # Older years may warn (e.g. MSFT FY2016 was restated for ASC 606; its old 10-Qs weren't).
    assert not [w for w in res.warnings if fy_end in w]


# Waters (WAT) capex, as filed: its 2025 10-Qs used a net-of-proceeds tag, so the 9M 2025
# year-to-date is missing under the mapped tag and Q3/Q4 2025 can't be split.
WAT_FY = _v("2025-01-01", "2025-12-31", 112_745_000)
WAT_YTD = [
    _v("2025-01-01", "2025-03-29", 26_000_000),
    _v("2025-01-01", "2025-06-28", 49_000_000),
    WAT_FY,
    _v("2026-01-01", "2026-04-04", 39_000_000),
    _v("2026-01-01", "2026-07-04", 87_000_000),
]


def _ytd(*vs: Value) -> dict[Period, Value]:
    return {v.period: v for v in vs}


def _wat(breaks: tuple[date, ...] = ()) -> dict[date, Value]:
    cm = concepts()
    vals = _ytd(*WAT_YTD)
    qs = discrete_quarters(vals, cm.durations)
    fys = fiscal_years(vals, cm.durations)
    return ttm_series(fys, qs, cm.durations, ytd=vals, breaks=breaks).values


def test_fy_plus_ytd_minus_prior_ytd_when_quarters_are_missing() -> None:
    res = _wat()
    h1 = res[D("2026-07-04")]
    assert h1.value == 112_745_000 + 87_000_000 - 49_000_000
    assert h1.period == Period(end=D("2026-07-04"), start=D("2025-06-29"))
    assert h1.source_tag is None and not h1.derived
    assert h1.inputs == (
        "FY 2025-01-01..2025-12-31",
        "+ 2026-01-01..2026-07-04",
        "− 2025-01-01..2025-06-28",
        "[Revenues]",
    )
    assert h1.first_filed_value == h1.value and h1.source_accn == "a-2026-07-04"
    q1 = res[D("2026-04-04")]  # Q1 is a year-to-date too; Q2-Q4 2025 aren't all known
    assert q1.value == 112_745_000 + 39_000_000 - 26_000_000
    assert res[D("2025-12-31")] == WAT_FY


def test_bridge_not_across_a_fiscal_year_change() -> None:
    assert D("2026-07-04") not in _wat(breaks=(D("2025-12-31"),))


def test_bridge_needs_same_length_prior_ytd_and_a_year_span() -> None:
    cm = concepts()
    fy = WAT_FY
    cur = _v("2026-01-01", "2026-07-04", 87)
    nine = _v("2025-01-01", "2025-09-27", 70)  # different class than the 6M year-to-date
    vals = _ytd(fy, cur, nine)
    assert ttm_series({fy.period.end: fy}, {}, cm.durations, ytd=vals).values == {fy.period.end: fy}
    # An odd-length stub ending on the same day is skipped; the 6M year-to-date still bridges.
    stub = _v("2026-05-05", "2026-07-04", 30)
    vals = _ytd(fy, stub, cur, _v("2025-01-01", "2025-06-28", 49))
    t = ttm_series({fy.period.end: fy}, {}, cm.durations, ytd=vals).values
    assert t[D("2026-07-04")].value == fy.value + 87 - 49
    # A year-to-date that doesn't start right after a FY: no bridge.
    late = _v("2026-02-01", "2026-07-31", 87)
    h1 = _v("2025-01-01", "2025-06-28", 49)
    vals = _ytd(fy, late, h1)
    assert D("2026-07-31") not in ttm_series({fy.period.end: fy}, {}, cm.durations, ytd=vals).values


def test_bridge_carries_derived_inputs_and_skips_non_additive() -> None:
    cm = concepts()
    fy = _v("2025-01-01", "2025-12-31", 100, derived=True)
    cur, prior = _v("2026-01-01", "2026-06-30", 60), _v("2025-01-01", "2025-06-30", 50)
    vals = _ytd(fy, cur, prior)
    res = ttm_series({fy.period.end: fy}, {}, cm.durations, ytd=vals)
    assert res.values[D("2026-06-30")].value == 110 and res.values[D("2026-06-30")].derived
    res = ttm_series({fy.period.end: fy}, {}, cm.durations, ytd=vals, additive=False)
    assert list(res.values) == [D("2025-12-31")]


def test_bridge_first_filed_needs_every_input() -> None:
    cm = concepts()
    fy = _v("2025-01-01", "2025-12-31", 100)
    cur = replace(_v("2026-01-01", "2026-06-30", 60), first_filed_value=None, first_filed_date=None)
    prior = _v("2025-01-01", "2025-06-30", 50)
    t = ttm_series({fy.period.end: fy}, {}, cm.durations, ytd=_ytd(fy, cur, prior)).values
    assert t[D("2026-06-30")].first_filed_value is None
    assert t[D("2026-06-30")].first_filed_date is None


@pytest.mark.parametrize("ticker", ["AAPL", "MSFT", "KO", "NVDA"])
@pytest.mark.parametrize("item", [LineItem.REVENUE, LineItem.CFO])
def test_bridge_matches_four_quarters_where_both_exist(ticker: str, item: LineItem) -> None:
    """The fallback is the same arithmetic: on real filings it agrees with Σ4 quarters."""
    cm = concepts()
    usable = usable_facts(fixture_facts(ticker), cm, Taxonomy.US_GAAP, "USD", Rejections())
    vals = select_item(cm[item], Taxonomy.US_GAAP, usable[item])
    fys = fiscal_years(vals, cm.durations)
    summed = ttm_series(fys, discrete_quarters(vals, cm.durations), cm.durations).values
    bridged = ttm_series(fys, {}, cm.durations, ytd=vals).values
    shared = [e for e in bridged if e in summed and e not in fys and e >= D("2023-01-01")]
    assert shared, "expected quarter ends with both a Σ4 and a bridged TTM"
    for e in shared:
        assert bridged[e].value == pytest.approx(summed[e].value, rel=0.005), e


def test_bridge_needs_one_tag_across_its_inputs() -> None:
    cm = concepts()
    fy = WAT_FY
    cur = _v("2026-01-01", "2026-07-04", 87)
    prior = replace(
        _v("2025-01-01", "2025-06-28", 49),
        source_tag="RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    t = ttm_series({fy.period.end: fy}, {}, cm.durations, ytd=_ytd(fy, cur, prior)).values
    assert D("2026-07-04") not in t


def test_bridge_uses_a_shared_tag_when_winners_differ() -> None:
    cm = concepts()
    rfc = "RevenueFromContractWithCustomerExcludingAssessedTax"
    fy = WAT_FY
    cur = _v("2026-01-01", "2026-07-04", 87)
    prior = replace(_v("2025-01-01", "2025-06-28", 49), source_tag=rfc)
    alts = {
        fy.period: {"Revenues": fy, rfc: replace(fy, source_tag=rfc)},
        cur.period: {"Revenues": cur, rfc: replace(cur, source_tag=rfc)},
        prior.period: {rfc: prior},
    }
    t = ttm_series(
        {fy.period.end: fy}, {}, cm.durations, ytd=_ytd(fy, cur, prior), alternatives=alts
    )
    v = t.values[D("2026-07-04")]
    assert v.value == fy.value + 87 - 49 and v.tag_key == rfc
