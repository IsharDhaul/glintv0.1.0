"""Run a screen, export it as CSV, and metric distributions for the threshold UI.

The `/api/screen` body is a `Screen` object. A preset file wraps one in metadata: send the
preset's `screen`, not the whole preset (`GET /api/presets/{id}` → `.preset.screen`).
"""

import csv
import io
import math
import re
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response, StreamingResponse

from glint.api.build import Build
from glint.api.deps import CurrentBuild
from glint.api.errors import ApiError
from glint.contracts.api import (
    CellValue,
    DistributionResponse,
    ErrorCode,
    HistogramBin,
    ResultRow,
    ScreenResponse,
)
from glint.contracts.enums import Sector, Unit
from glint.contracts.screen import Screen, Universe, Within
from glint.screen.compile import compile_screen
from glint.screen.config import load_screen_config
from glint.screen.engine import RANK_SCORE
from glint.screen.engine import run_screen as run_engine

router = APIRouter(tags=["screen"])

HISTOGRAM_BINS = 30
# Interior bin edges span these percentiles; the end bins stretch to the min and max, so fat
# tails don't squash the histogram into one bar yet every value is still counted.
HISTOGRAM_CLIP = (0.01, 0.99)
PERCENTILES = {"p5": 0.05, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p95": 0.95}
EXPORT_EXTRA_COLUMNS = ("as_of_fundamentals", "as_of_prices", "notes")


@router.post("/api/screen")
def run_screen(screen: Screen, build: CurrentBuild) -> ScreenResponse:
    """422 INVALID_SCREEN (with the field path) when the screen doesn't fit this build."""
    return run_engine(build.cursor(), screen, build.registry).response


# --- export ------------------------------------------------------------------------------------


def screen_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "screen"


def _csv_cell(value: CellValue | int | date) -> str:
    if value is None:
        return ""  # the `notes` column says why
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _notes_cell(row: ResultRow, columns: list[str], ranked: bool) -> str:
    """Null reasons for the exported cells. A null `rank` carries the `rank_score` reason."""
    notes = {k: n for k, n in row.notes.items() if k in columns}
    if ranked and row.rank is None and RANK_SCORE in row.notes:
        notes["rank"] = row.notes[RANK_SCORE]
    return "; ".join(f"{k}: {n.code.value} ({n.message})" for k, n in sorted(notes.items()))


def _export_rows(screen: Screen, build: Build) -> tuple[list[str], list[list[str]]]:
    ranked = screen.rank is not None
    # Ask for rank_score too, so the engine attaches the reason when a rank is null.
    run_columns = [
        *screen.columns,
        *([RANK_SCORE] if ranked and RANK_SCORE not in screen.columns else []),
    ]
    run = screen.model_copy(update={"columns": run_columns})
    response = run_engine(build.cursor(), run, build.registry).response
    ciks = [r.cik for r in response.results]
    as_of = {
        cik: (f, p)
        for cik, f, p in build.cursor()
        .execute(
            "SELECT cik, as_of_fundamentals, as_of_prices FROM metrics_snapshot "
            "WHERE list_contains($ciks, cik)",
            {"ciks": ciks},
        )
        .fetchall()
    }
    add_ticker = "ticker" not in screen.columns
    header = [*(["rank"] if ranked else []), *(["ticker"] if add_ticker else []),
              *screen.columns, *EXPORT_EXTRA_COLUMNS]  # fmt: skip
    rows: list[list[str]] = []
    for r in response.results:
        fundamentals, prices = as_of.get(r.cik, (None, None))
        rows.append(
            [
                *([_csv_cell(r.rank)] if ranked else []),
                *([r.ticker] if add_ticker else []),
                *(_csv_cell(r.values.get(c)) for c in screen.columns),
                _csv_cell(fundamentals),
                _csv_cell(prices),
                _notes_cell(r, screen.columns, ranked),
            ]
        )
    return header, rows


def _stream_csv(header: list[str], rows: list[list[str]]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for line in [header, *rows]:
        writer.writerow(line)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()


@router.post(
    "/api/screen/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "CSV stream (§2.12)"}},
)
def export_screen(screen: Screen, build: CurrentBuild) -> StreamingResponse:
    """The result rows (as many as `limit`) with the screen's columns, plus `rank` when
    ranked, `ticker` if not already a column, the as-of dates and the null reasons."""
    header, rows = _export_rows(screen, build)
    filename = (
        f"glint-{screen_slug(screen.name)}-{datetime.now().astimezone().date().isoformat()}.csv"
    )
    return StreamingResponse(
        _stream_csv(header, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- distribution ------------------------------------------------------------------------------

_PARAM_RE = re.compile(r"\$(p\d+)\b")


def used_params(sql: str, params: dict[str, Any]) -> dict[str, Any]:
    """The params a statement uses: DuckDB rejects unused named parameters."""
    used = set(_PARAM_RE.findall(sql))
    return {k: v for k, v in params.items() if k in used}


def _bins(values: list[float], lo_clip: float, hi_clip: float) -> list[HistogramBin]:
    """HISTOGRAM_BINS bins: equal widths over [lo_clip, hi_clip], with the first bin starting at
    the minimum and the last ending at the maximum. `values` is sorted and non-empty."""
    lo, hi = values[0], values[-1]
    if hi_clip <= lo_clip:
        return [HistogramBin(lo=lo, hi=hi, count=len(values))]
    width = (hi_clip - lo_clip) / HISTOGRAM_BINS
    edges = [lo_clip + i * width for i in range(HISTOGRAM_BINS + 1)]
    edges[0], edges[-1] = min(lo, lo_clip), max(hi, hi_clip)
    counts = [0] * HISTOGRAM_BINS
    for v in values:
        i = min(HISTOGRAM_BINS - 1, max(0, math.floor((v - lo_clip) / width)))
        counts[i] += 1
    return [
        HistogramBin(lo=edges[i], hi=edges[i + 1], count=counts[i]) for i in range(HISTOGRAM_BINS)
    ]


@router.get("/api/distribution")
def distribution(
    metric: str,
    build: CurrentBuild,
    within: Within = Within.UNIVERSE,
    sector: Sector | None = None,
) -> DistributionResponse:
    """Over the default universe (§2.3), or one sector of it with `within=sector&sector=…`."""
    registry = build.registry
    m = registry.get(metric)
    if m is None or not registry.is_live(metric):
        raise ApiError(404, ErrorCode.UNKNOWN_METRIC, f"No live metric {metric!r} in this build")
    if m.unit is Unit.BOOL:
        raise ApiError(
            422,
            ErrorCode.INVALID_REQUEST,
            f"{metric} is yes/no: it has no distribution",
            ["metric"],
        )
    if within is Within.SECTOR and sector is None:
        raise ApiError(422, ErrorCode.INVALID_REQUEST, "within=sector needs a sector", ["sector"])
    if within is Within.UNIVERSE and sector is not None:
        raise ApiError(
            422, ErrorCode.INVALID_REQUEST, "sector applies only with within=sector", ["sector"]
        )
    universe = Universe(sectors_include=[sector] if sector is not None else [])
    compiled = compile_screen(
        Screen(universe=universe, columns=[metric]), registry, load_screen_config()
    )
    rows = (
        build.cursor().execute(compiled.sql, used_params(compiled.sql, compiled.params)).fetchall()
    )
    position = compiled.row_columns.index(metric)
    values = sorted(float(r[position]) for r in rows if r[position] is not None)
    percentiles: dict[str, float] = {}
    bins: list[HistogramBin] = []
    if values:
        q = (
            build.cursor()
            .execute(
                "SELECT quantile_cont(x, $qs) FROM unnest($xs) AS t(x)",
                {"xs": values, "qs": [*PERCENTILES.values(), *HISTOGRAM_CLIP]},
            )
            .fetchone()
        )
        assert q is not None
        quantiles: list[float] = q[0]
        percentiles = dict(zip(PERCENTILES, quantiles, strict=False))
        bins = _bins(values, quantiles[-2], quantiles[-1])
    return DistributionResponse(
        build_id=build.build_id,
        metric=metric,
        within=within,
        sector=sector,
        count=len(values),
        null_count=len(rows) - len(values),
        bins=bins,
        percentiles=percentiles,
    )
