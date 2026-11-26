"""Untagged dividends, buybacks and issuance count as none when the period's cash-flow statement
is tagged (CFO present at the TTM end); otherwise MISSING_INPUT (user decision 2026-10-30)."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

NOW = date(2026, 6, 30)


def base(cik: str, *, cfo: bool = True, **flows: float) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = [
        (cik, "net_income", "ttm", NOW, 50),
        (cik, "fcf", "ttm", NOW, 40, True),
        (cik, "equity", "mrq", NOW, 400),
        (cik, "shares_outstanding", "mrq", date(2026, 7, 25), 10),
    ]
    if cfo:
        rows.append((cik, "cfo", "ttm", NOW, 60))
    return rows + [(cik, k, "ttm", NOW, v) for k, v in flows.items()]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        *base("N"),  # pays nothing, tags nothing, cash-flow statement filed
        *base("B", buybacks=30),  # buys back, no issuance tag
        *base("X", cfo=False),  # no cash-flow statement for the period
    ]
    cos = [{"cik": c, "tickers": [f"T{c}"], "primary_ticker": f"T{c}"} for c in "NBX"]
    return run(rows, cos, [{"ticker": f"T{c}", "close": 50.0} for c in "NBX"])


def test_non_payer_is_zero_with_a_note(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "N", "dividend_yield")
    assert (v, c) == (0.0, "DERIVED_INPUT")
    assert m is not None and "dividends_paid_ttm (not tagged; cash-flow statement filed" in m
    assert cell(out, "N", "buyback_yield")[0] == 0.0
    assert cell(out, "N", "shareholder_yield")[0] == 0.0
    assert cell(out, "N", "payout_ratio")[0] == 0.0
    assert cell(out, "N", "fcf_payout_ratio")[0] == 0.0


def test_partial_tags(out: pl.DataFrame) -> None:
    assert cell(out, "B", "buyback_yield")[0] == pytest.approx(30 / 500)  # issuance counts as none
    assert cell(out, "B", "shareholder_yield")[0] == pytest.approx(30 / 500)


def test_no_cash_flow_statement_stays_missing(out: pl.DataFrame) -> None:
    for mid in ("dividend_yield", "buyback_yield", "shareholder_yield"):
        assert cell(out, "X", mid)[:2] == (None, "MISSING_INPUT"), mid
