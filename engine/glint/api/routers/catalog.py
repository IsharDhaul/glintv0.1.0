"""Metrics registry, sectors, presets, and the columnar metrics snapshot."""

from functools import cache

from fastapi import APIRouter, Query, Request, Response

from glint.api.build import Build
from glint.api.deps import Builds, CurrentBuild
from glint.api.errors import ApiError
from glint.api.snapshot import snapshot_for
from glint.contracts.api import (
    ErrorCode,
    MetricsResponse,
    Preset,
    PresetListResponse,
    PresetResponse,
    PresetSummary,
    SectorCount,
    SectorsResponse,
    SnapshotMeta,
)
from glint.contracts.enums import Sector
from glint.screen.presets import load_presets

router = APIRouter(tags=["catalog"])


@router.get("/api/metrics")
def metrics(build: CurrentBuild) -> MetricsResponse:
    """Live metrics only, in registry order (a synthetic build treats every metric as live)."""
    return MetricsResponse(build_id=build.build_id, metrics=build.registry.live())


def _sector_counts(build: Build) -> list[SectorCount]:
    counts = dict(
        build.cursor()
        .execute("SELECT sector, count(*) FROM metrics_snapshot GROUP BY sector")
        .fetchall()
    )
    return [SectorCount(sector=s, count=int(counts.get(s.value, 0))) for s in Sector]


@router.get("/api/sectors")
def sectors(build: CurrentBuild) -> SectorsResponse:
    """Every sector in enum order, with its company count in the snapshot (0 if none)."""
    return SectorsResponse(build_id=build.build_id, sectors=build.cached("sectors", _sector_counts))


@cache
def _presets() -> dict[str, Preset]:
    """Presets are config, not build data: loaded (and validated) once per process."""
    return load_presets()


@router.get("/api/presets")
def presets(builds: Builds) -> PresetListResponse:
    summaries = [
        PresetSummary(id=p.id, name=p.name, summary=p.summary, kind=p.kind)
        for p in _presets().values()
    ]
    return PresetListResponse(build_id=builds.build_id(), presets=summaries)


@router.get("/api/presets/{preset_id}")
def preset(preset_id: str, builds: Builds) -> PresetResponse:
    """The preset with its `screen`: POST that object (not the whole preset) to /api/screen."""
    found = _presets().get(preset_id)
    if found is None:
        raise ApiError(404, ErrorCode.UNKNOWN_PRESET, f"No preset {preset_id!r}")
    return PresetResponse(build_id=builds.build_id(), preset=found)


IMMUTABLE = "public, max-age=31536000, immutable"


def _cache_control(build_id: str, asked: str | None) -> str:
    """Immutable only when the client names the build it got: a later build changes the URL."""
    return IMMUTABLE if asked == build_id else "no-cache"


@router.get("/api/snapshot/meta")
def snapshot_meta(
    build: CurrentBuild,
    response: Response,
    build_id: str | None = Query(
        default=None, alias="build", description="Cache key: the build_id"
    ),
) -> SnapshotMeta:
    """Rows and layout for `/api/snapshot/values` (same build)."""
    response.headers["Cache-Control"] = _cache_control(build.build_id, build_id)
    return snapshot_for(build).meta


@router.get(
    "/api/snapshot/values",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            }
        }
    },
)
def snapshot_values(
    build: CurrentBuild,
    request: Request,
    build_id: str | None = Query(
        default=None, alias="build", description="Cache key: the build_id"
    ),
) -> Response:
    """The build's metric values and reason codes as binary columns (layout: SnapshotMeta).
    Gzipped when the client accepts it. Check `X-Glint-Build` against the meta's `build_id`."""
    snap = snapshot_for(build)
    gz = "gzip" in request.headers.get("accept-encoding", "")
    headers = {
        "Cache-Control": _cache_control(build.build_id, build_id),
        "X-Glint-Build": build.build_id,
        "Vary": "Accept-Encoding",
    }
    if gz:
        headers["Content-Encoding"] = "gzip"
    return Response(
        content=snap.body_gzip if gz else snap.body,
        media_type="application/octet-stream",
        headers=headers,
    )
