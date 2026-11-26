"""The `PriceProvider` interface: the only way Glint gets market prices (SPEC §5.7).

Every implementation:
- returns **unadjusted** bars keyed by canonical symbols (`BRK.B`);
- never asks for the current day (end-of-day data only);
- raises `SourceError` on failure, so a price outage degrades price-tier metrics only;
- caches what it fetches (grouped-daily dates are cached by the parquet store itself).
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from glint.core.errors import SourceError
from glint.ingest.prices.models import Bar, Split

MARKET_TZ = ZoneInfo("America/New_York")


class HistoryLimitError(SourceError):
    """The date is older than the provider plan's history (e.g. Massive's free ~2 years)."""

    code = "PRICE_HISTORY_LIMIT"


@runtime_checkable
class PriceProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_fallback(self) -> bool:
        """True for providers used only because the preferred one isn't configured."""
        ...

    def bars_for_date(self, day: date) -> list[Bar]:
        """Every ticker's bar on `day`. An empty list means the market was closed."""
        ...

    def history(self, ticker: str, start: date, end: date) -> list[Bar]:
        """One ticker's bars for `start..end` inclusive, oldest first."""
        ...

    def splits(self, since: date) -> list[Split]:
        """Splits with `execution_date >= since`."""
        ...

    def prefetch(self, days: Sequence[date]) -> None:
        """Hint that `bars_for_date` is about to be called for `days` (batch providers use it)."""
        ...


def market_today(now: datetime | None = None) -> date:
    """Today's date in New York, where the trading day is defined."""
    return (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ).date()


def latest_requestable(now: datetime | None = None) -> date:
    """The newest date a provider may be asked for: yesterday in New York (never "today")."""
    return market_today(now) - timedelta(days=1)
