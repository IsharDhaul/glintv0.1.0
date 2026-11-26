"""JSON file cache with TTLs and schema-versioned keys (`sec:companyfacts:v1:<cik>`).

Bump the `vN` part of a key whenever the stored shape changes; old entries are then ignored.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import orjson

from glint.core.errors import ContractError

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*:v\d+:[A-Za-z0-9._-]+$")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CacheHit:
    value: Any
    stored_at: datetime
    stale: bool


class JsonCache:
    def __init__(self, root: Path, *, now: Callable[[], datetime] = _utcnow) -> None:
        self.root = root
        self._now = now

    def _path(self, key: str) -> Path:
        if not KEY_RE.match(key):
            raise ContractError(f"bad cache key {key!r}: expected 'source:kind:vN:id'")
        source, kind, version, ident = key.split(":", 3)
        return self.root / source / kind / version / f"{ident}.json"

    def get(self, key: str, ttl: timedelta, *, allow_stale: bool = False) -> CacheHit | None:
        path = self._path(key)
        if not path.exists():
            return None
        entry = orjson.loads(path.read_bytes())
        stored_at = datetime.fromisoformat(entry["stored_at"])
        stale = self._now() - stored_at > ttl
        if stale and not allow_stale:
            return None
        return CacheHit(value=entry["value"], stored_at=stored_at, stale=stale)

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        entry = {"stored_at": self._now().isoformat(), "value": value}
        tmp.write_bytes(orjson.dumps(entry))
        tmp.replace(path)
