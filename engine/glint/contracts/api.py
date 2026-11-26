"""API request and response models for every §5.5 endpoint. FastAPI turns these into OpenAPI,
which generates the web's TypeScript types. Every response carries `build_id`.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from glint.contracts.enums import Exchange, FlagId, FlagSeverity, Kind, NoteCode, Sector
from glint.contracts.metrics import MetricDefinition
from glint.contracts.screen import Comparator, Screen, Within


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiResponse(_Model):
    build_id: str | None = Field(description="Build that served this response; null if none")


# --- Errors ------------------------------------------------------------------------------------


class ErrorCode(StrEnum):
    UNKNOWN_TICKER = "UNKNOWN_TICKER"  # 404
    UNKNOWN_PRESET = "UNKNOWN_PRESET"  # 404
    UNKNOWN_METRIC = "UNKNOWN_METRIC"  # 404
    INVALID_SCREEN = "INVALID_SCREEN"  # 422
    INVALID_REQUEST = "INVALID_REQUEST"  # 422 (non-screen query/body errors)
    NOT_FOUND = "NOT_FOUND"  # 404 (no such route)
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"  # 405
    NO_BUILD = "NO_BUILD"  # 503
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"  # 503
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"  # 501
    INTERNAL = "INTERNAL"  # 500


class ErrorResponse(ApiResponse):
    error: ErrorCode
    message: str
    path: list[str | int] | None = Field(default=None, description="Field path for INVALID_SCREEN")


# --- Shared pieces -----------------------------------------------------------------------------

CellValue = float | bool | str | None


class CellNote(_Model):
    code: NoteCode
    message: str


class AsOf(_Model):
    fundamentals: datetime | None = Field(description="SEC bulk file timestamp")
    prices: date | None = Field(description="Close date of the price data")


# --- GET /api/health ---------------------------------------------------------------------------


class HealthResponse(ApiResponse):
    status: Literal["ok"] = "ok"


# --- GET /api/meta -----------------------------------------------------------------------------


class UniverseCounts(_Model):
    companies: int
    by_kind: dict[str, int]
    by_exchange: dict[str, int]
    foreign_filers: int
    stale: int


class RunStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    WARN = "warn"
    FAILED = "failed"


class LastRun(_Model):
    run_id: str
    status: RunStatus
    started: datetime
    finished: datetime | None
    warnings: list[str]


class UniverseRules(_Model):
    """Universe rules from `config/thresholds.yaml`, so the UI states them without hard-coding
    a number (principle 8)."""

    stale_annual_report_months: int = Field(
        description="A company is stale (left out by default) when its latest annual report is "
        "older than this many months (`freshness.stale_annual_report_months`)"
    )


class MetaResponse(ApiResponse):
    synthetic: bool = Field(description="True for synthetic builds; the UI shows a banner")
    db_schema_version: int | None
    built_at: datetime | None
    as_of: AsOf
    universe_counts: UniverseCounts | None
    universe_rules: UniverseRules
    source_timestamps: dict[str, datetime | None]
    last_run: LastRun | None
    warnings: list[str]


# --- GET /api/metrics --------------------------------------------------------------------------


class MetricsResponse(ApiResponse):
    metrics: list[MetricDefinition]


# --- GET /api/sectors --------------------------------------------------------------------------


class SectorCount(_Model):
    sector: Sector
    count: int


class SectorsResponse(ApiResponse):
    sectors: list[SectorCount]


# --- GET /api/presets, /api/presets/{id} -------------------------------------------------------


class PresetKind(StrEnum):
    SCREEN = "screen"  # an ordinary screen: what it finds is worth a closer look
    RED_FLAGS = "red_flags"  # a risk screen, not a buy list: each match is a question


class PresetSummary(_Model):
    id: str
    name: str
    summary: str
    kind: PresetKind = Field(description="Set explicitly in every preset file")


class Preset(PresetSummary):
    """Also the shape of `config/presets/<id>.json` (with `id` = file stem)."""

    how_to_read: str
    misses: list[str] = Field(
        default_factory=list[str],
        description="What this screen misses: one short plain-language line per known blind "
        "spot; empty when the preset states none",
    )
    source: str
    screen: Screen


class PresetListResponse(ApiResponse):
    presets: list[PresetSummary]


class PresetResponse(ApiResponse):
    preset: Preset


# --- POST /api/screen (request body: Screen) ---------------------------------------------------


class FunnelStep(_Model):
    index: int = Field(description="0 = universe, then one step per top-level AND child")
    label: str
    filter_path: list[str | int] | None = Field(description="Path into the Screen; null = universe")
    remaining: int
    removed: int
    removed_missing: int = Field(description="Of `removed`, how many fell out for missing data")
    binding: bool = Field(description="The step with the largest `removed`")


class ResultRow(_Model):
    cik: str
    ticker: str
    name: str
    sector: Sector
    rank: int | None
    rank_score: float | None
    factor_contributions: dict[str, float | None]
    values: dict[str, CellValue] = Field(description="Requested columns, keyed by id")
    notes: dict[str, CellNote] = Field(description="Null reasons / info notes, keyed by id")


class NearMiss(_Model):
    cik: str
    ticker: str
    name: str
    sector: Sector
    failed_filter_path: list[str | int]
    failed_label: str
    metric: str
    cmp: Comparator
    value: CellValue
    threshold: CellValue | list[CellValue]
    distance: float | None = Field(description="|value − threshold| / |threshold|, or pct gap")
    note: CellNote | None = Field(
        default=None,
        description="Why the compared value (or the percentile/median it goes through) is null; "
        "null when it is present",
    )


class ScreenResponse(ApiResponse):
    as_of: AsOf
    universe_count: int
    funnel: list[FunnelStep]
    total: int
    results: list[ResultRow]
    near_misses: list[NearMiss]
    warnings: list[str]


# --- GET /api/distribution ---------------------------------------------------------------------


class HistogramBin(_Model):
    lo: float
    hi: float
    count: int


class DistributionResponse(ApiResponse):
    metric: str
    within: Within
    sector: Sector | None
    count: int
    null_count: int
    bins: list[HistogramBin]
    percentiles: dict[str, float] = Field(description="Keys p5, p25, p50, p75, p95")


# --- GET /api/snapshot/meta, /api/snapshot/values ----------------------------------------------


class SnapshotRows(_Model):
    """One entry per company, in the same order as every values/notes block."""

    cik: list[str]
    ticker: list[str]
    name: list[str]
    sector: list[Sector]
    exchange: list[Exchange | None]
    kind: list[Kind]
    is_foreign_filer: list[bool]
    is_stale: list[bool]
    has_facts: list[bool]


class SnapshotScreenConfig(_Model):
    """The screen engine's settings (`config/thresholds.yaml`), so a browser preview compares
    exactly as the server does."""

    float_tolerance: float
    small_peer_group_min: int


class SnapshotMeta(ApiResponse):
    """How to read `/api/snapshot/values` for the same build: the build's metric values as
    columns, for live screening in the browser (the server stays authoritative).

    The values body is `len(metrics)` blocks of `n` little-endian float64 (NaN = null; booleans
    as 1/0), then `len(metrics)` blocks of `n` uint8 reason codes: 0 = none, k = `note_codes[k-1]`
    (info codes such as DERIVED_INPUT can sit beside a value). Note messages stay server-side."""

    n: int
    metrics: list[str] = Field(description="Metric ids, in block order (registry order, live only)")
    note_codes: list[NoteCode]
    rows: SnapshotRows
    screen_config: SnapshotScreenConfig
    values_bytes: int = Field(description="n × len(metrics) × 8")
    notes_bytes: int = Field(description="n × len(metrics)")


# --- GET /api/search ---------------------------------------------------------------------------


class MatchType(StrEnum):
    EXACT = "exact"
    TICKER_PREFIX = "ticker_prefix"
    NAME_PREFIX = "name_prefix"
    FUZZY = "fuzzy"


class SearchHit(_Model):
    cik: str
    ticker: str
    name: str
    exchange: Exchange | None
    sector: Sector
    kind: Kind
    match: MatchType
    score: float


class SearchResponse(ApiResponse):
    query: str
    results: list[SearchHit]


# --- GET /api/companies/{ticker}, /history ------------------------------------------------------


class CompanyHeader(_Model):
    cik: str
    name: str
    tickers: list[str]
    primary_ticker: str | None
    exchange: Exchange | None
    sector: Sector
    sic: int | None
    sic_description: str | None
    kind: Kind
    is_foreign_filer: bool
    is_reit: bool
    has_facts: bool
    filer_category: str | None
    fiscal_year_end: str | None
    reporting_currency: str | None
    last_annual_date: date | None
    last_quarterly_date: date | None


class MetricValue(_Model):
    value: CellValue
    note: CellNote | None = None


class FlagOut(_Model):
    flag_id: FlagId
    severity: FlagSeverity = Field(
        description="caution: about the business; info: about reading the data "
        "(config/thresholds.yaml)"
    )
    question: str
    evidence: dict[str, Any]


class HistoryPoint(_Model):
    basis: Literal["fy", "ttm"]
    period_end: date
    value: float | None


class SourceFiling(_Model):
    accn: str
    form: str | None = Field(
        description="Form type (10-K, 10-Q, …); null when the build doesn't record it"
    )
    filed: date
    url: str


class FilterOutcome(_Model):
    filter_path: list[str | int]
    label: str
    passed: bool
    value: CellValue
    sector_percentile: float | None


class CompanyResponse(ApiResponse):
    company: CompanyHeader
    as_of: AsOf
    metrics: dict[str, MetricValue]
    flags: list[FlagOut]
    history: dict[str, list[HistoryPoint]] = Field(description="Sparkline series by metric id")
    sources: list[SourceFiling]
    why_passed: list[FilterOutcome] | None = Field(
        default=None, description="Present when ?screen= is supplied"
    )


class HistoryResponse(ApiResponse):
    ticker: str
    metric: str
    points: list[HistoryPoint]


# --- v1 (WT-12): saved screens and watchlists --------------------------------------------------


class SavedScreenIn(_Model):
    """v1 (WT-12)."""

    name: str
    screen: Screen


class SavedScreen(SavedScreenIn):
    """v1 (WT-12)."""

    id: str
    created: datetime
    updated: datetime


class SavedScreenListResponse(ApiResponse):
    """v1 (WT-12)."""

    screens: list[SavedScreen]


class ScreenRunDiff(_Model):
    """v1 (WT-12): "since last run: +4 entered, −2 left"."""

    screen_id: str
    build_id: str
    previous_build_id: str | None
    entered: list[str]
    left: list[str]
    changed_filters: dict[str, list[str]] = Field(
        description="ticker -> filter labels that changed state"
    )


class ScreenRunDiffResponse(ApiResponse):
    """v1 (WT-12)."""

    diff: ScreenRunDiff


class WatchlistItemIn(_Model):
    """v1 (WT-12)."""

    ticker: str
    note: str | None = None


class WatchlistItem(WatchlistItemIn):
    """v1 (WT-12)."""

    added_at: datetime


class Watchlist(_Model):
    """v1 (WT-12)."""

    id: str
    items: list[WatchlistItem]


class WatchlistResponse(ApiResponse):
    """v1 (WT-12)."""

    watchlist: Watchlist


# --- v2 (WT-13): natural-language screens ------------------------------------------------------


class NlScreenRequest(_Model):
    """v2 (WT-13)."""

    prompt: str = Field(min_length=1, max_length=1000)


class NlScreenResponse(ApiResponse):
    """v2 (WT-13). A draft for the user to confirm; never run automatically."""

    screen: Screen
    explanation: str
    model: str
