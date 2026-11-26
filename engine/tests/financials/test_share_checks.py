"""Share-count plausibility: diluted scale errors (NI ÷ EPS check), zero and placeholder counts."""

import dataclasses
from datetime import date

import orjson
import pytest

from glint.contracts.enums import Basis, LineItem, Taxonomy
from glint.financials.concepts import ShareCheckParams
from glint.financials.facts import Fact, facts_from_companyfacts
from glint.financials.normalize import CompanyFinancials, normalize_company
from glint.financials.periods import Period
from glint.financials.select import Value
from glint.financials.share_checks import (
    check_diluted_scale,
    drop_placeholder_counts,
    same_filing_diluted,
    scale_power,
)
from tests.financials.conftest import DATA_DIR, concepts

D = date.fromisoformat
P = ShareCheckParams(
    min_count=10_000,
    placeholder_ratio=0.01,
    class_ratio=0.5,
    scale_band=0.25,
    scale_reject_ratio=100,
    check_min_eps=0.05,
    check_min_net_income=100_000,
    same_filing_max_ratio=2,
)
Q1 = Period(start=D("2026-01-01"), end=D("2026-03-31"))
Q1_LY = Period(start=D("2025-01-01"), end=D("2025-03-31"))


def _v(item: LineItem, period: Period, value: float, unit: str, tag: str) -> Value:
    return Value(
        item=item,
        period=period,
        value=value,
        unit=unit,
        source_tag=tag,
        source_accn="0000000000-26-000001",
        filed=period.end,
        first_filed_value=value,
        first_filed_date=period.end,
        derived=False,
    )


def _dil(period: Period, value: float) -> Value:
    return _v(LineItem.DILUTED_SHARES, period, value, "shares", "WeightedAverage")


def _ni(period: Period, value: float) -> Value:
    return _v(LineItem.NET_INCOME, period, value, "USD", "NetIncomeLoss")


def _eps(period: Period, value: float) -> Value:
    return _v(LineItem.EPS_DILUTED, period, value, "USD/shares", "EarningsPerShareDiluted")


def _sh(end: str, value: float) -> Value:
    return _v(LineItem.SHARES_OUTSTANDING, Period(end=D(end)), value, "shares", "CommonStock")


@pytest.mark.parametrize(
    ("ratio", "power"),
    [(1.0, 0), (0.8, 0), (1003.7, 1), (0.001, -1), (1e-6, -2), (1.1e6, 2), (5.0, None),
     (5000.0, None), (100.0, None), (-1000.0, None)],
)  # fmt: skip
def test_scale_power(ratio: float, power: int | None) -> None:
    assert scale_power(ratio, 0.25) == power


def test_in_band_value_is_the_filed_value_divided_not_ni_over_eps() -> None:
    # WAT Q2 2026: filed 98,204,000,000; NI −136M / EPS −1.39 = 97,841,727.
    r = check_diluted_scale({Q1: _dil(Q1, 98_204_000_000)}, {Q1: _ni(Q1, -136e6)},
                            {Q1: _eps(Q1, -1.39)}, P, 365)  # fmt: skip
    v = r.values[Q1]
    assert v.value == 98_204_000 and v.derived and v.source_tag is None
    assert "filed WeightedAverage 98,204,000,000" in v.inputs[0]
    assert "net_income -136,000,000 / eps_diluted -1.39 = 97,841,727" in v.inputs[0]
    assert r.rescaled == {Q1: 1} and Q1 in r.checked and not r.rejected


def test_in_thousands_is_multiplied() -> None:
    # HUBG Q3 2025: filed 60,333 (thousands); NI / EPS ≈ 60.75M.
    r = check_diluted_scale({Q1: _dil(Q1, 60_333)}, {Q1: _ni(Q1, 25.52e6)},
                            {Q1: _eps(Q1, 0.42)}, P, 365)  # fmt: skip
    assert r.values[Q1].value == 60_333_000 and r.rescaled == {Q1: -1}
    assert "× 1,000" in r.values[Q1].inputs[0]


