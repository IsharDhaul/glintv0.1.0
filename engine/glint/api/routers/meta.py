import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
from fastapi import APIRouter

from glint.api.build import (
    NO_BUILD_MESSAGE,
    Build,
    BuildUnavailableError,
    connect_read_only,
)
from glint.api.deps import Builds
from glint.api.errors import ApiError
from glint.contracts.api import (
    AsOf,
    ErrorCode,
    LastRun,
    MetaResponse,
    RunStatus,
    UniverseCounts,
    UniverseRules,
)
from glint.contracts.db import DB_SCHEMA_VERSION, CurrentPointer
from glint.contracts.enums import Kind
from glint.metrics.params import load_params

router = APIRouter(tags=["meta"])

NO_BUILD_WARNING = NO_BUILD_MESSAGE


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _as_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def as_of(build: Build) -> AsOf:
    return AsOf(
        fundamentals=_as_datetime(build.meta.get("as_of_fundamentals")),
        prices=_as_date(build.meta.get("as_of_prices")),
    )


def universe_rules() -> UniverseRules:
    """From `config/thresholds.yaml` via the same loader the metrics stage uses."""
    return UniverseRules(stale_annual_report_months=load_params().stale_annual_report_months)


def _no_build_meta() -> MetaResponse:
    return MetaResponse(
        build_id=None,
        synthetic=False,
        db_schema_version=None,
        built_at=None,
        as_of=AsOf(fundamentals=None, prices=None),
        universe_counts=None,
        universe_rules=universe_rules(),
        source_timestamps={},
        last_run=None,
        warnings=[NO_BUILD_WARNING],
    )


@router.get("/api/meta")
def meta(builds: Builds) -> MetaResponse:
    """200 with a warning when there is no build yet (the header still renders); 503 when
    current.json is unreadable, points at a missing file, or the schema doesn't match."""
    try:
        build = builds.get()
    except BuildUnavailableError:
        if not builds.paths.current_pointer.exists():
            return _no_build_meta()
        raise
    return build.cached("meta", _meta_for)


def _meta_for(build: Build) -> MetaResponse:
    return meta_from_connection(build.pointer, build.cursor(), build.meta)


def meta_from_build(pointer: CurrentPointer, db_path: Path) -> MetaResponse:
    """MetaResponse for one build file (also used to export web/mocks/meta.json)."""
    with connect_read_only(db_path) as con:
        kv: dict[str, str] = dict(con.execute("SELECT key, value FROM build_meta").fetchall())
        return meta_from_connection(pointer, con, kv)


def _last_run(con: duckdb.DuckDBPyConnection) -> tuple[LastRun | None, dict[str, Any]]:
    row = con.execute(
        "SELECT run_id, status, started, finished, warnings, source_timestamps "
        "FROM pipeline_runs ORDER BY started DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None, {}
    run_id, status, started, finished, warnings, sources = row
    run = LastRun(
        run_id=run_id,
        status=RunStatus(status),
        started=started,
        finished=finished,
        warnings=[str(w) for w in json.loads(warnings)],
    )
    return run, json.loads(sources)


def meta_from_connection(
    pointer: CurrentPointer, con: duckdb.DuckDBPyConnection, kv: dict[str, str]
) -> MetaResponse:
    """The build's own `build_meta` is authoritative: a pointer can't hide a synthetic build or
    a schema mismatch."""
    if kv.get("db_schema_version") != str(DB_SCHEMA_VERSION):
        raise ApiError(
            503,
            ErrorCode.SCHEMA_MISMATCH,
            f"Build schema v{kv.get('db_schema_version')} != engine v{DB_SCHEMA_VERSION}: rebuild.",
        )
    rows = con.execute(
        "SELECT kind, exchange, is_foreign_filer, is_stale FROM metrics_snapshot"
    ).fetchall()
    by_kind: dict[str, int] = {}
    by_exchange: dict[str, int] = {}
    for kind, exchange, _, _ in rows:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_exchange[exchange or "unknown"] = by_exchange.get(exchange or "unknown", 0) + 1
    synthetic = (
        pointer.synthetic or kv.get("synthetic") == "true" or Kind.SYNTHETIC.value in by_kind
    )
    last_run, sources = _last_run(con)
    warnings: list[str] = []
    if synthetic:
        warnings.append("Synthetic data: not real companies or numbers.")
    if last_run is not None:
        warnings += last_run.warnings
    return MetaResponse(
        build_id=pointer.build_id,
        synthetic=synthetic,
        db_schema_version=int(kv["db_schema_version"]),
        built_at=pointer.created_at,
        as_of=AsOf(
            fundamentals=_as_datetime(kv.get("as_of_fundamentals")),
            prices=_as_date(kv.get("as_of_prices")),
        ),
        universe_counts=UniverseCounts(
            companies=len(rows),
            by_kind=by_kind,
            by_exchange=by_exchange,
            foreign_filers=sum(1 for r in rows if r[2]),
            stale=sum(1 for r in rows if r[3]),
        ),
        universe_rules=universe_rules(),
        source_timestamps={k: _as_datetime(v) for k, v in sorted(sources.items())},
        last_run=last_run,
        warnings=warnings,
    )
