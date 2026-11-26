"""Step 8: units and currency, share-count priority, fiscal-year changes."""

import dataclasses
from datetime import date

from glint.contracts.enums import Basis, LineItem, Taxonomy
from glint.financials.facts import Fact
from glint.financials.fychange import calendar_shift, detect_changes
from glint.financials.normalize import normalize_company
from glint.financials.periods import Period
from glint.financials.select import Value
from glint.financials.shares import share_count
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat


def _sh(end: str, value: float, tag: str | None = "EntityCommonStockSharesOutstanding") -> Value:
    return Value(
        item=LineItem.SHARES_OUTSTANDING,
        period=Period(end=D(end)),
        value=value,
        unit="shares",
        source_tag=tag,
        source_accn="a",
        filed=D(end),
        first_filed_value=value,
        first_filed_date=D(end),
        derived=False,
    )


def _dil(start: str, end: str, value: float) -> Value:
    v = _sh(end, value, "WeightedAverageNumberOfDilutedSharesOutstanding")
    return dataclasses.replace(
        v, item=LineItem.DILUTED_SHARES, period=Period(end=D(end), start=D(start))
    )


# --- Units and currency -------------------------------------------------------------------------


def test_tsm_is_ifrs_in_twd() -> None:
    cf = normalize_company("0001046179", fixture_facts("TSM"), concepts())
    assert cf.taxonomy is Taxonomy.IFRS_FULL
    assert cf.currency == "TWD"
    rev = cf.latest(LineItem.REVENUE, Basis.FY)
    assert (
        rev is not None
        and rev.unit == "TWD"
        and rev.source_tag
        in {
            "Revenue",
            "RevenueFromContractsWithCustomers",
        }
    )
    eps = cf.latest(LineItem.EPS_DILUTED, Basis.FY)
    assert eps is not None and eps.unit == "TWD/shares"
    assert cf.rejections.counts["unit"] > 0  # USD convenience translations


def test_asml_reports_in_eur() -> None:
    cf = normalize_company("0000937966", fixture_facts("ASML"), concepts())
    assert cf.taxonomy is Taxonomy.US_GAAP and cf.currency == "EUR"
    rev = cf.latest(LineItem.REVENUE, Basis.FY)
    assert rev is not None and rev.unit == "EUR"


# --- Share count --------------------------------------------------------------------------------


def test_cover_page_count_wins_when_fresh() -> None:
    shares = {
        e.period.end: e
        for e in (_sh("2026-03-31", 90, "CommonStockSharesOutstanding"), _sh("2026-04-20", 100))
    }
    got = share_count(shares, {D("2026-03-31"): _dil("2026-01-01", "2026-03-31", 95)}, 365)
    assert got is not None and got.value == 100 and got.period.end == D("2026-04-20")


def test_stale_cover_count_falls_back_to_diluted() -> None:
    shares = {D("2011-04-28"): _sh("2011-04-28", 3_700)}
    got = share_count(shares, {D("2026-03-31"): _dil("2026-01-01", "2026-03-31", 4_071)}, 365)
    assert got is not None and got.value == 4_071 and got.derived and got.source_tag is None
    assert got.period == Period(end=D("2026-03-31"))
    assert got.inputs[0].startswith(
        "diluted_shares (WeightedAverageNumberOfDilutedSharesOutstanding)"
    )


def test_no_count_without_any_input() -> None:
    assert share_count({}, {}, 365) is None
    only_dil = share_count({}, {D("2026-03-31"): _dil("2026-01-01", "2026-03-31", 5)}, 365)
    assert only_dil is not None and only_dil.derived


def test_real_share_counts() -> None:
    aapl = normalize_company("0000320193", fixture_facts("AAPL"), concepts())
    s = aapl.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
    assert s is not None and s.source_tag == "EntityCommonStockSharesOutstanding"
    assert aapl.shares_as_of == D("2026-07-17") and not s.derived
    # Ford stopped tagging a single cover-page total in 2011: diluted count, flagged.
    ford = normalize_company("0000037996", fixture_facts("F"), concepts())
    fs = ford.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
    dil = ford.latest(LineItem.DILUTED_SHARES, Basis.Q)
    assert fs is not None and fs.derived and dil is not None
    assert ford.shares_as_of == dil.period.end and fs.value == dil.value
    # BRK has neither a recent count nor a diluted count: kept as filed, with a warning.
    brk = normalize_company("0001067983", fixture_facts("BRK.B"), concepts())
    assert brk.shares_as_of == D("2011-04-29")
    assert any(w.startswith("shares_outstanding: latest count is from 2011") for w in brk.warnings)