def test_far_off_but_outside_every_band_is_rejected_not_rescaled() -> None:
    # Ratio 5,000: off by more than scale_reject_ratio, not within ±25% of a power of 1,000.
    r = check_diluted_scale({Q1: _dil(Q1, 500_000_000)}, {Q1: _ni(Q1, 1e6)},
                            {Q1: _eps(Q1, 10.0)}, P, 365)  # fmt: skip
    assert Q1 not in r.values and r.rejected == {Q1} and not r.rescaled
    assert "not a power of 1,000); dropped" in r.warnings[0]


def test_moderate_gaps_are_kept_unchecked() -> None:
    # Ratio 3 (NI to common ≠ NI, two-class EPS): kept as filed, not counted as checked.
    r = check_diluted_scale({Q1: _dil(Q1, 30e6)}, {Q1: _ni(Q1, 10e6)},
                            {Q1: _eps(Q1, 1.0)}, P, 365)  # fmt: skip
    assert r.values[Q1].value == 30e6 and not r.values[Q1].derived
    assert not r.checked and not r.rejected and not r.warnings


def test_opposite_signs_are_no_check_not_a_rejection() -> None:
    # BHR: net income (incl. noncontrolling interests) +4.4M, EPS to common −0.28.
    r = check_diluted_scale({Q1: _dil(Q1, 66.5e6)}, {Q1: _ni(Q1, 4.364e6)},
                            {Q1: _eps(Q1, -0.28)}, P, 365)  # fmt: skip
    assert r.values[Q1].value == 66.5e6 and not r.rejected and not r.checked
    bhr = _real("BHR")
    q = bhr.series(LineItem.DILUTED_SHARES, Basis.Q)
    assert q[D("2026-06-30")].value == 68_679_000 and not q[D("2026-06-30")].derived


def test_no_check_without_eps_or_with_cent_eps() -> None:
    r = check_diluted_scale({Q1: _dil(Q1, 9e9), Q1_LY: _dil(Q1_LY, 9e9)},
                            {Q1: _ni(Q1, 1e6), Q1_LY: _ni(Q1_LY, 1e6)},
                            {Q1_LY: _eps(Q1_LY, 0.01)}, P, 365)  # fmt: skip
    assert r.values[Q1].value == 9e9 and r.values[Q1_LY].value == 9e9 and not r.checked


def test_every_affected_period_is_corrected_so_yoy_does_not_mix_scales() -> None:
    dil = {Q1: _dil(Q1, 98_204_000_000), Q1_LY: _dil(Q1_LY, 59_656_000_000)}
    ni = {Q1: _ni(Q1, -136e6), Q1_LY: _ni(Q1_LY, 147e6)}
    eps = {Q1: _eps(Q1, -1.39), Q1_LY: _eps(Q1_LY, 2.47)}
    r = check_diluted_scale(dil, ni, eps, P, 365)
    assert r.values[Q1].value / r.values[Q1_LY].value - 1 == pytest.approx(0.6462, abs=1e-4)


def test_first_filed_value_is_rescaled_only_when_it_is_off_too() -> None:
    v = dataclasses.replace(_dil(Q1, 59_656_000_000), first_filed_value=59_656_000)
    r = check_diluted_scale({Q1: v}, {Q1: _ni(Q1, 147e6)}, {Q1: _eps(Q1, 2.47)}, P, 365)
    assert r.values[Q1].first_filed_value == 59_656_000


def test_counts_below_the_minimum_are_dropped() -> None:
    kept, warnings = drop_placeholder_counts(
        {D("2025-12-31"): _sh("2025-12-31", 1_000), D("2026-03-31"): _sh("2026-03-31", 1_000)},
        {}, set(), P,
    )  # fmt: skip
    assert kept == {} and len(warnings) == 2 and "below 10,000 shares" in warnings[0]


def test_latest_count_far_below_a_checked_diluted_count_is_dropped() -> None:
    q2 = Period(start=D("2026-04-01"), end=D("2026-06-30"))
    shares = {D("2025-12-31"): _sh("2025-12-31", 40e6), D("2026-03-31"): _sh("2026-03-31", 50_000)}
    dil = {q2: _dil(q2, 52.8e6)}
    kept, warnings = drop_placeholder_counts(shares, dil, {q2}, P)
    assert list(kept) == [D("2025-12-31")] and "0.01 × diluted_shares" in warnings[0]
    # The same diluted count, unchecked (no NI/EPS): nothing to judge against, count kept.
    kept, _ = drop_placeholder_counts(shares, dil, set(), P)
    assert list(kept) == [D("2025-12-31"), D("2026-03-31")]


