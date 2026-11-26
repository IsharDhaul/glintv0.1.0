"""Pipeline stage interface. Each module (WT-01/02/03/06) exposes `Stage`s; WT-07 runs them."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from glint.core.paths import Paths
from glint.core.settings import Settings


class StageStatus(StrEnum):
    OK = "ok"
    WARN = "warn"  # finished, with warnings worth reading
    SKIPPED = "skipped"
    FAILED = "failed"


class StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    status: StageStatus
    counts: dict[str, int] = Field(default_factory=dict[str, int])
    warnings: list[str] = Field(default_factory=list[str])
    duration_s: float = Field(ge=0)
    error: str | None = None


@dataclass(frozen=True)
class BuildOptions:
    no_download: bool = False
    skip_prices: bool = False
    dry_run: bool = False


@dataclass
class BuildContext:
    """Everything a stage needs. Stages write only to `build_db` and (under raw.lock) raw dirs."""

    build_id: str
    settings: Settings
    paths: Paths
    build_db: Path
    options: BuildOptions = field(default_factory=BuildOptions)
    raw_date: date | None = None  # which GLINT_RAW_DIR/sec/<date>/ snapshot to read
    results: dict[str, StageResult] = field(default_factory=dict[str, StageResult])


@runtime_checkable
class Stage(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def deps(self) -> tuple[str, ...]: ...

    def run(self, ctx: BuildContext) -> StageResult: ...
