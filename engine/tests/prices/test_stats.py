"""Price stats against hand-computed values (exact to 1e-9)."""

import math
import statistics
from datetime import date, timedelta

import polars as pl
import pytest

from glint.ingest.prices.models import Split
from glint.ingest.prices.splits import SplitIndex, adjust_for_splits, split_between
from glint.ingest.prices.stats import Windows, price_stats
from glint.ingest.prices.store import SPLITS_SCHEMA, bars_frame, splits_frame
from tests.prices.helpers import bar

TOL = 1e-9
D0 = date(2026, 1, 5)
TINY = Windows(m1=1, m3=2, m6=3, m12=4, high=4, vol=4, adv=2, annualize=252)


def _days(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def _bars(series: dict[str, list[tuple[float, float]]]) -> pl.DataFrame:
    """{ticker: [(close, volume), ...]} on consecutive days from D0."""
    return bars_frame(
        bar(t, d, c, v)
        for t, rows in series.items()
        for d, (c, v) in zip(_days(len(rows)), rows, strict=True)
    )


def _no_splits() -> pl.DataFrame:
    return pl.DataFrame(schema=SPLITS_SCHEMA)


def _stats(bars: pl.DataFrame, splits: pl.DataFrame | None = None, w: Windows = TINY):
    as_of = bars["date"].max()
    assert isinstance(as_of, date)
    adj = adjust_for_splits(bars, _no_splits() if splits is None else splits, as_of)
    return price_stats(adj, as_of, w)


def _row(df: pl.DataFrame, ticker: str) -> dict[str, object]:
    return df.filter(pl.col("ticker") == ticker).row(0, named=True)


ABC = [(10.0, 100.0), (11.0, 200.0), (9.0, 300.0), (12.0, 400.0), (15.0, 500.0)]


def test_every_stat_on_a_hand_computed_series() -> None:
    r = _row(_stats(_bars({"ABC": ABC})).stats, "ABC")
    assert r["as_of"] == D0 + timedelta(days=4)
    assert r["history_days"] == 5
    assert r["close"] == 15.0
    assert r["return_1m"] == pytest.approx(15 / 12 - 1, abs=TOL)  # 0.25
    assert r["return_3m"] == pytest.approx(15 / 9 - 1, abs=TOL)  # 0.666…
    assert r["return_6m"] == pytest.approx(15 / 11 - 1, abs=TOL)  # 0.3636…
    assert r["return_12m"] == pytest.approx(15 / 10 - 1, abs=TOL)  # 0.5
    assert r["momentum_12_1"] == pytest.approx(12 / 10 - 1, abs=TOL)  # t−1 vs t−4
    assert r["high_52w"] == 15.0
    assert r["pct_from_52w_high"] == pytest.approx(0.0, abs=TOL)
    log_returns = [math.log(11 / 10), math.log(9 / 11), math.log(12 / 9), math.log(15 / 12)]
    assert r["volatility_1y"] == pytest.approx(
        statistics.stdev(log_returns) * math.sqrt(252), abs=TOL
    )
    assert r["avg_dollar_volume_3m"] == pytest.approx((12 * 400 + 15 * 500) / 2, abs=TOL)


def test_off_the_high() -> None:
    bars = _bars({"DIP": [(10.0, 1.0), (20.0, 1.0), (15.0, 1.0), (12.0, 1.0)]})
    r = _row(_stats(bars).stats, "DIP")
    assert r["high_52w"] == 20.0
    assert r["pct_from_52w_high"] == pytest.approx(12 / 20 - 1, abs=TOL)  # −0.4


def test_insufficient_history_is_null_with_a_reason() -> None:
    out = _stats(_bars({"NEW": [(5.0, 100.0), (6.0, 200.0)], "ABC": ABC}))
    r = _row(out.stats, "NEW")
    assert r["return_1m"] == pytest.approx(0.2, abs=TOL)
    assert r["avg_dollar_volume_3m"] == pytest.approx((500 + 1200) / 2, abs=TOL)
    for stat in ("return_3m", "return_6m", "return_12m", "momentum_12_1", "high_52w"):
        assert r[stat] is None
    notes = out.notes.filter(pl.col("ticker") == "NEW")
    assert set(notes["stat"]) == {
        "return_3m",
        "return_6m",
        "return_12m",
        "momentum_12_1",
        "high_52w",
        "pct_from_52w_high",
        "volatility_1y",
    }
    assert set(notes["code"]) == {"INSUFFICIENT_HISTORY"}
    msg = notes.filter(pl.col("stat") == "return_12m")["message"][0]
    assert msg == "return_12m needs 5 sessions of prices; has 2"
    assert out.notes.filter(pl.col("ticker") == "ABC").height == 0


def test_every_null_has_a_note() -> None:
    out = _stats(_bars({"NEW": [(5.0, 1.0)], "ABC": ABC}))
    nulls = {
        (row["ticker"], col)
        for row in out.stats.iter_rows(named=True)
        for col, v in row.items()
        if v is None
    }
    noted = set(out.notes.select("ticker", "stat").iter_rows())
    assert nulls == noted


def test_returns_use_split_adjusted_closes() -> None:
    # 10-for-1 effective on day 3: raw closes fall 1200 → 120 but the holder lost nothing
    bars = _bars({"NV": [(1000.0, 10.0), (1200.0, 10.0), (120.0, 100.0), (125.0, 100.0)]})
    split = splits_frame([Split("NV", D0 + timedelta(days=2), 1, 10)])
    r = _row(_stats(bars, split).stats, "NV")
    assert r["close"] == 125.0  # unadjusted: what traded on as_of (market cap uses this)
    assert r["return_1m"] == pytest.approx(125 / 120 - 1, abs=TOL)
    assert r["return_3m"] == pytest.approx(125 / 120 - 1, abs=TOL)  # vs 1200 / 10
    assert r["high_52w"] == pytest.approx(125.0, abs=TOL)
    # dollar volume is split-invariant: raw close × raw volume
    assert r["avg_dollar_volume_3m"] == pytest.approx((120 * 100 + 125 * 100) / 2, abs=TOL)


def test_future_split_is_ignored() -> None:
    bars = _bars({"X": [(10.0, 1.0), (11.0, 1.0)]})
    adj = adjust_for_splits(
        bars, splits_frame([Split("X", D0 + timedelta(days=30), 1, 2)]), D0 + timedelta(days=1)
    )
    assert adj["adj_close"].to_list() == [10.0, 11.0]


def test_rows_after_as_of_are_ignored() -> None:
    bars = _bars({"ABC": ABC})
    adj = adjust_for_splits(bars, _no_splits(), D0 + timedelta(days=4))
    r = _row(price_stats(adj, D0 + timedelta(days=3), TINY).stats, "ABC")
    assert r["close"] == 12.0
    assert r["history_days"] == 4


def test_default_windows_on_a_geometric_series() -> None:
    # c_t = 100 × 1.001^t for 300 sessions: every return has a closed form, volatility is 0
    rows = [(100 * 1.001**t, 1_000.0) for t in range(300)]
    r = _row(_stats(_bars({"G": rows}), w=Windows()).stats, "G")
    assert r["history_days"] == 300
    assert r["return_1m"] == pytest.approx(1.001**21 - 1, abs=TOL)
    assert r["return_3m"] == pytest.approx(1.001**63 - 1, abs=TOL)
    assert r["return_6m"] == pytest.approx(1.001**126 - 1, abs=TOL)
    assert r["return_12m"] == pytest.approx(1.001**252 - 1, abs=TOL)
    assert r["momentum_12_1"] == pytest.approx(1.001**231 - 1, abs=TOL)
    assert r["pct_from_52w_high"] == pytest.approx(0.0, abs=TOL)
    assert r["volatility_1y"] == pytest.approx(0.0, abs=TOL)
    expected_adv = sum(100 * 1.001**t * 1_000 for t in range(237, 300)) / 63
    assert r["avg_dollar_volume_3m"] == pytest.approx(expected_adv, abs=1e-6)


def test_default_windows_need_253_rows_for_12m() -> None:
    rows = [(100.0 + t, 1.0) for t in range(252)]
    r = _row(_stats(_bars({"S": rows}), w=Windows()).stats, "S")
    assert r["return_12m"] is None
    assert r["high_52w"] == 351.0  # 252 rows is enough for the 52-week high
    assert r["volatility_1y"] is None


# --- split_between -----------------------------------------------------------------------

SPLITS = splits_frame(
    [
        Split("AAPL", date(2020, 8, 31), 1, 4),
        Split("NVDA", date(2021, 7, 20), 1, 4),
        Split("NVDA", date(2024, 6, 10), 1, 10),
        Split("REV", date(2024, 3, 1), 10, 1),
    ]
)


@pytest.mark.parametrize(
    ("ticker", "d1", "d2", "expected"),
    [
        ("AAPL", date(2020, 6, 27), date(2020, 9, 30), 4.0),
        ("AAPL", date(2020, 9, 26), date(2026, 10, 27), None),
        ("AAPL", date(2020, 8, 31), date(2020, 9, 30), None),  # effective on d1: already counted
        ("AAPL", date(2020, 8, 30), date(2020, 8, 31), 4.0),  # effective on d2: counts
        ("NVDA", date(2021, 1, 31), date(2024, 7, 1), 40.0),
        ("NVDA", date(2024, 4, 28), date(2024, 6, 9), None),
        ("REV", date(2024, 1, 1), date(2024, 4, 1), 0.1),
        ("NONE", date(2020, 1, 1), date(2026, 1, 1), None),
        ("AAPL", date(2020, 9, 30), date(2020, 6, 27), None),  # reversed range
    ],
)
def test_split_between(ticker: str, d1: date, d2: date, expected: float | None) -> None:
    got = SplitIndex(SPLITS).split_between(ticker, d1, d2)
    assert got == (None if expected is None else pytest.approx(expected, abs=TOL))
    assert split_between(SPLITS, ticker, d1, d2) == got
