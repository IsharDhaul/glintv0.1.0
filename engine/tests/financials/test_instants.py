"""Instants (MRQ, year-ago within ±45 days) and per-company series history."""

from datetime import date

from glint.contracts.enums import Basis, LineItem
from glint.financials.instants import last_n, latest, nearest, one_year_before, year_ago
from glint.financials.normalize import keep_from, normalize_company
from glint.financials.periods import Period
from glint.financials.select import Value
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat


def _i(end: str, value: float) -> Value:
    return Value(
        item=LineItem.EQUITY,
        period=Period(end=D(end)),
        value=value,
        unit="USD",
        source_tag="StockholdersEquity",
        source_accn="a",
        filed=D(end),
        first_filed_value=value,
        first_filed_date=D(end),
        derived=False,
    )


SERIES = {v.period.end: v for v in (_i("2024-06-29", 1), _i("2024-09-28", 2), _i("2025-06-28", 3))}


def test_one_year_before() -> None:
    assert one_year_before(D("2025-06-28")) == D("2024-06-28")
    assert one_year_before(D("2024-02-29")) == D("2023-02-28")


def test_mrq_and_year_ago() -> None:
    mrq = latest(SERIES)
    assert mrq is not None and mrq.value == 3
    ago = year_ago(SERIES, D("2025-06-28"), 45)
    assert ago is not None and ago.period.end == D("2024-06-29")
    assert year_ago(SERIES, D("2025-12-31"), 45) is None
    assert latest({}) is None


def test_nearest_ties_prefer_the_earlier_end() -> None:
    s = {v.period.end: v for v in (_i("2025-01-01", 1), _i("2025-01-05", 2))}
    hit = nearest(s, D("2025-01-03"), 45)
    assert hit is not None and hit.value == 1


def test_last_n() -> None:
    assert list(last_n(SERIES, 2)) == [D("2024-09-28"), D("2025-06-28")]
    assert last_n(SERIES, 0) == {}


def test_company_series_and_rows() -> None:
    cf = normalize_company("0000320193", fixture_facts("AAPL"), concepts())
    assert cf.currency == "USD"
    assets = cf.latest(LineItem.TOTAL_ASSETS, Basis.MRQ)
    assert assets is not None and assets.period.end == D("2026-06-27")
    ago = year_ago(cf.series(LineItem.TOTAL_ASSETS, Basis.MRQ), assets.period.end, 45)
    assert ago is not None and ago.period.end == D("2025-06-28")
    # FY-basis instants sit on fiscal year ends only.
    fy_assets = cf.series(LineItem.TOTAL_ASSETS, Basis.FY)
    assert D("2025-09-27") in fy_assets and D("2026-06-27") not in fy_assets
    assert cf.series(LineItem.TOTAL_ASSETS, Basis.TTM) == {}

    rows = cf.rows(keep_from(concepts()))
    by_key = {(r.line_item, r.basis, r.period_end): r for r in rows}
    assert len(by_key) == len(rows)  # the table's primary key holds
    rev = [r for r in rows if r.line_item == "revenue"]
    assert sum(r.basis == "fy" for r in rev) == 10
    assert sum(r.basis == "ttm" for r in rev) == 12
    assert sum(r.basis == "q" for r in rev) == 12
    assert sum(r.line_item == "total_assets" and r.basis == "mrq" for r in rows) == 12
    q4 = by_key[("revenue", "q", D("2025-09-27"))]
    assert q4.derived and q4.source_tag is None and q4.value == 102_466e6
    ttm = by_key[("revenue", "ttm", D("2025-09-27"))]
    assert (
        not ttm.derived and ttm.source_tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    latest_ttm = by_key[("revenue", "ttm", D("2026-06-27"))]
    assert latest_ttm.value == 143_756e6 + 111_184e6 + 109_417e6 + 102_466e6
