"""Size, liquidity and price metrics: hand-computed values and every null path."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date


def co(cik: str, ticker: str | None, **kw: object) -> dict[str, object]:
    return {"cik": cik, "tickers": [ticker] if ticker else [], "primary_ticker": ticker, **kw}


COVER = D(2026, 7, 25)


def base(
    cik: str, shares: float = 11, shares_at: date = COVER, derived: bool = False
) -> list[tuple[object, ...]]:
    return [
        (cik, "revenue", "ttm", D(2026, 6, 30), 400),
        (cik, "equity", "mrq", D(2026, 6, 30), 200),
        (cik, "shares_outstanding", "mrq", shares_at, shares, derived),
    ]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        *base("A"), *base("B"), *base("C"), *base("D"), *base("E", derived=True),
        *base("F", shares_at=D(2011, 4, 29)), *base("G"),
        # balance-sheet count at 06-30, filed 08-20, after the 08-10 split: already restated
        ("I", "revenue", "ttm", D(2026, 6, 30), 400), ("I", "equity", "mrq", D(2026, 6, 30), 200),
        ("I", "shares_outstanding", "mrq", D(2026, 6, 30), 44, False, None, D(2026, 8, 20)),
        # cover-page count at 07-25, filed 08-20: the count on its own date, so adjusted
        ("J", "revenue", "ttm", D(2026, 6, 30), 400), ("J", "equity", "mrq", D(2026, 6, 30), 200),
        ("J", "shares_outstanding", "mrq", COVER, 11, False, None, D(2026, 8, 20), None,
         "EntityCommonStockSharesOutstanding"),
        # balance-sheet count at 06-30, filed 07-30, before the split: adjusted from the filing
        ("K", "revenue", "ttm", D(2026, 6, 30), 400), ("K", "equity", "mrq", D(2026, 6, 30), 200),
        ("K", "shares_outstanding", "mrq", D(2026, 6, 30), 11, False, None, D(2026, 7, 30)),
        ("H", "net_income", "ttm", D(2026, 6, 30), 10),
        ("H", "revenue", "ttm", D(2025, 12, 31), 380),
        ("H", "revenue", "fy", D(2025, 12, 31), 380),
    ]  # fmt: skip
    companies = [co("A", "TA"), co("B", "TB"), co("C", "TC"), co("D", "TD"), co("E", "TE"),
                 co("F", "TF"), co("G", None), co("H", "TH"), co("I", "TI"),
                 co("J", "TJ"), co("K", "TK")]  # fmt: skip
    prices = [
        {"ticker": "TA", "close": 50.0, "return_1m": 0.05, "return_12m": -0.2,
         "avg_dollar_volume_3m": 2.5e7, "pct_from_52w_high": -0.1, "volatility_1y": 0.3},
        {"ticker": "TB", "close": 50.0, "as_of": D(2026, 10, 15)},  # 13 days old
        {"ticker": "TC", "close": 50.0, "return_1m": 0.02, "history_days": 40},
        {"ticker": "TD", "close": 20.0},
        {"ticker": "TE", "close": 50.0},
        {"ticker": "TF", "close": 50.0},
        {"ticker": "TI", "close": 20.0},
        {"ticker": "TJ", "close": 20.0},
        {"ticker": "TK", "close": 20.0},
    ]  # fmt: skip
    splits = pl.DataFrame(
        {"ticker": ["TD", "TI", "TJ", "TK"], "execution_date": [D(2026, 8, 10)] * 4,
         "split_from": [1.0] * 4, "split_to": [4.0] * 4}
    )  # fmt: skip
    return run(rows, companies, prices, splits=splits)


def test_price_and_market_cap(out: pl.DataFrame) -> None:
    assert cell(out, "A", "price") == (50.0, None, None)
    assert cell(out, "A", "market_cap") == (550.0, None, None)  # 50 × 11
    assert cell(out, "A", "revenue_ttm") == (400.0, None, None)
    assert cell(out, "A", "avg_dollar_volume_3m")[0] == 2.5e7
    assert cell(out, "A", "return_1m")[0] == 0.05
    assert cell(out, "A", "return_12m")[0] == -0.2
    assert cell(out, "A", "pct_from_52w_high")[0] == -0.1
    assert cell(out, "A", "volatility_1y")[0] == 0.3


def test_split_between_share_date_and_price_date(out: pl.DataFrame) -> None:
    value, code, msg = cell(out, "D", "market_cap")
    assert value == 880.0  # 11 × 4 shares after the 4-for-1, × $20
    assert code == "DERIVED_INPUT"
    assert msg is not None and "× 4.0" in msg and "2026-07-25" in msg


def test_statement_count_filed_after_split_is_not_adjusted_again(out: pl.DataFrame) -> None:
    # SAB Topic 4C: the 06-30 count filed on 08-20 is already on the post-split basis
    assert cell(out, "I", "market_cap") == (880.0, None, None)  # 44 × $20


def test_cover_count_dated_before_split_is_adjusted(out: pl.DataFrame) -> None:
    value, code, msg = cell(out, "J", "market_cap")
    assert value == 880.0  # 11 × 4 × $20
    assert code == "DERIVED_INPUT"
    assert msg is not None and "between the share count (2026-07-25)" in msg


def test_statement_count_filed_before_split_is_adjusted(out: pl.DataFrame) -> None:
    value, code, msg = cell(out, "K", "market_cap")
    assert value == 880.0  # 11 × 4 × $20
    assert code == "DERIVED_INPUT"
    assert msg is not None and "the filing the share count (2026-06-30) is from (2026-07-30)" in msg


def test_diluted_share_fallback_is_derived(out: pl.DataFrame) -> None:
    assert cell(out, "E", "market_cap") == (
        550.0, "DERIVED_INPUT", "uses derived input: shares_outstanding",
    )  # fmt: skip


def test_stale_price_nulls_every_price_cell(out: pl.DataFrame) -> None:
    for mid in ("price", "market_cap"):
        value, code, msg = cell(out, "B", mid)
        assert value is None and code == "STALE_DATA"
        assert msg is not None and "2026-10-15" in msg and "13 days" in msg


def test_short_history(out: pl.DataFrame) -> None:
    assert cell(out, "C", "return_1m")[0] == 0.02
    value, code, msg = cell(out, "C", "return_3m")
    assert value is None and code == "INSUFFICIENT_HISTORY"
    assert msg == "return_3m needs 64 sessions of prices; TC has 40"


def test_stale_share_count(out: pl.DataFrame) -> None:
    value, code, msg = cell(out, "F", "market_cap")
    assert value is None and code == "STALE_DATA"
    assert msg is not None and "2011-04-29" in msg


def test_no_ticker(out: pl.DataFrame) -> None:
    assert cell(out, "G", "market_cap") == (None, "MISSING_INPUT", "close: no listed ticker")
    assert cell(out, "G", "price")[1] == "MISSING_INPUT"


def test_revenue_behind_the_common_ttm_end(out: pl.DataFrame) -> None:
    value, code, msg = cell(out, "H", "revenue_ttm")
    assert value is None and code == "INSUFFICIENT_HISTORY"
    assert msg == "revenue_ttm: no 4 contiguous quarters (or FY + YTD bridge) to 2026-06-30"
