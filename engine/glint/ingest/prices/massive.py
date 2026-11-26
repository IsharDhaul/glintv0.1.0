"""`MassiveProvider`: Massive (formerly Polygon.io) REST API, the preferred price source.

- Grouped daily (`/v2/aggs/grouped/...`): every US ticker for one date in one call.
- **Unadjusted** bars (`adjusted=false`); splits come from `/stocks/v1/splits`.
- Paced client-side to `MASSIVE_CALLS_PER_MIN` (free plan: 5); 429 waits out the window,
  5xx and network errors back off and retry, 401/403 fail at once.
- Never requests today's date (403 on the free plan, and the bar wouldn't be final).
- Endpoint details and the date they were checked: `docs/decisions/WT-02.md`.
"""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
import orjson
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from glint.core.cache import JsonCache
from glint.core.errors import SourceError
from glint.core.log import get_logger, log_event
from glint.core.settings import REPO_ROOT, Settings
from glint.ingest.prices.models import Bar, Split
from glint.ingest.prices.pacing import Pacer
from glint.ingest.prices.provider import MARKET_TZ, HistoryLimitError, market_today
from glint.ingest.prices.symbols import canonical_from_massive, to_massive

DEFAULT_BASE_URL = "https://api.massive.com"
SOURCE = "massive"
RETRY_STATUSES = frozenset({500, 502, 503, 504})
DEFAULT_RETRY_AFTER_S = 60.0
HISTORY_TTL = timedelta(days=30)  # unadjusted past bars don't change
SPLITS_TTL = timedelta(hours=12)
SPLITS_PAGE_LIMIT = 5000
HISTORY_LIMIT = 50000

log = get_logger(__name__)


class MassiveSettings(BaseSettings):
    """Massive-only settings that live with the provider (core settings are a WT-00 contract)."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    base_url: str = Field(default=DEFAULT_BASE_URL, alias="MASSIVE_BASE_URL")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _bar_date(ms: int) -> date:
    """Massive stamps a daily bar with a Unix-ms time inside that New York trading day."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).astimezone(MARKET_TZ).date()


def _retry_after_s(header: str | None) -> float:
    """`Retry-After` in seconds; an HTTP-date or junk value falls back to a full minute."""
    try:
        return max(float(header), 1.0) if header else DEFAULT_RETRY_AFTER_S
    except ValueError:
        return DEFAULT_RETRY_AFTER_S


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


