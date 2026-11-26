"""Valuation, EV, debt, ROIC, Greenblatt, Altman and EPS growth on one hand-built company.

V: price $50 × 10 shares = market cap 500.
MRQ 2026-06-30: total_debt 200 (derived), cash 80, st_investments 20, preferred untagged,
minority_interest 10, equity 250, current assets 300 / liabilities 150, debt_current 30,
total_liabilities 400, receivables 60, goodwill 50, intangibles 25, total_assets 700, ppe 220,
retained earnings 150. A year earlier: total_debt 180, cash 70, st_investments untagged,
minority 10, equity 230.
TTM: revenue 1,000, EBIT 120, EBITDA 160 (derived), NI 80, FCF 60 (derived), dividends 20,
buybacks 30, stock issued 5, pretax 100, tax 20, interest 15; diluted shares 10 (quarter at the
TTM end). TTM a year earlier: NI 60, diluted shares 12.
"""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date
NOW, YEAR_AGO = D(2026, 6, 30), D(2025, 6, 30)
DERIVED = {"total_debt", "ebitda", "fcf"}


def at(cik: str, basis: str, end: date, **items: float) -> list[tuple[object, ...]]:
    return [(cik, k, basis, end, v, k in DERIVED) for k, v in items.items()]


def company(cik: str, **over: float) -> list[tuple[object, ...]]:
    mrq: dict[str, float] = {"total_debt": 200, "cash": 80, "st_investments": 20, "minority_interest": 10, "equity": 250,
               "current_assets": 300, "current_liabilities": 150, "debt_current": 30,
               "total_liabilities": 400, "receivables": 60, "goodwill": 50, "intangibles": 25,
               "total_assets": 700, "ppe_net": 220, "retained_earnings": 150}  # fmt: skip
    ttm: dict[str, float] = {"revenue": 1000, "operating_income": 120, "ebitda": 160, "net_income": 80, "fcf": 60,
               "dividends_paid": 20, "buybacks": 30, "stock_issued": 5, "pretax_income": 100, "income_tax": 20,
               "interest_expense": 15}  # fmt: skip
    for k, v in over.items():
        (mrq if k in mrq else ttm)[k] = v
    return [
        *at(cik, "mrq", NOW, **mrq),
        *at(cik, "mrq", YEAR_AGO, total_debt=180, cash=70, minority_interest=10, equity=230),
        *at(cik, "ttm", NOW, **ttm),
        *at(cik, "ttm", YEAR_AGO, net_income=60),
        (cik, "diluted_shares", "q", NOW, 10),
        (cik, "diluted_shares", "q", YEAR_AGO, 12),
        (cik, "shares_outstanding", "mrq", D(2026, 7, 25), 10),
    ]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        *company("V"),
        *company("W", pretax_income=-10, income_tax=2),  # loss before tax → 21%
        *company("X", income_tax=50),  # 50% effective → clamped to 35%
        *company("N", equity=-40, operating_income=-5, ebitda=-1, net_income=-3),
        *[r for r in company("Q") if r[1] != "total_debt"],  # debt untagged: strict
        *company("K"),  # a bank
        *company("C"),  # 40-F, USD: price metrics allowed
        *company("T"),  # 20-F, USD: FOREIGN_PRICE_BASIS
    ]
    cos = [{"cik": c, "tickers": [f"T{c}"], "primary_ticker": f"T{c}", "last_annual_form": "10-K"}
           for c in "VWXNQ"]  # fmt: skip
    cos += [
        {"cik": "K", "tickers": ["TK"], "primary_ticker": "TK", "sector": "Banks",
         "last_annual_form": "10-K"},
        {"cik": "C", "tickers": ["TC"], "primary_ticker": "TC", "is_foreign_filer": True,
         "last_annual_form": "40-F"},
        {"cik": "T", "tickers": ["TT"], "primary_ticker": "TT", "is_foreign_filer": True,
         "last_annual_form": "20-F"},
    ]  # fmt: skip
    prices = [{"ticker": f"T{c}", "close": 50.0} for c in "VWXNQKCT"]
    return run(rows, cos, prices)


