"""Audit-driven rules (user decisions 2026-10-30): no common listing; non-USD amounts."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date
NOW = D(2026, 6, 30)


def rows(cik: str) -> list[tuple[object, ...]]:
    return [
        (cik, "revenue", "ttm", NOW, 1000),
        (cik, "operating_income", "ttm", NOW, 100),
        (cik, "net_income", "ttm", NOW, 50),
        (cik, "ebitda", "ttm", NOW, 150, True),
        (cik, "total_debt", "mrq", NOW, 200, True),
        (cik, "cash", "mrq", NOW, 80),
        (cik, "equity", "mrq", NOW, 400),
        (cik, "shares_outstanding", "mrq", D(2026, 7, 25), 10),
    ]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    cos = [
        # preferred-only listing (EIDP-like)
        {"cik": "P", "tickers": ["CTA.PB"], "primary_ticker": "CTA.PB"},
        # domestic filer reporting in EUR
        {"cik": "E", "tickers": ["EU"], "primary_ticker": "EU", "reporting_currency": "EUR"},
        # foreign 20-F in TWD (FOREIGN scope already)
        {"cik": "T", "tickers": ["TW"], "primary_ticker": "TW", "is_foreign_filer": True,
         "reporting_currency": "TWD", "last_annual_form": "20-F"},
        {"cik": "U", "tickers": ["US"], "primary_ticker": "US", "last_annual_form": "10-K"},
    ]  # fmt: skip
    for c in cos:
        c.setdefault("last_annual_form", "10-K")
    prices = [{"ticker": t, "close": 50.0} for t in ("CTA.PB", "EU", "TW", "US")]
    return run([r for c in "PETU" for r in rows(c)], cos, prices)


def test_no_common_listing(out: pl.DataFrame) -> None:
    for mid in ("price", "market_cap", "pe_ttm", "enterprise_value"):
        v, c, m = cell(out, "P", mid)
        assert (v, c) == (None, "MISSING_INPUT"), mid
        assert m is not None and "no common share listing (only preferred CTA.PB)" in m
    assert cell(out, "P", "operating_margin")[0] == pytest.approx(0.1)  # fundamentals stay


def test_non_usd_amounts(out: pl.DataFrame) -> None:
    for cik in ("E", "T"):
        for mid in ("revenue_ttm", "net_debt", "pe_ttm", "ev_ebit", "pb", "earnings_yield"):
            v, c, _ = cell(out, cik, mid)
            assert (v, c) == (None, "FOREIGN_PRICE_BASIS"), (cik, mid)
    v, c, m = cell(out, "E", "revenue_ttm")
    assert m is not None and "EUR" in m
    assert cell(out, "E", "market_cap")[0] == 500.0  # USD price × shares: no currency mix
    assert cell(out, "E", "operating_margin")[0] == pytest.approx(0.1)  # currency cancels
    assert cell(out, "U", "revenue_ttm")[0] == 1000.0
    assert cell(out, "U", "pe_ttm")[0] == pytest.approx(10.0)


def test_currency_free_ratio_survives(out: pl.DataFrame) -> None:
    # EUR reporter: (200 − 80) / 150 = 0.8, the currency cancels
    assert cell(out, "E", "net_debt_to_ebitda")[0] == pytest.approx(0.8)
