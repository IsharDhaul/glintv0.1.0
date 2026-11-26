"""Raw price storage in `GLINT_RAW_DIR/prices/` (shared by every worktree).

    prices/daily/date=YYYY-MM-DD/part.parquet   one grouped-daily date, unadjusted bars
    prices/daily/date=YYYY-MM-DD/source.json    who wrote it (massive | yfinance) + rows
    prices/splits.parquet                       every split seen, deduplicated
    prices/holidays.json                        weekdays confirmed closed (never refetched)
    prices/reports/                             coverage / unmatched-symbol reports

Files keep the symbol that traded that day. Reads (`read_bars`, `load_splits`) follow ticker
changes in `config/ticker_changes.yaml`, so a renamed company's history arrives under its current
symbol (see `ticker_changes`).

Writes happen only inside `with store.writer():`, which holds `raw.lock`. Every file is written to
a temp name and renamed into place, so a killed process leaves either the old file or the new
one, never half of one; that is what makes the backfill safe to kill and restart.
"""

import os
import re
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import orjson
import polars as pl

from glint.contracts.db import PRICES_DAILY_COLUMNS
from glint.core.errors import GlintError
from glint.core.filelock import raw_lock
from glint.core.paths import Paths
from glint.ingest.prices.models import Bar, Split
from glint.ingest.prices.ticker_changes import (
    TickerChange,
    effective_changes,
    follow_changes,
    load_ticker_changes,
    related_symbols,
)

_DUCK_TO_POLARS: dict[str, Any] = {"VARCHAR": pl.String, "DATE": pl.Date, "DOUBLE": pl.Float64}
BARS_SCHEMA: dict[str, Any] = {c: _DUCK_TO_POLARS[t] for c, t in PRICES_DAILY_COLUMNS.items()}
SPLITS_SCHEMA: dict[str, Any] = {
    "ticker": pl.String,
    "execution_date": pl.Date,
    "split_from": pl.Float64,
    "split_to": pl.Float64,
    "adjustment_type": pl.String,
}
_PARTITION_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")


class NotLockedError(GlintError):
    code = "RAW_NOT_LOCKED"


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    _fsync(tmp)
    tmp.replace(path)