@pytest.mark.parametrize(
    ("metric_id", "value"),
    [
        ("market_cap", 500.0),
        ("enterprise_value", 610.0),  # 500 + 200 + 0 + 10 − 80 − 20
        ("pe_ttm", 6.25),
        ("earnings_yield", 0.16),
        ("ev_ebit", 610 / 120),
        ("ebit_ev", 120 / 610),
        ("ev_ebitda", 610 / 160),
        ("ev_sales", 0.61),
        ("p_fcf", 500 / 60),
        ("fcf_yield", 0.12),
        ("pb", 2.0),
        ("dividend_yield", 0.04),
        ("buyback_yield", 0.05),  # (30 − 5) / 500
        ("shareholder_yield", 0.09),
        ("ncav_to_mcap", -0.2),  # (300 − 400) / 500
        ("net_debt", 100.0),  # 200 − 80 − 20
        ("net_debt_to_ebitda", 0.625),
        ("debt_to_equity", 0.8),
        ("quick_ratio", 160 / 150),  # (80 + 20 + 60) / 150
        ("cash_to_mcap", 0.2),
        ("goodwill_to_assets", 75 / 700),
        # NOPAT 120 × (1 − 20/100) = 96; IC (200+250+10−80−20) = 360 and (180+230+10−70−0) = 350
        ("roic", 96 / 355),
        ("greenblatt_roc", 0.4),  # 120 / ((300 − 80 − 20) − (150 − 30) + 220)
        # 1.2·150/700 + 1.4·150/700 + 3.3·120/700 + 0.6·500/400 + 1,000/700
        ("altman_z", 1.2 * 150 / 700 + 1.4 * 150 / 700 + 3.3 * 120 / 700 + 0.75 + 1000 / 700),
        ("eps_growth_yoy", 0.6),  # (80 / 10) / (60 / 12) − 1
    ],
)
def test_values(out: pl.DataFrame, metric_id: str, value: float) -> None:
    assert cell(out, "V", metric_id)[0] == pytest.approx(value, rel=1e-12)


def test_untagged_parts_count_as_none_with_a_note(out: pl.DataFrame) -> None:
    _, code, msg = cell(out, "V", "enterprise_value")
    assert code == "DERIVED_INPUT"
    assert msg == (
        "uses derived input: total_debt_mrq, preferred_mrq (not tagged, counted as none)"
    )


def test_tax_rate_rules(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "W", "roic")
    assert v == pytest.approx(120 * 0.79 / 355)
    assert c == "ASSUMED_TAX_RATE"
    assert m == "pretax income ≤ 0, so NOPAT uses the 21% statutory rate"
    assert cell(out, "X", "roic")[0] == pytest.approx(120 * 0.65 / 355)


def test_negative_paths(out: pl.DataFrame) -> None:
    assert cell(out, "N", "pe_ttm")[:2] == (None, "NEGATIVE_DENOMINATOR")
    assert cell(out, "N", "earnings_yield")[0] == pytest.approx(-0.006)
    assert cell(out, "N", "pb") == (None, "NEGATIVE_DENOMINATOR", "equity_mrq ≤ 0")
    assert cell(out, "N", "debt_to_equity")[:2] == (None, "NEGATIVE_DENOMINATOR")
    assert cell(out, "N", "ev_ebit")[:2] == (None, "NEGATIVE_DENOMINATOR")
    assert cell(out, "N", "ebit_ev")[0] == pytest.approx(-5 / 610)  # EV ignores equity: 610
    assert cell(out, "N", "net_debt_to_ebitda")[:2] == (None, "NEGATIVE_DENOMINATOR")


def test_untagged_debt_is_missing(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "Q", "enterprise_value")
    assert (v, c) == (None, "MISSING_INPUT")
    assert m is not None and m.startswith("total_debt_mrq: total_debt is not reported")
    assert cell(out, "Q", "roic")[1] == "MISSING_INPUT"
    assert cell(out, "Q", "pe_ttm")[0] == pytest.approx(6.25)


def test_bank_and_foreign(out: pl.DataFrame) -> None:
    for mid in ("enterprise_value", "ev_ebit", "roic", "current_ratio", "altman_z"):
        assert cell(out, "K", mid)[1] == "NOT_APPLICABLE_SECTOR", mid
    assert cell(out, "K", "pe_ttm")[0] == pytest.approx(6.25)
    assert cell(out, "C", "market_cap")[0] == 500.0
    v, c, _m = cell(out, "T", "market_cap")
    assert (v, c) == (None, "FOREIGN_PRICE_BASIS")
    assert cell(out, "T", "pe_ttm")[1] == "FOREIGN_PRICE_BASIS"
    assert cell(out, "T", "operating_margin")[0] == pytest.approx(0.12)
