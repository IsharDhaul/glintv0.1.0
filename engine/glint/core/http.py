"""The SEC gateway. Every request to sec.gov goes through `SecGateway`; nothing else may call SEC.

- User-Agent with a contact address, from settings (SEC fair-access policy).
- Global throttle at `GLINT_SEC_MAX_RPS` requests per second (aiolimiter).
- Retries on 429, 5xx and network errors with exponential backoff plus jitter (tenacity).
- Conditional GET for downloads: ETag / Last-Modified stored next to the file as `<file>.meta.json`.
- Large downloads stream to a temp file, then replace the target atomically.
"""

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlparse

import httpx
import orjson
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from glint.core.errors import SourceError
from glint.core.log import get_logger, log_event
from glint.core.settings import Settings, get_settings

SEC_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
CHUNK_BYTES = 1 << 20

log = get_logger(__name__)


class _RetryableStatusError(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableStatusError | httpx.TransportError)


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    changed: bool
    status: int
    bytes: int
    etag: str | None
    last_modified: str | None


def _meta_path(dest: Path) -> Path:
    return dest.with_name(dest.name + ".meta.json")


class SecGateway:
    """Async SEC client. Use as `async with SecGateway() as sec: ...`."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 5,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 30.0,
    ) -> None:
        self.settings = settings or get_settings()
        if not self.settings.sec_contact_configured:
            raise SourceError(
                "sec",
                "GLINT_SEC_USER_AGENT needs a real contact address (set it in .env). "
                "SEC's fair-access policy requires one.",
            )
        self._limiter = AsyncLimiter(self.settings.sec_max_rps, 1)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": self.settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
            transport=transport,
        )
        self._max_attempts = max_attempts
        self._backoff_initial_s = backoff_initial_s
        self._backoff_max_s = backoff_max_s

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _check_host(self, url: str) -> None:
        host = urlparse(url).hostname
        if host not in SEC_HOSTS:
            raise SourceError("sec", f"refusing non-SEC host {host!r}; use the right gateway")

    def _retrying(self) -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(
                multiplier=self._backoff_initial_s, max=self._backoff_max_s
            ),
            reraise=False,
        )

    async def get_json(self, url: str) -> Any:
        """GET a JSON document (per-company APIs: fixtures and spot checks only)."""
        self._check_host(url)
        try:
            async for attempt in self._retrying():
                with attempt:
                    async with self._limiter:
                        resp = await self._client.get(url)
                    if resp.status_code in RETRY_STATUSES:
                        raise _RetryableStatusError(resp.status_code, url)
                    if resp.status_code != 200:
                        raise SourceError(
                            "sec", f"HTTP {resp.status_code} for {url}", status=resp.status_code
                        )
                    return orjson.loads(resp.content)
        except RetryError as exc:
            raise self._exhausted(url, exc) from exc
        raise AssertionError("unreachable")

    async def download(self, url: str, dest: Path) -> DownloadResult:
        """Stream `url` to `dest`, skipping the body when SEC says it hasn't changed (304)."""
        self._check_host(url)
        meta_path = _meta_path(dest)
        headers: dict[str, str] = {}
        if dest.exists() and meta_path.exists():
            meta = orjson.loads(meta_path.read_bytes())
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            async for attempt in self._retrying():
                with attempt:
                    return await self._download_once(url, dest, tmp, meta_path, headers)
        except RetryError as exc:
            raise self._exhausted(url, exc) from exc
        finally:
            tmp.unlink(missing_ok=True)
        raise AssertionError("unreachable")

    async def _download_once(
        self, url: str, dest: Path, tmp: Path, meta_path: Path, headers: dict[str, str]
    ) -> DownloadResult:
        async with self._limiter, self._client.stream("GET", url, headers=headers) as resp:
            if resp.status_code in RETRY_STATUSES:
                raise _RetryableStatusError(resp.status_code, url)
            etag = resp.headers.get("ETag")
            last_modified = resp.headers.get("Last-Modified")
            if resp.status_code == 304:
                log_event(log, "sec_download_unchanged", url=url)
                return DownloadResult(
                    dest,
                    False,
                    304,
                    dest.stat().st_size,
                    etag or headers.get("If-None-Match"),
                    last_modified or headers.get("If-Modified-Since"),
                )
            if resp.status_code != 200:
                raise SourceError(
                    "sec", f"HTTP {resp.status_code} for {url}", status=resp.status_code
                )
            size = 0
            with tmp.open("wb") as fh:
                async for chunk in resp.aiter_bytes(CHUNK_BYTES):
                    fh.write(chunk)
                    size += len(chunk)
        tmp.replace(dest)
        meta_path.write_bytes(
            orjson.dumps({"url": url, "etag": etag, "last_modified": last_modified, "bytes": size})
        )
        log_event(log, "sec_download_done", url=url, bytes=size)
        return DownloadResult(dest, True, 200, size, etag, last_modified)

    @staticmethod
    def _exhausted(url: str, exc: RetryError) -> SourceError:
        last = exc.last_attempt.exception()
        status = last.status if isinstance(last, _RetryableStatusError) else None
        return SourceError("sec", f"gave up on {url} after retries: {last}", status=status)
