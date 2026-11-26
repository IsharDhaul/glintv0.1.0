"""Finding and opening the current build.

`BuildManager` holds one read-only DuckDB connection to the build `current.json` points at.
It stats the pointer at most every `check_interval` seconds and reopens when the pointer
changes, so a pipeline swap is picked up without a restart. Each request gets its own cursor
(DuckDB connections aren't safe to share across threads; cursors are).
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
from pydantic import ValidationError

from glint.contracts.api import ErrorCode
from glint.contracts.db import DB_SCHEMA_VERSION, CurrentPointer
from glint.contracts.metrics import MetricRegistry
from glint.core.errors import ContractError, GlintError
from glint.core.log import get_logger, log_event
from glint.core.paths import Paths
from glint.screen.engine import registry_for_build

log = get_logger(__name__)

POINTER_CHECK_SECONDS = 30.0
NO_BUILD_MESSAGE = "No build yet: run `glint fixtures synthetic` or `glint refresh`."


def read_pointer(paths: Paths | None = None) -> CurrentPointer | None:
    """None if there is no build yet; raises ContractError if current.json is unreadable."""
    p = (paths or Paths.from_settings()).current_pointer
    if not p.exists():
        return None
    try:
        return CurrentPointer.model_validate_json(p.read_text())
    except (ValidationError, ValueError) as exc:
        raise ContractError(f"{p.name} is unreadable: rebuild or fix it") from exc


def current_build_id(paths: Paths | None = None) -> str | None:
    try:
        pointer = read_pointer(paths)
    except ContractError:
        return None
    return pointer.build_id if pointer else None


def build_db_path(pointer: CurrentPointer, paths: Paths | None = None) -> Path:
    return (paths or Paths.from_settings()).db_dir / pointer.path


def connect_read_only(path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=True)


class BuildUnavailableError(GlintError):
    """503: no usable build (`NO_BUILD`) or one this engine can't read (`SCHEMA_MISMATCH`)."""

    def __init__(self, code: ErrorCode, message: str, build_id: str | None) -> None:
        super().__init__(message, code=code.value)
        self.error_code = code
        self.build_id = build_id


@dataclass
class Build:
    """One open build. Derived data (registry, search index, …) is cached per build, so
    nothing computed from one build is ever served for another."""

    pointer: CurrentPointer
    path: Path
    con: duckdb.DuckDBPyConnection
    meta: dict[str, str]
    _cache: dict[str, Any] = field(default_factory=dict[str, Any])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def build_id(self) -> str:
        return self.pointer.build_id

    @property
    def synthetic(self) -> bool:
        return self.pointer.synthetic or self.meta.get("synthetic") == "true"

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self.con.cursor()

    def cached[T](self, key: str, make: Callable[["Build"], T]) -> T:
        with self._lock:
            if key not in self._cache:
                self._cache[key] = make(self)
            return self._cache[key]

    @property
    def registry(self) -> MetricRegistry:
        return self.cached("registry", lambda b: registry_for_build(b.cursor()))


def _stat_key(path: Path) -> tuple[int, int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_ino, st.st_size)


def _open(pointer: CurrentPointer, paths: Paths) -> Build:
    if pointer.db_schema_version != DB_SCHEMA_VERSION:
        raise BuildUnavailableError(
            ErrorCode.SCHEMA_MISMATCH,
            f"Build schema v{pointer.db_schema_version} != engine v{DB_SCHEMA_VERSION}: rebuild.",
            pointer.build_id,
        )
    path = build_db_path(pointer, paths)
    if not path.exists():
        raise BuildUnavailableError(
            ErrorCode.NO_BUILD,
            f"current.json points at missing {path.name}: rebuild.",
            pointer.build_id,
        )
    con = connect_read_only(path)
    meta: dict[str, str] = dict(con.execute("SELECT key, value FROM build_meta").fetchall())
    # The build's own build_meta is authoritative: a pointer can't hide a schema mismatch.
    if meta.get("db_schema_version") != str(DB_SCHEMA_VERSION):
        con.close()
        raise BuildUnavailableError(
            ErrorCode.SCHEMA_MISMATCH,
            f"Build schema v{meta.get('db_schema_version')} != engine v{DB_SCHEMA_VERSION}: "
            "rebuild.",
            pointer.build_id,
        )
    return Build(pointer=pointer, path=path, con=con, meta=meta)


class BuildManager:
    """The API's view of `current.json`. Thread-safe; one per app."""

    def __init__(
        self,
        paths: Paths | None = None,
        check_interval: float = POINTER_CHECK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._paths = paths
        self.check_interval = check_interval
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_at: float | None = None
        self._loaded = False
        self._stat: tuple[int, int, int] | None = None
        self._build: Build | None = None
        self._error: BuildUnavailableError | None = None

    @property
    def paths(self) -> Paths:
        # Resolved lazily, so settings read at request time (tests set GLINT_DB_DIR first).
        if self._paths is None:
            self._paths = Paths.from_settings()
        return self._paths

    def _refresh(self) -> None:
        """Stat the pointer at most every `check_interval` s while a build is being served; on
        every call while there isn't one. Reopen when it changed, and retry a failed open every
        `check_interval` s even if it didn't (the file it points at may appear, or a lock clear)."""
        now = self._clock()
        due = self._checked_at is None or now - self._checked_at >= self.check_interval
        healthy = self._build is not None
        if healthy and not due:
            return
        stat = _stat_key(self.paths.current_pointer)
        changed = not self._loaded or stat != self._stat
        if not changed and (healthy or not due):
            if healthy:
                self._checked_at = now
            return
        self._checked_at, self._loaded, self._stat = now, True, stat
        old = self._build
        self._build, self._error = None, None
        try:
            pointer = read_pointer(self.paths)
            if pointer is None:
                self._error = BuildUnavailableError(ErrorCode.NO_BUILD, NO_BUILD_MESSAGE, None)
            else:
                if old is not None and old.path == build_db_path(pointer, self.paths):
                    # Rebuilt in place (e.g. `glint fixtures synthetic`): DuckDB would hand back
                    # the cached, unlinked database while the old connection is open.
                    old.con.close()
                self._build = _open(pointer, self.paths)
        except BuildUnavailableError as exc:
            self._error = exc
        except ContractError as exc:
            self._error = BuildUnavailableError(ErrorCode.NO_BUILD, exc.message, None)
        except Exception as exc:  # any open failure is "no usable build", not a 500 loop
            log.exception("build_open_failed")
            self._error = BuildUnavailableError(
                ErrorCode.NO_BUILD, f"The build can't be opened: {exc}", None
            )
        log_event(
            log,
            "build_opened",
            previous=old.build_id if old else None,
            build=self._build.build_id if self._build else None,
            error=self._error.code if self._error else None,
        )

    def get(self) -> Build:
        """The current build, or raises BuildUnavailableError (→ 503)."""
        with self._lock:
            self._refresh()
            if self._build is None:
                assert self._error is not None
                raise self._error
            return self._build

    def peek(self) -> Build | None:
        """The current build if there is a usable one; never raises."""
        try:
            return self.get()
        except BuildUnavailableError:
            return None

    def last_build_id(self) -> str | None:
        """The build id as of the last check, without re-checking (safe in async code; only
        the very first call, before any check, looks at the pointer)."""
        with self._lock:
            if not self._loaded:
                self._refresh()
            if self._build is not None:
                return self._build.build_id
            return self._error.build_id if self._error else None

    def build_id(self) -> str | None:
        """For `build_id` on every response, including 503s."""
        with self._lock:
            self._refresh()
            if self._build is not None:
                return self._build.build_id
            return self._error.build_id if self._error else None
