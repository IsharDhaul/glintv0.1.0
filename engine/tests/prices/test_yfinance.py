import logging
from datetime import date
from typing import Any

import pandas as pd
import pytest

from glint.core.errors import SourceError
from glint.ingest.prices.yfinance_provider import YFinanceProvider
from tests.prices.helpers import FakeClock, fixed_now

TODAY = date(2024, 6, 13)
FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]


def _frame(per_symbol: dict[str, list[tuple[str, float, float, float]]]) -> Any:
    """{yahoo symbol: [(date, adjusted close, adjusted volume, split ratio), ...]} → yf frame."""
    dates = sorted({d for rows in per_symbol.values() for d, *_ in rows})
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    cols = pd.MultiIndex.from_product([list(per_symbol), FIELDS])
    frame = pd.DataFrame(index=index, columns=cols, dtype=float)
    for sym, rows in per_symbol.items():
        for d, close, vol, split in rows:
            ts = pd.Timestamp(d)
            for f in ("Open", "High", "Low", "Close", "Adj Close"):
                frame.loc[ts, (sym, f)] = close
            frame.loc[ts, (sym, "Volume")] = vol
            frame.loc[ts, (sym, "Dividends")] = 0.0
            frame.loc[ts, (sym, "Stock Splits")] = split
    return frame


# NVDA 10-for-1, effective 2024-06-10. Yahoo shows pre-split days divided by 10.
NVDA = [
    ("2024-06-06", 120.998, 4_000_000.0, 0.0),
    ("2024-06-07", 120.888, 3_500_000.0, 0.0),
    ("2024-06-10", 121.790, 3_000_000.0, 10.0),
    ("2024-06-11", 120.910, 2_000_000.0, 0.0),
]
BRK = [
    ("2024-06-06", 410.0, 3_000.0, 0.0),
    ("2024-06-07", 412.0, 3_100.0, 0.0),
    ("2024-06-10", 411.0, 3_200.0, 0.0),
    ("2024-06-11", 409.0, 3_300.0, 0.0),
]


class FakeDownload:
    def __init__(self, frame: Any) -> None:
        self.frame = frame
        self.calls: list[tuple[list[str], date, date]] = []

    def __call__(self, symbols: list[str], start: date, end: date) -> Any:
        self.calls.append((symbols, start, end))
        return self.frame


def _provider(dl: FakeDownload, **kw: Any) -> YFinanceProvider:
    clock = FakeClock()
    return YFinanceProvider(
        kw.pop("tickers", ["NVDA", "BRK.B"]),
        download=dl,
        sleep=clock.sleep,
        now=lambda: fixed_now(TODAY),
        **kw,
    )


def test_unadjusts_across_a_split_and_maps_symbols() -> None:
    dl = FakeDownload(_frame({"NVDA": NVDA, "BRK-B": BRK}))
    p = _provider(dl)
    before = {b.ticker: b for b in p.bars_for_date(date(2024, 6, 7))}
    after = {b.ticker: b for b in p.bars_for_date(date(2024, 6, 10))}
    assert set(before) == {"BRK.B", "NVDA"}  # Yahoo BRK-B → canonical BRK.B
    assert before["NVDA"].close == pytest.approx(1208.88, abs=1e-9)  # as traded that day
    assert before["NVDA"].volume == pytest.approx(350_000.0, abs=1e-9)
    assert after["NVDA"].close == pytest.approx(121.79, abs=1e-9)
    assert before["BRK.B"].close == 412.0
    # one batched download for the whole window, through today (so every split is applied)
    assert len(dl.calls) == 1
    symbols, start, end = dl.calls[0]
    assert symbols == ["BRK-B", "NVDA"]
    assert (start, end) == (date(2024, 6, 7), TODAY)


def test_splits_come_from_the_actions_column() -> None:
    p = _provider(FakeDownload(_frame({"NVDA": NVDA, "BRK-B": BRK})))
    splits = p.splits(date(2024, 6, 1))
    assert [(s.ticker, s.execution_date, s.ratio) for s in splits] == [
        ("NVDA", date(2024, 6, 10), 10.0)
    ]


def test_prefetch_downloads_once_for_many_days() -> None:
    dl = FakeDownload(_frame({"NVDA": NVDA, "BRK-B": BRK}))
    p = _provider(dl)
    days = [date(2024, 6, 6), date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 11)]
    p.prefetch(days)
    for d in days:
        assert len(p.bars_for_date(d)) == 2
    assert len(dl.calls) == 1


def test_batches_of_two_with_pauses() -> None:
    dl = FakeDownload(_frame({"NVDA": NVDA, "BRK-B": BRK}))
    clock = FakeClock()
    p = YFinanceProvider(
        ["NVDA", "BRK.B", "A", "B", "C"],
        download=dl,
        batch_size=2,
        pause_s=1.5,
        sleep=clock.sleep,
        now=lambda: fixed_now(TODAY),
    )
    p.bars_for_date(date(2024, 6, 11))
    assert [c[0] for c in dl.calls] == [["A", "B"], ["BRK-B", "C"], ["NVDA"]]
    assert clock.sleeps == [1.5, 1.5]


def test_day_without_any_rows_is_empty() -> None:
    p = _provider(FakeDownload(_frame({"NVDA": NVDA, "BRK-B": BRK})))
    p.prefetch([date(2024, 6, 6)])
    assert p.bars_for_date(date(2024, 6, 8)) == []  # Saturday, inside the window


def test_everything_failed_is_a_source_error() -> None:
    empty = pd.DataFrame(columns=pd.MultiIndex.from_product([["NVDA"], FIELDS]))
    p = _provider(FakeDownload(empty))
    with pytest.raises(SourceError, match="no bars for any of 2 tickers in the window"):
        p.bars_for_date(date(2024, 6, 10))


def test_downloader_exception_is_contained() -> None:
    def boom(symbols: list[str], start: date, end: date) -> Any:
        raise RuntimeError("rate limited")

    p = YFinanceProvider(["NVDA"], download=boom, now=lambda: fixed_now(TODAY))
    with pytest.raises(SourceError, match="rate limited"):
        p.bars_for_date(date(2024, 6, 10))


def test_never_today() -> None:
    p = _provider(FakeDownload(_frame({"NVDA": NVDA})))
    with pytest.raises(SourceError, match="end-of-day"):
        p.bars_for_date(TODAY)


def test_history_one_ticker() -> None:
    dl = FakeDownload(_frame({"NVDA": NVDA}))
    p = _provider(dl)
    bars = p.history("NVDA", date(2024, 6, 7), date(2024, 6, 10))
    assert [(b.date, round(b.close, 6)) for b in bars] == [
        (date(2024, 6, 7), 1208.88),
        (date(2024, 6, 10), 121.79),
    ]


def test_says_it_is_in_fallback_mode(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging.getLogger("glint"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="glint"):
        _provider(FakeDownload(_frame({"NVDA": NVDA})))
    assert "price_provider_fallback" in caplog.text