def _atomic_write_parquet(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.write_parquet(tmp)
    _fsync(tmp)
    tmp.replace(path)


def bars_frame(bars: Iterable[Bar]) -> pl.DataFrame:
    rows = [
        {
            "ticker": b.ticker,
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "vwap": b.vwap,
        }
        for b in bars
    ]
    return pl.DataFrame(rows, schema=BARS_SCHEMA, orient="row")


def _ratio_key() -> pl.Expr:
    return (pl.col("split_to") / pl.col("split_from")).log10().round(4)


def net_same_day(splits: pl.DataFrame) -> pl.DataFrame:
    """One row per ticker and execution date: the legs' `split_from`s and `split_to`s multiplied
    (so the ratio is the product of the legs' ratios) and their distinct `adjustment_type`s
    joined with "+". An odd-lot pair nets to a ratio of 1 (TTSH 2025-12-16: from 3,000, to 3,000,
    "forward_split+reverse_split"), so nothing is adjusted."""
    if splits.is_empty():
        return splits
    return (
        splits.group_by("ticker", "execution_date", maintain_order=True)
        .agg(
            pl.col("split_from").product(),
            pl.col("split_to").product(),
            pl.col("adjustment_type").drop_nulls().unique().sort().str.join("+"),
        )
        .with_columns(
            pl.when(pl.col("adjustment_type") == "").then(None).otherwise(pl.col("adjustment_type"))
            .alias("adjustment_type")
        )
        .select(list(SPLITS_SCHEMA))
        .sort(["execution_date", "ticker"])
    )  # fmt: skip


def splits_frame(splits: Iterable[Split]) -> pl.DataFrame:
    rows = [
        {
            "ticker": s.ticker,
            "execution_date": s.execution_date,
            "split_from": s.split_from,
            "split_to": s.split_to,
            "adjustment_type": s.adjustment_type,
        }
        for s in splits
    ]
    return pl.DataFrame(rows, schema=SPLITS_SCHEMA, orient="row")


class PriceStore:
    def __init__(self, paths: Paths, ticker_changes: list[TickerChange] | None = None) -> None:
        self.paths = paths
        self.ticker_changes = (
            load_ticker_changes()
            if ticker_changes is None
            else sorted(ticker_changes, key=lambda c: c.effective)
        )
        self.root = paths.prices_raw
        self.daily_dir = self.root / "daily"
        self.splits_path = self.root / "splits.parquet"
        self.holidays_path = self.root / "holidays.json"
        self.reports_dir = self.root / "reports"
        self._locked = False

    # --- writing (under raw.lock) ----------------------------------------------------------

    @contextmanager
    def writer(self, *, timeout_s: float = 0) -> Generator["PriceStore"]:
        with raw_lock(self.paths.raw_dir, timeout_s=timeout_s):
            self._locked = True
            try:
                yield self
            finally:
                self._locked = False

    def _require_lock(self) -> None:
        if not self._locked:
            raise NotLockedError("price writes must happen inside `with store.writer():`")

    def partition_path(self, day: date) -> Path:
        return self.daily_dir / f"date={day.isoformat()}" / "part.parquet"

    def source_path(self, day: date) -> Path:
        return self.partition_path(day).with_name("source.json")

    def partition_source(self, day: date) -> str | None:
        """Who wrote the partition; None if unknown (no sidecar, e.g. killed before it)."""
        path = self.source_path(day)
        if not path.exists():
            return None
        return orjson.loads(path.read_bytes()).get("source")

    def write_day(self, day: date, bars: list[Bar], *, source: str) -> int:
        """Write one date's bars, replacing any earlier file for that date. Returns rows."""
        self._require_lock()
        if not bars:
            raise ValueError(f"no bars for {day}; record a holiday instead")
        wrong = {b.date for b in bars if b.date != day}
        if wrong:
            raise ValueError(f"bars for {sorted(wrong)} passed as {day}")
        frame = bars_frame(bars).unique(subset="ticker", keep="first").sort("ticker")
        # bars first, sidecar second: a kill in between leaves source unknown → refetched
        self.source_path(day).unlink(missing_ok=True)
        _atomic_write_parquet(self.partition_path(day), frame)
        _atomic_write_bytes(
            self.source_path(day), orjson.dumps({"source": source, "rows": frame.height})
        )
        return frame.height

    def add_holiday(self, day: date, *, source: str) -> None:
        self._require_lock()
        entries = self._holiday_entries()
        if any(e["date"] == day.isoformat() for e in entries):
            return
        entries.append(
            {
                "date": day.isoformat(),
                "source": source,
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )
        entries.sort(key=lambda e: e["date"])
        _atomic_write_bytes(
            self.holidays_path, orjson.dumps({"holidays": entries}, option=orjson.OPT_INDENT_2)
        )

    def merge_splits(self, splits: Iterable[Split]) -> int:
        """Add splits not seen before. Returns how many were new.

        Key: ticker, execution date and ratio (log10, 4 decimals, so the same event from two
        providers with rounding differences is one row). Ticker + date alone isn't a key: an
        odd-lot transaction is a reverse and a forward split on the same day (TTSH 2025-12-16:
        3,000 → 1 then 1 → 3,000), and keeping one leg left a phantom 3,000-for-1 split.
        `load_splits` nets same-day legs."""
        self._require_lock()
        old = self._raw_splits()
        new = splits_frame(splits)
        merged = (
            pl.concat([old, new])
            .with_columns(_ratio_key().alias("_key"))
            .unique(subset=["ticker", "execution_date", "_key"], keep="first", maintain_order=True)
            .drop("_key")
            .sort(["execution_date", "ticker", "split_from", "split_to"])
        )
        _atomic_write_parquet(self.splits_path, merged)
        return merged.height - old.height

    def write_report(self, name: str, doc: dict[str, Any]) -> Path:
        self._require_lock()
        path = self.reports_dir / name
        _atomic_write_bytes(path, orjson.dumps(doc, option=orjson.OPT_INDENT_2))
        return path

    # --- reading (no lock needed: files are only ever replaced atomically) -----------------

    def dates_on_disk(self, *, sources: Iterable[str] | None = None) -> list[date]:
        """Dates with bars; with `sources`, only partitions written by one of them."""
        if not self.daily_dir.exists():
            return []
        wanted = None if sources is None else set(sources)
        out: list[date] = []
        for d in self.daily_dir.iterdir():
            m = _PARTITION_RE.match(d.name)
            if m and (d / "part.parquet").exists():
                day = date.fromisoformat(m.group(1))
                if wanted is None or self.partition_source(day) in wanted:
                    out.append(day)
        return sorted(out)

    def latest_date(self) -> date | None:
        dates = self.dates_on_disk()
        return dates[-1] if dates else None

    def _holiday_entries(self) -> list[dict[str, str]]:
        if not self.holidays_path.exists():
            return []
        return orjson.loads(self.holidays_path.read_bytes())["holidays"]

    def holidays(self) -> set[date]:
        return {date.fromisoformat(e["date"]) for e in self._holiday_entries()}

    def _raw_splits(self) -> pl.DataFrame:
        if not self.splits_path.exists():
            return pl.DataFrame(schema=SPLITS_SCHEMA)
        return pl.read_parquet(self.splits_path)

    def active_changes(self) -> list[TickerChange]:
        """Ticker changes already effective in the data (newest date on disk)."""
        return effective_changes(self.ticker_changes, self.latest_date())

    def load_splits(self) -> pl.DataFrame:
        """Every split, under the symbol the company trades as now, one row per ticker and day:
        same-day legs are netted (`net_same_day`)."""
        return net_same_day(
            follow_changes(self._raw_splits(), self.active_changes(), "execution_date")
        )

    def scan_bars(self) -> pl.LazyFrame:
        files = [self.partition_path(d) for d in self.dates_on_disk()]
        if not files:
            return pl.LazyFrame(schema=BARS_SCHEMA)
        return pl.scan_parquet(files, hive_partitioning=False)

    def read_bars(
        self,
        tickers: Iterable[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> pl.DataFrame:
        """Unadjusted bars under the current symbol (ticker changes followed), sorted by ticker
        then date. Asking for a new symbol returns the old symbol's earlier bars too."""
        changes = self.active_changes()
        lf = self.scan_bars()
        wanted = None if tickers is None else set(tickers)
        if wanted is not None:
            lf = lf.filter(pl.col("ticker").is_in(sorted(related_symbols(wanted, changes))))
        if start is not None:
            lf = lf.filter(pl.col("date") >= start)
        if end is not None:
            lf = lf.filter(pl.col("date") <= end)
        bars = follow_changes(lf.collect(), changes)
        if wanted is not None:
            bars = bars.filter(pl.col("ticker").is_in(sorted(wanted)))
        return bars.sort(["ticker", "date"])
