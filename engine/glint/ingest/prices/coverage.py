"""How much of the listed universe has a price, and which symbols don't line up.

The universe here is SEC's `company_tickers_exchange.json` for NYSE / Nasdaq / NYSE American, read
from the newest `GLINT_RAW_DIR/sec/<date>/` folder that WT-01's downloader writes. Symbols are
compared in canonical form (`BRK.B`).

Coverage is measured on **common-stock listings** (what the screen ranks). Warrants, units,
rights and preferreds are counted separately rather than hidden. It is reported twice:
- on the latest date: a grouped-daily file only lists tickers that *traded* that day, so a thin
  stock with no trades is absent even though it is listed and priced the day before;
- within the last `RECENT_SESSIONS` sessions, which is what "has a usable price" means in practice.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import polars as pl

from glint.core.paths import Paths
from glint.fixtures.sec import LISTED_EXCHANGES, parse_tickers_exchange
from glint.ingest.prices.symbols import canonical_from_sec, is_common_listing

TICKERS_FILE = "company_tickers_exchange.json"
TOP_EXTRA = 50
RECENT_SESSIONS = 5
_DATED_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class UniverseTicker:
    ticker: str
    exchange: str

    @property
    def is_common(self) -> bool:
        return is_common_listing(self.ticker, self.exchange)


def universe_from_tickers_doc(doc: dict[str, Any]) -> list[UniverseTicker]:
    seen: dict[str, UniverseTicker] = {}
    for row in parse_tickers_exchange(doc):
        if row.exchange in LISTED_EXCHANGES:
            t = canonical_from_sec(row.ticker)
            seen.setdefault(t, UniverseTicker(t, row.exchange))
    return sorted(seen.values(), key=lambda u: u.ticker)


def find_tickers_file(paths: Paths) -> Path | None:
    sec = paths.sec_raw
    if not sec.exists():
        return None
    dated = sorted((d for d in sec.iterdir() if _DATED_DIR.match(d.name)), reverse=True)
    return next((d / TICKERS_FILE for d in dated if (d / TICKERS_FILE).exists()), None)


def load_universe(paths: Paths) -> tuple[list[UniverseTicker], Path] | None:
    path = find_tickers_file(paths)
    if path is None:
        return None
    return universe_from_tickers_doc(orjson.loads(path.read_bytes())), path


def _share(n: int, d: int) -> float | None:
    return n / d if d else None


def coverage_report(
    universe: list[UniverseTicker], bars: pl.DataFrame, day: date, *, source: str = ""
) -> dict[str, Any]:
    """`bars`: the recent sessions' bars (ticker, date, close, volume), `day` the newest. Pure."""
    latest = bars.filter(pl.col("date") == day)
    priced_latest = set(latest["ticker"].to_list())
    priced_recent = set(bars["ticker"].to_list())
    sessions = bars["date"].n_unique()

    common = [u for u in universe if u.is_common]
    other = [u for u in universe if not u.is_common]
    by_exchange: dict[str, dict[str, int]] = {}
    totals: Counter[str] = Counter()
    hit_latest: Counter[str] = Counter()
    hit_recent: Counter[str] = Counter()
    for u in common:
        totals[u.exchange] += 1
        hit_latest[u.exchange] += u.ticker in priced_latest
        hit_recent[u.exchange] += u.ticker in priced_recent
    for ex in sorted(totals):
        by_exchange[ex] = {
            "common_listings": totals[ex],
            "priced_latest": hit_latest[ex],
            "priced_recent": hit_recent[ex],
        }

    n = len(common)
    missing_latest = sorted(u.ticker for u in common if u.ticker not in priced_latest)
    missing_recent = sorted(u.ticker for u in common if u.ticker not in priced_recent)
    universe_set = sorted({u.ticker for u in universe})
    extra = (
        latest.filter(~pl.col("ticker").is_in(universe_set))
        .with_columns((pl.col("close") * pl.col("volume")).alias("dollar_volume"))
        .sort(["dollar_volume", "ticker"], descending=[True, False], nulls_last=True)
        .head(TOP_EXTRA)
    )
    return {
        "date": day.isoformat(),
        "universe_source": source,
        "recent_sessions": sessions,
        "common_listings": n,
        "priced_latest": n - len(missing_latest),
        "coverage_latest": _share(n - len(missing_latest), n),
        "priced_recent": n - len(missing_recent),
        "coverage_recent": _share(n - len(missing_recent), n),
        "by_exchange": by_exchange,
        "other_listings": len(other),
        "other_listings_priced_latest": sum(u.ticker in priced_latest for u in other),
        "common_without_price_recent": missing_recent,
        "common_without_price_latest_only": sorted(set(missing_latest) - set(missing_recent)),
        "prices_not_in_universe_count": latest.filter(~pl.col("ticker").is_in(universe_set)).height,
        "prices_not_in_universe_top50": [
            {"ticker": t, "dollar_volume": dv}
            for t, dv in extra.select("ticker", "dollar_volume").rows()
        ],
    }