def test_class_only_count_is_dropped_at_any_date() -> None:
    """IHRT Q3 2025 10-Q: the special-warrants count (5,039,323) tagged as the undimensioned
    CommonStockSharesOutstanding, against 155,187,000 diluted for the quarter in the same filing."""
    q3 = Period(start=D("2025-07-01"), end=D("2025-09-30"))
    nine = Period(start=D("2025-01-01"), end=D("2025-09-30"))
    accn = "0000000000-26-000001"  # _v's accession: count and diluted from one filing
    shares = {
        D("2023-12-31"): _sh("2023-12-31", 150_748_521),
        D("2025-09-30"): _sh("2025-09-30", 5_039_323),
    }
    dil = {q3: _dil(q3, 155_187_000), nine: _dil(nine, 153_991_000)}
    tag = "WeightedAverageNumberOfDilutedSharesOutstanding"
    filed = same_filing_diluted(
        [
            _fact(tag, "2025-09-30", 153_991_000, "2025-01-01"),
            _fact(tag, "2025-09-30", 155_187_000, "2025-07-01"),
        ]
    )
    assert filed == {(accn, D("2025-09-30")): (q3, 155_187_000)}
    kept, warnings = drop_placeholder_counts(shares, dil, {q3, nine}, P, filed)
    assert list(kept) == [D("2023-12-31")]
    assert len(warnings) == 1 and "0.5 × the 155,187,000 diluted_shares" in warnings[0]
    # Another filing's diluted count (a reverse split in between can't trip it): kept.
    other = {("0000000000-26-000099", D("2025-09-30")): (q3, 155_187_000.0)}
    assert list(drop_placeholder_counts(shares, dil, {q3}, P, other)[0]) == list(shares)
    # No checked diluted count for that day to corroborate the filing's: kept.
    assert list(drop_placeholder_counts(shares, dil, set(), P, filed)[0]) == list(shares)
    # The filing's diluted count is mis-scaled (WAT, x1,000) and the count is right: kept.
    scaled = {(accn, D("2025-09-30")): (q3, 155_187_000_000.0)}
    shares[D("2025-09-30")] = _sh("2025-09-30", 150e6)
    assert list(drop_placeholder_counts(shares, dil, {q3}, P, scaled)[0]) == list(shares)
    # Within half of the diluted count (buybacks, classes netted differently): kept.
    shares[D("2025-09-30")] = _sh("2025-09-30", 0.6 * 155_187_000)
    assert list(drop_placeholder_counts(shares, dil, {q3}, P, filed)[0]) == list(shares)


def test_class_only_count_falls_back_to_the_diluted_count() -> None:
    """End to end: the class-only count is dropped, the 2023 count is stale against the 2026
    diluted count, so the diluted count is used (derived)."""
    facts = [
        _fact("CommonStockSharesOutstanding", "2023-12-31", 150_748_521),
        _fact("CommonStockSharesOutstanding", "2025-09-30", 5_039_323),
    ]
    for start, end, n, ni, eps in (
        ("2025-07-01", "2025-09-30", 155_187_000, -40e6, -0.26),
        ("2026-07-01", "2026-09-30", 158_494_000, -50e6, -0.32),
    ):
        facts += [
            _fact("WeightedAverageNumberOfDilutedSharesOutstanding", end, n, start),
            _fact("NetIncomeLoss", end, ni, start)._replace(unit="USD"),
            _fact("EarningsPerShareDiluted", end, eps, start)._replace(unit="USD/shares"),
        ]
    cf = normalize_company("0000000001", facts, concepts())
    s = cf.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
    assert s is not None and s.derived and s.value == 158_494_000
    assert any("one class or instrument" in w for w in cf.warnings)


