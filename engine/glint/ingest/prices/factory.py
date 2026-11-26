"""Pick the price provider: Massive when configured, else the yfinance fallback (and say so)."""

from collections.abc import Sequence

from glint.core.cache import JsonCache
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.prices.massive import MassiveProvider
from glint.ingest.prices.provider import PriceProvider
from glint.ingest.prices.yfinance_provider import YFinanceProvider


def make_provider(
    settings: Settings, *, tickers: Sequence[str] = (), force: str | None = None
) -> PriceProvider:
    """`force` overrides `GLINT_PRICE_PROVIDER`. yfinance needs `tickers` (it has no "all")."""
    choice = force or settings.price_provider
    if choice == "massive" and settings.massive_api_key:
        cache = JsonCache(Paths.from_settings(settings).cache_dir)
        return MassiveProvider.from_settings(settings, cache=cache)
    # yfinance chosen on purpose is not a fallback; massive without a key is.
    return YFinanceProvider(tickers, is_fallback=choice == "massive")
