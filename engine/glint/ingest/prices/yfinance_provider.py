"""`YFinanceProvider`: the unofficial Yahoo fallback, used when there is no Massive key.

Yahoo can rate-limit or break at any time, so it stays behind the `PriceProvider` interface,
every failure becomes a `SourceError`, and nothing about a build depends on it succeeding.
The default transport is `yahoo_chart.chart_download` (Yahoo's chart endpoint over plain TLS),
not the yfinance library: yfinance 1.7.0's browser-impersonating TLS is reset by Yahoo (see
`docs/decisions/WT-02.md`). The name stays "yfinance" because that is the settings value.

Yahoo's `Close` and `Volume` are split-adjusted as of the download date. Glint stores unadjusted
bars, so each window is downloaded through today and un-adjusted with the `Stock Splits` column:
raw = adjusted × (product of split ratios after that date); raw volume = adjusted ÷ the same.
"""

import math
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from glint.core.errors import SourceError
from glint.core.log import get_logger, log_event
from glint.ingest.prices.models import Bar, Split
from glint.ingest.prices.provider import market_today
from glint.ingest.prices.symbols import to_yahoo
from glint.ingest.prices.yahoo_chart import chart_download

SOURCE = "yfinance"
BATCH_SIZE = 200
BATCH_PAUSE_S = 2.0
PREFETCH_SLACK_DAYS = 21

Downloader = Callable[[list[str], date, date], Any]
"""(yahoo symbols, start, end exclusive) -> a pandas DataFrame shaped like `yf.download`."""

log = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    f = float(value)
    return None if math.isnan(f) else f