def _fact(tag: str, end: str, val: float, start: str | None = None) -> Fact:
    return Fact(Taxonomy.US_GAAP, tag, "shares", D(start) if start else None, D(end), val,
                "0000000000-26-000001", 2026, "Q1", "10-Q", D("2026-05-01"))  # fmt: skip


def test_zero_counts_are_rejected_and_the_diluted_count_is_used() -> None:
    facts = [
        _fact("CommonStockSharesOutstanding", "2026-03-31", 0),
        _fact("WeightedAverageNumberOfDilutedSharesOutstanding", "2026-03-31", 0, "2026-01-01"),
        _fact("WeightedAverageNumberOfDilutedSharesOutstanding", "2025-12-31", 7e6, "2025-10-01"),
    ]
    cf = normalize_company("0000000001", facts, concepts())
    assert cf.rejections.counts["nonpositive_shares"] == 2
    s = cf.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
    assert s is not None and s.value == 7e6 and s.derived


def _filing(accn: str, filed: str, *rows: tuple[str, str, float, str | None]) -> list[Fact]:
    return [
        Fact(
            Taxonomy.US_GAAP,
            tag,
            "shares",
            D(start) if start else None,
            D(end),
            val,
            accn,
            2026,
            "FY",
            "20-F",
            D(filed),
        )
        for tag, end, val, start in rows
    ]


def test_older_count_is_not_used_after_a_class_only_count() -> None:
    """YAAS-like: the year-old count (22.3M, before a reverse split the new filing restated) is
    within the stale window, but only the new filing's own diluted count stands in."""
    cs, wa = "CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"
    facts = _filing("a-2025", "2025-01-30", (cs, "2024-09-30", 22_304_693, None))
    facts += _filing("a-2026", "2026-01-28", (cs, "2025-09-30", 2_325_550, None),
                     (wa, "2025-09-30", 9_311_589, "2024-10-01"))  # fmt: skip
    facts += [
        _fact("NetIncomeLoss", "2025-09-30", -9.3e6, "2024-10-01")._replace(
            unit="USD", accn="a-2026"
        ),
        _fact("EarningsPerShareDiluted", "2025-09-30", -1.0, "2024-10-01")._replace(
            unit="USD/shares", accn="a-2026"
        ),
    ]
    cf = normalize_company("0000000001", facts, concepts())
    s = cf.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
    assert s is not None and s.derived and s.value == 9_311_589
    assert s.period.end == D("2025-09-30")
    # The older count stays in the history.
    assert D("2024-09-30") in cf.series(LineItem.SHARES_OUTSTANDING, Basis.MRQ)


def _real(ticker: str) -> CompanyFinancials:
    doc = orjson.loads((DATA_DIR / f"{ticker}.companyfacts.json").read_bytes())
    return normalize_company(ticker, list(facts_from_companyfacts(doc)), concepts())


def test_wat_share_count_change_is_not_a_scale_artifact() -> None:
    wat = _real("WAT")
    q = wat.series(LineItem.DILUTED_SHARES, Basis.Q)
    now = q[D("2026-07-04")]
    year_ago = q[D("2025-06-28")]  # the 10-Q's own comparative, also tagged ×1,000
    assert now.value == 98_204_000 and year_ago.value == 59_656_000
    assert now.value / year_ago.value - 1 == pytest.approx(0.646, abs=1e-3)  # BD merger shares


def test_avex_pre_ipo_count_is_not_used() -> None:
    avex = _real("AVEX")
    s = avex.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
    assert s is not None and s.derived and s.value == 52_805_593
    assert s.period.end == D("2026-06-30")


def test_tbla_mis_scaled_eps_does_not_drive_a_rescale() -> None:
    # Taboola's Q2 2026 10-Q tags diluted shares ×1,000 *and* 6M diluted EPS ×1,000 (−40 for
    # −$0.04), so NI ÷ EPS says ÷1,000,000. Corroboration against the clean Q1 2026 10-Q
    # (288.8M) rejects the filing's diluted counts instead; the count falls back to Q1 2026.
    tbla = _real("TBLA")
    q = tbla.series(LineItem.DILUTED_SHARES, Basis.Q)
    assert D("2026-06-30") not in q and D("2025-06-30") not in q
    s = tbla.latest(LineItem.SHARES_OUTSTANDING, Basis.MRQ)
    assert s is not None and s.value == 288_764_244 and s.period.end == D("2026-03-31")
    assert any("the check itself is off" in w for w in tbla.warnings)


