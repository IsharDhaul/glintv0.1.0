"""Every on-disk location Glint uses, derived from settings."""

from dataclasses import dataclass
from pathlib import Path

from glint.core.settings import Settings, get_settings


@dataclass(frozen=True)
class Paths:
    raw_dir: Path
    db_dir: Path

    @property
    def raw_lock(self) -> Path:
        return self.raw_dir / "raw.lock"

    @property
    def sec_raw(self) -> Path:
        return self.raw_dir / "sec"

    @property
    def prices_raw(self) -> Path:
        return self.raw_dir / "prices"

    @property
    def snapshots(self) -> Path:
        return self.raw_dir / "snapshots"

    @property
    def cache_dir(self) -> Path:
        return self.raw_dir / "cache"

    @property
    def builds_dir(self) -> Path:
        return self.db_dir / "builds"

    @property
    def current_pointer(self) -> Path:
        return self.db_dir / "current.json"

    @property
    def user_db(self) -> Path:
        """Saved screens and watchlists. The pipeline never opens this file."""
        return self.db_dir / "user.duckdb"

    def build_db(self, build_id: str) -> Path:
        return self.builds_dir / f"{build_id}.duckdb"

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "Paths":
        s = settings or get_settings()
        return cls(raw_dir=s.raw_dir, db_dir=s.db_dir)
