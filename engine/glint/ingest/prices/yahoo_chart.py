"""Yahoo's chart endpoint over plain TLS: the transport behind the yfinance fallback.

yfinance 1.7.0 sends every request through curl_cffi with a browser TLS impersonation, and those
handshakes are reset (checked 2026-10-29 from two networks: impersonate=chrome/safari/firefox all
fail, while plain TLS to the same URL returns 200). This module asks the same endpoint directly
and returns a frame shaped like `yf.download(group_by="ticker", actions=True)`, so the provider's
un-adjusting logic is unchanged.

`GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1&period2&interval=1d
&events=split` → `chart.result[0]`: `timestamp[]`, `indicators.quote[0].{open,high,low,close,
volume}` (split-adjusted as of today, like yfinance's `Close`), `events.splits{…numerator,
denominator}`.
"""

import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from datetime import time as dtime
from typing import Any

import httpx
import pandas as pd

from glint.core.log import get_logger, log_event
from glint.ingest.prices.provider import MARKET_TZ

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Glint"
PER_SYMBOL_PAUSE_S = 0.25
FIELDS = ["Open", "High", "Low", "Close", "Volume", "Stock Splits"]

log = get_logger(__name__)


def _epoch(day: date) -> int:
    return int(datetime.combine(day, dtime(0, 0), tzinfo=UTC).timestamp())


def parse_chart(doc: dict[str, Any]) -> dict[date, dict[str, float | None]]:
    """One symbol's chart response → {trading date: {Yahoo column: value}}."""
    chart: dict[str, Any] = doc.get("chart") or {}
    results: list[dict[str, Any]] = chart.get("result") or []
    if not results:
        return {}
    res = results[0]
    stamps: list[int] = res.get("timestamp") or []
    indicators: dict[str, Any] = res.get("indicators") or {}
    quotes: list[dict[str, list[float | None]]] = indicators.get("quote") or [{}]
    blank: list[float | None] = [None] * len(stamps)
    columns = {
        name: quotes[0].get(key) or blank
        for name, key in (
            ("Open", "open"),
            ("High", "high"),
            ("Low", "low"),
            ("Close", "close"),
            ("Volume", "volume"),
        )
    }
    rows: dict[date, dict[str, float | None]] = {}
    for i, ts in enumerate(stamps):
        day = datetime.fromtimestamp(ts, tz=UTC).astimezone(MARKET_TZ).date()
        rows[day] = {name: col[i] for name, col in columns.items()} | {"Stock Splits": 0.0}
    events: dict[str, Any] = res.get("events") or {}
    splits: dict[str, dict[str, Any]] = events.get("splits") or {}
    for split in splits.values():
        day = datetime.fromtimestamp(int(split["date"]), tz=UTC).astimezone(MARKET_TZ).date()
        if day in rows and split.get("denominator"):
            rows[day]["Stock Splits"] = float(split["numerator"]) / float(split["denominator"])
    return rows


def to_frame(per_symbol: dict[str, dict[date, dict[str, float | None]]]) -> Any:
    """Build the `yf.download(group_by="ticker")` shape: MultiIndex columns (symbol, field)."""
    days = sorted({d for rows in per_symbol.values() for d in rows})
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    cols = pd.MultiIndex.from_product([list(per_symbol), FIELDS])
    data = [[per_symbol[s].get(d, {}).get(f) for s in per_symbol for f in FIELDS] for d in days]
    return pd.DataFrame(data, index=index, columns=cols, dtype=float)


def chart_download(
    symbols: list[str],
    start: date,
    end: date,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Download `start..end` (end exclusive) for Yahoo symbols; failures leave a symbol empty."""
    own = client is None
    http = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0)
    params = {
        "period1": str(_epoch(start)),
        "period2": str(_epoch(end)),
        "interval": "1d",
        "events": "split",
    }
    per_symbol: dict[str, dict[date, dict[str, float | None]]] = {}
    failed = 0
    try:
        for n, symbol in enumerate(symbols):
            if n:
                sleep(PER_SYMBOL_PAUSE_S)
            try:
                resp = http.get(CHART_URL.format(symbol=symbol), params=params)
                rows = parse_chart(resp.json()) if resp.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                rows = {}
            failed += not rows
            per_symbol[symbol] = rows
    finally:
        if own:
            http.close()
    if failed:
        log_event(log, "yahoo_chart_symbols_empty", failed=failed, of=len(symbols))
    return to_frame(per_symbol)