def test_corroboration_keeps_a_filed_value_that_agrees_with_a_clean_filing() -> None:
    # The check says ×1,000 (EPS mis-scaled), but the filed count matches the clean neighbour.
    dil = {Q1: _in(_dil(Q1, 60e6), "bad"), Q1_LY: _in(_dil(Q1_LY, 58e6), "clean")}
    r = check_diluted_scale(dil, {Q1: _ni(Q1, 60e6)}, {Q1: _eps(Q1, 1000.0)}, P, 365)
    assert r.values[Q1].value == 60e6 and not r.rescaled
    assert any("kept as filed" in w for w in r.warnings)


Q2 = Period(start=D("2026-04-01"), end=D("2026-06-30"))
Q2_LY = Period(start=D("2025-04-01"), end=D("2025-06-30"))


def _in(v: Value, accn: str) -> Value:
    return dataclasses.replace(v, source_accn=accn)


def test_unchecked_period_takes_its_filings_correction() -> None:
    # TEM Q2 2026 10-Q: EPS 0.03 (no check) for the quarter; the comparative quarter in the same
    # filing checks at ×1,000. Both are in thousands, so both are corrected.
    dil = {Q2: _in(_dil(Q2, 182_397), "f2"), Q2_LY: _in(_dil(Q2_LY, 173_381), "f2")}
    ni = {Q2: _ni(Q2, 5.642e6), Q2_LY: _ni(Q2_LY, -42.843e6)}
    eps = {Q2: _eps(Q2, 0.03), Q2_LY: _eps(Q2_LY, -0.25)}
    r = check_diluted_scale(dil, ni, eps, P, 365)
    assert r.values[Q2].value == 182_397_000 and r.values[Q2_LY].value == 173_381_000
    assert r.rescaled == {Q2: -1, Q2_LY: -1} and Q2 not in r.checked
    assert "same filing as 2025-04-01..2025-06-30" in r.values[Q2].inputs[0]


def test_no_filing_correction_when_the_filing_disagrees_or_is_far_off() -> None:
    # A filing with one period at ×1,000 and one fine: unclear, the unchecked one stays.
    dil = {Q1: _in(_dil(Q1, 60e9), "f1"), Q1_LY: _in(_dil(Q1_LY, 59e6), "f1"),
           Q2: _in(_dil(Q2, 61e9), "f1")}  # fmt: skip
    ni = {Q1: _ni(Q1, 60e6), Q1_LY: _ni(Q1_LY, 59e6), Q2: _ni(Q2, 1e6)}
    eps = {Q1: _eps(Q1, 1.0), Q1_LY: _eps(Q1_LY, 1.0), Q2: _eps(Q2, 0.01)}
    r = check_diluted_scale(dil, ni, eps, P, 365)
    assert r.values[Q2].value == 61e9 and Q2 not in r.rescaled
    # Same power everywhere, but the unchecked value is 10× the corrected one: left as filed.
    dil = {Q1: _in(_dil(Q1, 60e9), "f1"), Q2: _in(_dil(Q2, 600e9), "f1")}
    r = check_diluted_scale(dil, {Q1: _ni(Q1, 60e6)}, {Q1: _eps(Q1, 1.0)}, P, 365)
    assert r.values[Q2].value == 600e9


def test_diluted_counts_below_the_minimum_are_dropped() -> None:
    # KLRA: pre-IPO quarter with 1 share (EPS per 1,000 shares), so no share-count change from it.
    r = check_diluted_scale(
        {Q1_LY: _dil(Q1_LY, 1), Q1: _dil(Q1, 102e6)},
        {Q1_LY: _ni(Q1_LY, -28.947e6)},
        {Q1_LY: _eps(Q1_LY, -28_947)},
        P,
        365,
    )
    assert list(r.values) == [Q1] and Q1_LY in r.rejected
