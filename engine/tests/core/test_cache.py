from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from glint.core.cache import JsonCache
from glint.core.errors import ContractError


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 28, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t


def test_roundtrip_and_ttl(tmp_path: Path) -> None:
    clock = Clock()
    cache = JsonCache(tmp_path, now=clock)
    cache.set("sec:companyfacts:v1:0000320193", {"a": 1})
    hit = cache.get("sec:companyfacts:v1:0000320193", timedelta(hours=1))
    assert hit is not None and hit.value == {"a": 1} and not hit.stale

    clock.t += timedelta(hours=2)
    assert cache.get("sec:companyfacts:v1:0000320193", timedelta(hours=1)) is None
    stale = cache.get("sec:companyfacts:v1:0000320193", timedelta(hours=1), allow_stale=True)
    assert stale is not None and stale.stale


def test_version_bump_misses(tmp_path: Path) -> None:
    cache = JsonCache(tmp_path)
    cache.set("sec:companyfacts:v1:1", 1)
    assert cache.get("sec:companyfacts:v2:1", timedelta(days=1)) is None


@pytest.mark.parametrize("key", ["companyfacts:1", "sec:companyfacts:1:x", "sec:cf:v1:../x"])
def test_bad_keys_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(ContractError):
        JsonCache(tmp_path).get(key, timedelta(days=1))