class MassiveProvider:
    name = SOURCE
    is_fallback = False

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        calls_per_min: int = 5,
        cache: JsonCache | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utcnow,
        max_attempts: int = 5,
        backoff_initial_s: float = 2.0,
    ) -> None:
        if not api_key:
            raise SourceError(SOURCE, "MASSIVE_API_KEY is empty")
        self._base_host = urlparse(base_url).hostname
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=httpx.Timeout(30.0, read=120.0),
            transport=transport,
        )
        self.pacer = Pacer(calls_per_min, clock=clock, sleep=sleep)
        self._sleep = sleep
        self._now = now
        self._cache = cache
        self._max_attempts = max_attempts
        self._backoff_initial_s = backoff_initial_s
        self.calls = 0

    @classmethod
    def from_settings(
        cls, settings: Settings, *, cache: JsonCache | None = None
    ) -> "MassiveProvider":
        return cls(
            settings.massive_api_key or "",
            base_url=MassiveSettings().base_url,
            calls_per_min=settings.massive_calls_per_min,
            cache=cache,
        )

    def close(self) -> None:
        self._client.close()

    # --- PriceProvider ---------------------------------------------------------------------

    def bars_for_date(self, day: date) -> list[Bar]:
        self._refuse_today(day)
        if day.weekday() >= 5:
            return []
        doc = self._get(
            f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}",
            {"adjusted": "false"},
        )
        if doc.get("status") not in (None, "OK", "DELAYED"):
            raise SourceError(SOURCE, f"grouped daily {day}: status {doc.get('status')!r}")
        if doc.get("adjusted") is True:
            raise SourceError(SOURCE, f"asked for unadjusted bars on {day}, got adjusted ones")
        rows: list[dict[str, Any]] = doc.get("results") or []
        bars: list[Bar] = []
        for row in rows:
            if row.get("c") is None or not row.get("T"):
                continue
            bars.append(
                Bar(
                    ticker=canonical_from_massive(str(row["T"])),
                    date=day,
                    open=_float_or_none(row.get("o")),
                    high=_float_or_none(row.get("h")),
                    low=_float_or_none(row.get("l")),
                    close=float(row["c"]),
                    volume=_float_or_none(row.get("v")),
                    vwap=_float_or_none(row.get("vw")),
                )
            )
        bars.sort(key=lambda b: b.ticker)
        return bars

    def history(self, ticker: str, start: date, end: date) -> list[Bar]:
        end = min(end, market_today(self._now()) - timedelta(days=1))
        if end < start:
            return []
        key = f"massive:history:v1:{ticker}_{start.isoformat()}_{end.isoformat()}"
        rows = self._cached(key, HISTORY_TTL)
        if rows is None:
            rows = self._paged(
                f"/v2/aggs/ticker/{to_massive(ticker)}/range/1/day/{start}/{end}",
                {"adjusted": "false", "sort": "asc", "limit": str(HISTORY_LIMIT)},
            )
            self._store(key, rows)
        return [
            Bar(
                ticker=ticker,
                date=_bar_date(int(r["t"])),
                open=_float_or_none(r.get("o")),
                high=_float_or_none(r.get("h")),
                low=_float_or_none(r.get("l")),
                close=float(r["c"]),
                volume=_float_or_none(r.get("v")),
                vwap=_float_or_none(r.get("vw")),
            )
            for r in rows
            if r.get("c") is not None
        ]

    def splits(self, since: date) -> list[Split]:
        key = f"massive:splits:v1:{since.isoformat()}"
        rows = self._cached(key, SPLITS_TTL)
        if rows is None:
            rows = self._paged(
                "/stocks/v1/splits",
                {
                    "execution_date.gte": since.isoformat(),
                    "limit": str(SPLITS_PAGE_LIMIT),
                    "sort": "execution_date.asc",
                },
            )
            self._store(key, rows)
        out = [
            Split(
                ticker=canonical_from_massive(str(r["ticker"])),
                execution_date=date.fromisoformat(str(r["execution_date"])),
                split_from=float(r["split_from"]),
                split_to=float(r["split_to"]),
                adjustment_type=r.get("adjustment_type"),
            )
            for r in rows
            if r.get("ticker") and r.get("split_from") and r.get("split_to")
        ]
        out.sort(key=lambda s: (s.execution_date, s.ticker))
        return out

    def prefetch(self, days: Sequence[date]) -> None:
        return None

    # --- HTTP ------------------------------------------------------------------------------

    def _refuse_today(self, day: date) -> None:
        today = market_today(self._now())
        if day >= today:
            raise SourceError(
                SOURCE,
                f"refusing to request {day}: end-of-day data only, newest allowed is "
                f"{today - timedelta(days=1)} (New York)",
            )

    def _cached(self, key: str, ttl: timedelta) -> list[dict[str, Any]] | None:
        if self._cache is None:
            return None
        hit = self._cache.get(key, ttl)
        return None if hit is None else hit.value

    def _store(self, key: str, rows: list[dict[str, Any]]) -> None:
        if self._cache is not None:
            self._cache.set(key, rows)

    def _paged(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        doc = self._get(path, params)
        rows += doc.get("results") or []
        while next_url := str(doc.get("next_url") or ""):
            if urlparse(next_url).hostname != self._base_host:
                raise SourceError(SOURCE, f"refusing next_url on another host: {next_url}")
            doc = self._get(next_url, None)
            rows += doc.get("results") or []
        return rows

    def _get(self, url: str, params: dict[str, str] | None) -> dict[str, Any]:
        path = urlparse(url).path
        last_error = "no attempts made"
        for attempt in range(self._max_attempts):
            self.pacer.wait()
            self.calls += 1
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = f"network error: {exc}"
                self._backoff(attempt, path, last_error)
                continue
            status = resp.status_code
            if status == 200:
                log_event(log, "massive_call", path=path, status=status)
                return orjson.loads(resp.content)
            detail = self._error_detail(resp)
            if status == 429:
                retry_after = _retry_after_s(resp.headers.get("Retry-After"))
                log_event(log, "massive_rate_limited", path=path, retry_after_s=retry_after)
                self.pacer.penalize(retry_after)
                last_error = f"HTTP 429 {detail}"
                continue
            if status in RETRY_STATUSES:
                last_error = f"HTTP {status} {detail}"
                self._backoff(attempt, path, last_error)
                continue
            if status == 403 and "entitlement" in detail.lower():
                raise HistoryLimitError(SOURCE, f"{path}: {detail}", status=status)
            hint = " (check MASSIVE_API_KEY and your plan)" if status in (401, 403) else ""
            raise SourceError(SOURCE, f"HTTP {status} for {path}: {detail}{hint}", status=status)
        raise SourceError(
            SOURCE, f"gave up on {path} after {self._max_attempts} tries: {last_error}"
        )

    def _backoff(self, attempt: int, path: str, error: str) -> None:
        delay = self._backoff_initial_s * 2**attempt
        log_event(log, "massive_retry", path=path, attempt=attempt + 1, delay_s=delay, error=error)
        self._sleep(delay)

    @staticmethod
    def _error_detail(resp: httpx.Response) -> str:
        try:
            body = orjson.loads(resp.content)
        except orjson.JSONDecodeError:
            return resp.text[:200]
        if isinstance(body, dict):
            return str(body.get("error") or body.get("message") or body.get("status") or "")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        return ""