def _times(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def unadjust(rows: list[tuple[date, dict[str, float | None]]]) -> tuple[list[Bar], list[Split]]:
    """Un-adjust one ticker's Yahoo rows (oldest first) whose keys are Yahoo column names.

    Returns bars with the ticker left blank (the caller fills it) and the splits seen.
    """
    splits: list[tuple[date, float]] = [
        (d, r) for d, row in rows if (r := row.get("Stock Splits") or 0.0) > 0
    ]
    bars: list[Bar] = []
    for d, row in rows:
        close = row.get("Close")
        if close is None:
            continue
        factor = math.prod(r for sd, r in splits if sd > d)
        bars.append(
            Bar(
                ticker="",
                date=d,
                open=_times(row.get("Open"), factor),
                high=_times(row.get("High"), factor),
                low=_times(row.get("Low"), factor),
                close=close * factor,
                volume=_times(row.get("Volume"), 1 / factor),
                vwap=None,
            )
        )
    found = [Split("", d, split_from=1.0, split_to=r, adjustment_type=None) for d, r in splits]
    return bars, found


def frame_rows(frame: Any, symbol: str) -> list[tuple[date, dict[str, float | None]]]:
    """One symbol's rows from a `yf.download(group_by="ticker")` frame (multi- or single-index)."""
    columns = frame.columns
    if getattr(columns, "nlevels", 1) > 1:
        if symbol not in set(columns.get_level_values(0)):
            return []
        sub = frame[symbol]
    else:
        sub = frame
    names = [str(c) for c in sub.columns]
    out: list[tuple[date, dict[str, float | None]]] = []
    for idx, values in zip(sub.index, sub.itertuples(index=False, name=None), strict=True):
        row = {n: _num(v) for n, v in zip(names, values, strict=True)}
        if row.get("Close") is None:
            continue
        out.append((idx.date() if hasattr(idx, "date") else idx, row))
    return out


class YFinanceProvider:
    name = SOURCE

    def __init__(
        self,
        tickers: Sequence[str],
        *,
        is_fallback: bool = True,
        download: Downloader = chart_download,
        batch_size: int = BATCH_SIZE,
        pause_s: float = BATCH_PAUSE_S,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.tickers = sorted(set(tickers))
        self.is_fallback = is_fallback
        self._download = download
        self._batch_size = batch_size
        self._pause_s = pause_s
        self._sleep = sleep
        self._now = now
        self._window_start: date | None = None
        self._bars: dict[date, list[Bar]] = {}
        self._splits: list[Split] = []
        self.downloads = 0
        if is_fallback:
            log.warning(
                "price_provider_fallback",
                extra={
                    "provider": SOURCE,
                    "reason": "MASSIVE_API_KEY not set",
                    "tickers": len(self.tickers),
                },
            )

    # --- PriceProvider ---------------------------------------------------------------------

    def prefetch(self, days: Sequence[date]) -> None:
        # Slack, so a backfill that walks past a few holidays stays inside one download.
        if days:
            self._load_window(min(days) - timedelta(days=PREFETCH_SLACK_DAYS))

    def bars_for_date(self, day: date) -> list[Bar]:
        self._refuse_today(day)
        if self._window_start is None or day < self._window_start:
            self._load_window(day)
        return list(self._bars.get(day, []))

    def history(self, ticker: str, start: date, end: date) -> list[Bar]:
        frame = self._fetch([to_yahoo(ticker)], start)
        bars, _ = unadjust(frame_rows(frame, to_yahoo(ticker)))
        return [_with_ticker(b, ticker) for b in bars if start <= b.date <= end]

    def splits(self, since: date) -> list[Split]:
        # A loaded window runs through today, so it holds every split that can still affect
        # its bars; splits before it were merged by the runs that stored those older bars.
        # Only download (the whole universe) when nothing is loaded yet.
        if self._window_start is None:
            self._load_window(since)
        return [s for s in self._splits if s.execution_date >= since]

    # --- internals -------------------------------------------------------------------------

    def _refuse_today(self, day: date) -> None:
        today = market_today(self._now())
        if day >= today:
            raise SourceError(
                SOURCE,
                f"refusing to request {day}: end-of-day data only, newest allowed is "
                f"{today - timedelta(days=1)} (New York)",
            )

    def _fetch(self, symbols: list[str], start: date) -> Any:
        # Always through today: Yahoo adjusts history for every split up to the download date.
        end = market_today(self._now())
        try:
            frame = self._download(symbols, start, end)
        except Exception as exc:  # yfinance raises anything; contain it here
            raise SourceError(SOURCE, f"download failed: {exc}") from exc
        self.downloads += 1
        return frame

    def _load_window(self, start: date) -> None:
        if not self.tickers:
            raise SourceError(SOURCE, "no tickers to download (yfinance needs a ticker list)")
        by_day: dict[date, list[Bar]] = {}
        splits: list[Split] = []
        batches = [
            self.tickers[i : i + self._batch_size]
            for i in range(0, len(self.tickers), self._batch_size)
        ]
        for n, batch in enumerate(batches):
            if n:
                self._sleep(self._pause_s)
            frame = self._fetch([to_yahoo(t) for t in batch], start)
            for ticker in batch:
                bars, found = unadjust(frame_rows(frame, to_yahoo(ticker)))
                for b in bars:
                    if b.date >= start:
                        by_day.setdefault(b.date, []).append(_with_ticker(b, ticker))
                splits += [_split_with_ticker(s, ticker) for s in found]
            log_event(log, "yfinance_batch", batch=n + 1, of=len(batches), tickers=len(batch))
        if not by_day:
            raise SourceError(
                SOURCE,
                f"no bars for any of {len(self.tickers)} tickers in the window {start} → today "
                f"(the requested dates plus {PREFETCH_SLACK_DAYS} days of slack): "
                "Yahoo down or blocking us?",
            )
        for day_bars in by_day.values():
            day_bars.sort(key=lambda b: b.ticker)
        self._bars = by_day
        self._splits = sorted(splits, key=lambda s: (s.execution_date, s.ticker))
        self._window_start = start


def _with_ticker(b: Bar, ticker: str) -> Bar:
    return Bar(ticker, b.date, b.open, b.high, b.low, b.close, b.volume, b.vwap)


def _split_with_ticker(s: Split, ticker: str) -> Split:
    return Split(ticker, s.execution_date, s.split_from, s.split_to, s.adjustment_type)