# --- Fiscal-year changes ------------------------------------------------------------------------


def test_calendar_shift() -> None:
    assert calendar_shift(D("2025-12-31"), D("2027-01-02")) == 2
    assert calendar_shift(D("2025-01-26"), D("2026-01-25")) == 1
    assert calendar_shift(D("2025-12-31"), D("2026-06-30")) == 181


def test_anab_transition_report_is_a_fiscal_year_change() -> None:
    """ANAB moved its year end from December to June: 10-KT for Jan–Jun 2026."""
    cf = normalize_company("0001370053", fixture_facts("ANAB"), concepts())
    assert len(cf.fy_changes) == 1
    ch = cf.fy_changes[0]
    assert ch.old_year_end == D("2025-12-31")
    assert ch.transition == Period(end=D("2026-06-30"), start=D("2026-01-01"))
    ttm = cf.series(LineItem.REVENUE, Basis.TTM)
    assert D("2025-12-31") in ttm  # the last full old fiscal year
    assert not [e for e in ttm if e > D("2025-12-31")]  # no TTM spans the change


def test_shifted_fiscal_year_ends_are_a_change() -> None:
    years = [
        Period(end=D("2023-12-31"), start=D("2023-01-01")),
        Period(end=D("2025-06-30"), start=D("2024-07-01")),
    ]
    changes = detect_changes([], years, concepts().durations, 10)
    assert len(changes) == 1
    assert changes[0].breaks == (D("2023-12-31"), D("2024-06-30"))


def test_comparative_in_a_10kt_is_not_the_transition() -> None:
    def f(start: str, end: str) -> Fact:
        return Fact(
            Taxonomy.US_GAAP,
            "Revenues",
            "USD",
            D(start),
            D(end),
            1.0,
            "kt",
            None,
            None,
            "10-KT",
            D("2026-09-01"),
        )

    facts = [
        f("2025-01-01", "2025-06-30"),
        f("2026-01-01", "2026-06-30"),
        f("2025-01-01", "2025-12-31"),
    ]
    changes = detect_changes(facts, [], concepts().durations, 10)
    assert [c.transition for c in changes] == [Period(end=D("2026-06-30"), start=D("2026-01-01"))]


def test_no_false_changes_for_52_53_week_or_regular_years() -> None:
    for ticker, cik in (("NVDA", "0001045810"), ("AAPL", "0000320193"), ("MSFT", "0000789019")):
        assert normalize_company(cik, fixture_facts(ticker), concepts()).fy_changes == [], ticker


def test_negative_derived_quarters_are_warned_not_changed() -> None:
    """ANAB's 10-KT restates FY2024 SBC to 7.2M (10-Ks: 34.0M); latest filed wins (rule 3), so
    Q4 2024 = FY − 9M comes out negative. It's kept, and logged."""
    cf = normalize_company("ANAB", fixture_facts("ANAB"), concepts())
    q4 = cf.q[LineItem.SBC][D("2024-12-31")]
    assert q4.value < 0 and q4.quarter_derived
    assert any(
        w.startswith("sbc: derived quarter 2024-10-01..2024-12-31 is negative") for w in cf.warnings
    )
    aapl = normalize_company("AAPL", fixture_facts("AAPL"), concepts())
    assert not [w for w in aapl.warnings if "is negative" in w]


def test_nonnegative_items_are_configured() -> None:
    cm = concepts()
    assert cm[LineItem.SBC].nonnegative and cm[LineItem.CAPEX].nonnegative
    assert not cm[LineItem.NET_INCOME].nonnegative and not cm[LineItem.CFO].nonnegative


def _capex(start: str | None, end: str, val: float, filed: str) -> Fact:
    return Fact(
        taxonomy=Taxonomy.US_GAAP,
        tag="PaymentsToAcquirePropertyPlantAndEquipment",
        unit="USD",
        start=D(start) if start else None,
        end=D(end),
        val=val,
        accn=f"a-{filed}",
        fy=None,
        fp=None,
        form="10-Q",
        filed=D(filed),
    )


def test_negative_bridged_ttm_is_warned_not_changed() -> None:
    facts = [
        _capex("2025-01-01", "2025-12-31", 100, "2026-02-01"),
        _capex("2025-01-01", "2025-06-30", 120, "2026-08-01"),  # restated above the FY
        _capex("2026-01-01", "2026-06-30", 10, "2026-08-01"),
    ]
    cf = normalize_company("X", facts, concepts())
    assert cf.ttm[LineItem.CAPEX][D("2026-06-30")].value == -10
    assert any(w.startswith("capex: TTM 2025-07-01..2026-06-30") for w in cf.warnings)
