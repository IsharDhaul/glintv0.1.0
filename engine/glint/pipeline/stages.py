"""The refresh stages (SPEC §4.2), in run order.

Each stage wraps one module's public entry point; how a stage does its work lives in that module
(WT-01/02/03/06), never here. Stages write only to the build database and, under `raw.lock`, to
`GLINT_RAW_DIR`. Only `publish` touches `current.json`, and nothing here opens `user.duckdb`.

| stage            | module         | writes                                             |
|------------------|----------------|----------------------------------------------------|
| download_sec     | ingest/sec     | raw sec/<date>/ (conditional GET: 304 = skipped)   |
| extract_facts    | ingest/sec     | raw sec/<date>/facts_raw (skipped when stamped)    |
| companies        | universe       | raw companies.parquet (when inputs changed), build |
| financials       | financials     | build `financials` (always recomputed)             |
| prices           | ingest/prices  | raw prices/ (missing dates only)                   |
| price_stats      | ingest/prices  | build `price_stats` (bars via PriceStore.read_bars)|
| metrics          | metrics, flags | build `metrics_snapshot`, notes, history, `flags`; |
|                  |                | raw snapshots/date=<d>/ (WT-06's `MetricsStage`)   |
| publish          | pipeline       | build_meta, then current.json (atomic swap)        |
"""

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl

from glint.contracts.db import (
    BUILD_TABLES,
    DB_SCHEMA_VERSION,
    PRICE_STATS,
)
from glint.contracts.enums import DEFAULT_EXCHANGES, Kind
from glint.contracts.pipeline import BuildContext, StageResult, StageStatus
from glint.core.errors import GlintError
from glint.core.filelock import raw_lock
from glint.core.http import SecGateway
from glint.core.log import get_logger
from glint.core.settings import REPO_ROOT, Settings
from glint.financials.build import build_financials
from glint.financials.concepts import load_concepts
from glint.financials.coverage import Group
from glint.ingest.prices.backfill import ingest_dates
from glint.ingest.prices.coverage import load_universe
from glint.ingest.prices.factory import make_provider
from glint.ingest.prices.provider import PriceProvider
from glint.ingest.prices.splits import adjust_for_splits
from glint.ingest.prices.stats import DEFAULT_WINDOWS, price_stats
from glint.ingest.prices.store import PriceStore
from glint.ingest.sec.download import (
    COMPANYFACTS,
    MANIFEST,
    SUBMISSIONS,
    TICKERS,
    download_bulk,
    sha256_file,
)  # fmt: skip
from glint.ingest.sec.download import latest_folder as latest_sec_folder
from glint.ingest.sec.extract import FACTS_DIR, STAMP, load_whitelist, whitelist_hash
from glint.ingest.sec.run import extract_folder
from glint.metrics.io import insert_frame as append_frame
from glint.metrics.stage import MetricsStage
from glint.universe.build import COMPANIES_FILE, CONTRACT_COLUMNS, write_companies
from glint.universe.predecessors import load_predecessors

COMPANIES_STAMP = "_companies.pipeline.json"
"""Pipeline-owned stamp next to companies.parquet: the inputs it was built from."""
MISSING_KEY = "missing_submissions"  # also in the stamp, so a reuse still warns

COMPANIES_INPUT_CONFIGS = (
    "sectors.yaml",
    "sector_overrides.yaml",
    "share_classes.yaml",
    "cik_predecessors.yaml",
    "concepts.yaml",
    "thresholds.yaml",  # late-filer / FY-change rules (universe/submissions.py)
)
UNIVERSE_SOURCE = REPO_ROOT / "engine" / "glint" / "universe"

log = get_logger(__name__)

RAW_LOCK_WAIT_S = 600.0
"""How long a stage waits for `raw.lock` (another worktree's ingest) before failing the run."""


class StageFailedError(GlintError):
    code = "STAGE_FAILED"


@dataclass
class Outcome:
    """What a stage reports back; the runner adds the stage name and timing."""

    status: StageStatus = StageStatus.OK
    counts: dict[str, int] = field(default_factory=dict[str, int])
    warnings: list[str] = field(default_factory=list[str])
    note: str | None = None  # one line for the report ("reused companies.parquet", skip reason)


class BaseStage:
    """A `contracts.pipeline.Stage`. Subclasses set `name`, `deps` and implement `execute`."""

    name: str = ""
    deps: tuple[str, ...] = ()
    writes_build: bool = False  # True: needs the build database

    def __init__(self) -> None:
        self.note: str | None = None

    def skip_reason(self, ctx: BuildContext) -> str | None:
        """Why the stage won't run, decided before running it (also shown by --dry-run)."""
        return None

    def execute(self, ctx: BuildContext) -> Outcome:
        raise NotImplementedError

    def run(self, ctx: BuildContext) -> StageResult:
        out = self.execute(ctx)
        self.note = out.note
        return StageResult(
            stage=self.name,
            status=out.status,
            counts=out.counts,
            warnings=out.warnings,
            duration_s=0,
        )


# --- helpers ---------------------------------------------------------------------------------


def sec_folder(ctx: BuildContext) -> Path:
    """The SEC download folder this build reads: `ctx.raw_date`, else the newest complete one."""
    sec_raw = ctx.paths.sec_raw
    if ctx.raw_date is not None:
        folder = sec_raw / ctx.raw_date.isoformat()
        if not (folder / MANIFEST).exists():
            raise StageFailedError(f"{folder} has no {MANIFEST}: the download didn't finish")
        return folder
    folder = latest_sec_folder(sec_raw)
    if folder is None:
        raise StageFailedError(
            f"no completed SEC download under {sec_raw}: run `glint refresh` without "
            "--no-download (or `glint ingest sec`) once"
        )
    ctx.raw_date = date.fromisoformat(folder.name)
    return folder


def manifest(folder: Path) -> dict[str, Any]:
    return orjson.loads((folder / MANIFEST).read_bytes())


def connect_build(ctx: BuildContext) -> duckdb.DuckDBPyConnection:
    """The only way stages open a database: the build file, read-write."""
    if ctx.build_db.resolve() == ctx.paths.user_db.resolve():
        raise StageFailedError("refusing to open user.duckdb from the pipeline")
    return duckdb.connect(str(ctx.build_db))


def insert_frame(con: duckdb.DuckDBPyConnection, table: str, frame: pl.DataFrame) -> None:
    """Replace `table`'s rows with `frame` (via parquet: DuckDB reads polars only via pyarrow)."""
    con.execute(f"DELETE FROM {table}")
    append_frame(con, table, frame)


def init_build_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Every contract table except `metrics_snapshot` (its DDL comes from the metrics registry)."""
    for ddl in BUILD_TABLES.values():
        con.execute(ddl)


def _sha_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    return h.hexdigest()


def companies_inputs(folder: Path) -> dict[str, str]:
    """What companies.parquet depends on: the SEC files, config, and the universe code."""
    files = manifest(folder)["files"]
    return {
        "submissions_sha256": files[SUBMISSIONS.name]["sha256"],
        "tickers_sha256": files[TICKERS.name]["sha256"],
        "companyfacts_sha256": files[COMPANYFACTS.name]["sha256"],
        "config": _sha_files([REPO_ROOT / "config" / n for n in COMPANIES_INPUT_CONFIGS]),
        "code": _sha_files(sorted(UNIVERSE_SOURCE.glob("*.py"))),
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return orjson.loads(path.read_bytes())
    except (FileNotFoundError, orjson.JSONDecodeError):
        return None


def extract_is_current(folder: Path) -> bool:
    stamp = _read_json(folder / FACTS_DIR / STAMP)
    if stamp is None:
        return False
    wanted = {
        "source_sha256": manifest(folder)["files"][COMPANYFACTS.name]["sha256"],
        "whitelist": whitelist_hash(load_whitelist()),
    }
    return all(stamp.get(k) == v for k, v in wanted.items())


def companies_are_current(folder: Path) -> bool:
    """The stamp matches today's inputs *and* the parquet is the one this pipeline wrote (another
    checkout's `glint ingest sec` may have rewritten it with different code)."""
    stamp = _read_json(folder / COMPANIES_STAMP)
    if stamp is None or not (folder / COMPANIES_FILE).exists():
        return False
    parquet = stamp.pop("parquet_sha256", None)
    stamp.pop(MISSING_KEY, None)
    return stamp == companies_inputs(folder) and parquet == sha256_file(folder / COMPANIES_FILE)


def check_companies_unchanged(folder: Path) -> None:
    """Financials re-reads companies.parquet: fail if it changed since the companies stage."""
    stamp = _read_json(folder / COMPANIES_STAMP) or {}
    if stamp.get("parquet_sha256") != sha256_file(folder / COMPANIES_FILE):
        raise StageFailedError(
            f"{folder.name}/{COMPANIES_FILE} isn't the one the companies stage loaded (another "
            "process rewrote it): rerun with --from companies"
        )


# --- stages ----------------------------------------------------------------------------------

GatewayFactory = Callable[[Settings], SecGateway]
ProviderFactory = Callable[[Settings, list[str]], PriceProvider]


class DownloadSec(BaseStage):
    """companyfacts.zip, submissions.zip, company_tickers_exchange.json (conditional GET)."""

    name = "download_sec"
    deps = ()

    def __init__(self, gateway: GatewayFactory = SecGateway) -> None:
        super().__init__()
        self.gateway = gateway

    def skip_reason(self, ctx: BuildContext) -> str | None:
        return (
            "--no-download: using the newest SEC download on disk"
            if ctx.options.no_download
            else None
        )

    def execute(self, ctx: BuildContext) -> Outcome:
        async def go() -> Any:
            async with self.gateway(ctx.settings) as gw:
                return await download_bulk(gw, ctx.paths.sec_raw)

        with raw_lock(ctx.paths.raw_dir, timeout_s=RAW_LOCK_WAIT_S):
            report = asyncio.run(go())
        ctx.raw_date = date.fromisoformat(report.folder.name)
        changed = [f for f in report.files if f.changed]
        counts = {
            "files_changed": len(changed),
            "bytes_downloaded": sum(f.bytes for f in changed),
        }
        if report.unchanged:
            return Outcome(
                StageStatus.SKIPPED, counts,
                note="SEC says nothing changed since the last download (HTTP 304 on every file)",
            )  # fmt: skip
        return Outcome(counts=counts, note="changed: " + ", ".join(f.name for f in changed))


class ExtractFacts(BaseStage):
    """facts_raw (whitelisted tags) from companyfacts.zip; reused when already stamped."""

    name = "extract_facts"
    deps = ("download_sec",)

    def skip_reason(self, ctx: BuildContext) -> str | None:
        folder = sec_folder(ctx)
        if extract_is_current(folder):
            return f"facts_raw in {folder.name} already extracted from this companyfacts.zip"
        return None

    def execute(self, ctx: BuildContext) -> Outcome:
        folder = sec_folder(ctx)
        with raw_lock(ctx.paths.raw_dir, timeout_s=RAW_LOCK_WAIT_S):
            stats = extract_folder(folder)
        counts = {
            "companies": stats.companies,
            "companies_without_kept_facts": stats.companies_without_kept_facts,
            "facts_kept": stats.facts_kept,
        }
        if stats.reused_from:
            return Outcome(StageStatus.SKIPPED, counts, note=f"reused from {stats.reused_from}")
        if stats.skipped:
            return Outcome(StageStatus.SKIPPED, counts, note="already extracted")
        return Outcome(counts=counts, note=f"extracted in {stats.seconds:,.0f} s")


class Companies(BaseStage):
    """companies.parquet (rebuilt only when its inputs changed), loaded into the build."""

    name = "companies"
    deps = ("extract_facts",)
    writes_build = True

    def execute(self, ctx: BuildContext) -> Outcome:
        folder = sec_folder(ctx)
        if companies_are_current(folder):
            note = f"reused {folder.name}/{COMPANIES_FILE} (same SEC files, config and code)"
            missing = int((_read_json(folder / COMPANIES_STAMP) or {}).get(MISSING_KEY, 0))
        else:
            with raw_lock(ctx.paths.raw_dir, timeout_s=RAW_LOCK_WAIT_S):
                report = write_companies(folder, as_of=date.fromisoformat(folder.name))
                missing = len(report.missing_submissions)
                stamp = {
                    **companies_inputs(folder),
                    "parquet_sha256": sha256_file(folder / COMPANIES_FILE),
                    MISSING_KEY: missing,
                }
                (folder / COMPANIES_STAMP).write_bytes(
                    orjson.dumps(stamp, option=orjson.OPT_INDENT_2)
                )
            note = f"rebuilt {COMPANIES_FILE} in {report.seconds:,.0f} s"
        warnings: list[str] = []
        if missing:
            warnings.append(
                f"{missing:,} CIKs have no submissions record (kind and foreign status unverified)"
            )
        df = pl.read_parquet(folder / COMPANIES_FILE).select(CONTRACT_COLUMNS)
        with connect_build(ctx) as con:
            insert_frame(con, "companies", df)
        return Outcome(counts=universe_counts(df), warnings=warnings, note=note)


def universe_counts(df: pl.DataFrame) -> dict[str, int]:
    """Universe size and what the default universe (§2.3) leaves out, by first reason."""
    on_exchange = pl.col("exchange").is_in([e.value for e in DEFAULT_EXCHANGES])
    operating = pl.col("kind") == Kind.OPERATING.value
    default = on_exchange & operating & pl.col("has_facts")
    return {
        "companies": df.height,
        "default_universe": df.filter(default).height,
        "excluded_not_on_default_exchange": df.filter(~on_exchange.fill_null(False)).height,
        "excluded_not_operating": df.filter(on_exchange & ~operating).height,
        "excluded_no_facts": df.filter(on_exchange & operating & ~pl.col("has_facts")).height,
        "default_foreign_filers": df.filter(default & pl.col("is_foreign_filer")).height,
    }


def _group_key(group: Group) -> str:
    return group.name.lower()


class Financials(BaseStage):
    """FY / Q / TTM / MRQ series per line item from facts_raw. Always recomputed."""

    name = "financials"
    deps = ("companies",)
    writes_build = True

    def execute(self, ctx: BuildContext) -> Outcome:
        concepts = load_concepts()
        # Held while reading the folder: another worktree's publish prunes old SEC folders
        # under raw.lock, and a partial run may be reading one of them.
        with (
            raw_lock(ctx.paths.raw_dir, timeout_s=RAW_LOCK_WAIT_S),
            connect_build(ctx) as con,
        ):
            folder = sec_folder(ctx)
            check_companies_unchanged(folder)
            companies = pl.read_parquet(folder / COMPANIES_FILE)
            con.execute("DELETE FROM financials")
            report = build_financials(
                folder / FACTS_DIR, companies, load_predecessors(), concepts, con=con
            )
        counts = {
            "companies": report.companies,
            "rows": report.rows,
            "normalize_warnings": report.warnings,
        }
        # Coverage (TTM flows / MRQ instants) as integer counts, so it's stored in
        # pipeline_runs and the next build's report can compare with it.
        cov = report.coverage_ttm
        for group in Group:
            g = _group_key(group)
            counts[f"coverage.{g}.companies"] = cov.companies[group]
            for item in concepts.core:
                counts[f"coverage.{g}.{item.value}"] = (
                    cov.present[item][group] if item in cov.present else 0
                )
        return Outcome(counts=counts, note=f"{report.rows:,} rows, {report.companies:,} companies")


def _make_provider(settings: Settings, tickers: list[str]) -> PriceProvider:
    return make_provider(settings, tickers=tickers)


class Prices(BaseStage):
    """Grouped-daily bars for every weekday after the newest on disk (missing dates only).

    A provider failure is a warning, not an abort: price-tier metrics go null and the
    fundamentals build carries on (§4.1).
    """

    name = "prices"
    deps = ()

    def __init__(self, provider: ProviderFactory | None = None) -> None:
        super().__init__()
        self.provider: ProviderFactory = provider or _make_provider

    def skip_reason(self, ctx: BuildContext) -> str | None:
        if ctx.options.no_download:
            return "--no-download: using the bars on disk"
        if ctx.options.skip_prices:
            return "--skip-prices: using the bars on disk"
        return None

    def execute(self, ctx: BuildContext) -> Outcome:
        store = PriceStore(ctx.paths)
        universe = load_universe(ctx.paths)
        tickers = [u.ticker for u in universe[0]] if universe else []
        try:
            provider = self.provider(ctx.settings, tickers)
            per_call = (
                60 / ctx.settings.massive_calls_per_min if provider.name == "massive" else 0.0
            )
            result = ingest_dates(store, provider, seconds_per_call=per_call)
        except Exception as exc:  # any provider failure, not just ours: §4.1 says warn
            log.exception("price_fetch_failed")
            msg = exc.message if isinstance(exc, GlintError) else f"{type(exc).__name__}: {exc}"
            return Outcome(
                StageStatus.WARN,
                warnings=[f"price fetch failed, using bars on disk up to "
                          f"{store.latest_date()}: {msg}"],
            )  # fmt: skip
        counts = {
            "dates_fetched": len(result.fetched),
            "bars": result.rows,
            "holidays": len(result.holidays),
            "splits_new": result.splits_new,
        }
        warnings: list[str] = []
        if provider.is_fallback:
            warnings.append("prices from the yfinance FALLBACK (MASSIVE_API_KEY not set)")
        if result.not_yet_available:
            warnings.append(
                "no bars yet for " + ", ".join(d.isoformat() for d in result.not_yet_available)
            )
        status = StageStatus.WARN if warnings else StageStatus.OK
        if not result.fetched and not warnings:
            status = StageStatus.SKIPPED
        note = f"newest date on disk {store.latest_date()} (provider {provider.name})"
        return Outcome(status, counts, warnings, note)


class PriceStats(BaseStage):
    """Returns, 52w high, volatility, ADV per ticker, from bars read via `PriceStore.read_bars`
    (which follows config/ticker_changes.yaml, so a renamed ticker's history is continuous)."""

    name = "price_stats"
    deps = ("prices",)
    writes_build = True

    def execute(self, ctx: BuildContext) -> Outcome:
        store = PriceStore(ctx.paths)
        dates = store.dates_on_disk()
        if not dates:
            with connect_build(ctx) as con:
                con.execute(PRICE_STATS)
                con.execute("DELETE FROM price_stats")
            return Outcome(
                StageStatus.WARN,
                warnings=["no price bars on disk: price-tier metrics will be null"],
            )
        as_of = dates[-1]
        need = max(DEFAULT_WINDOWS.required().values())
        start = dates[-need:][0]
        bars = store.read_bars(start=start, end=as_of)
        adjusted = adjust_for_splits(bars, store.load_splits(), as_of)
        result = price_stats(adjusted, as_of)
        with connect_build(ctx) as con:
            insert_frame(con, "price_stats", result.stats)
        stale = result.stats.filter(pl.col("as_of") < as_of).height
        counts = {
            "tickers": result.stats.height,
            "sessions_on_disk": len(dates),
            "tickers_without_bar_on_as_of": stale,
            "notes": result.notes.height,
        }
        warnings: list[str] = []
        if len(dates) < need:
            warnings.append(
                f"only {len(dates)} sessions on disk: 12-month stats need {need} "
                f"(run `glint ingest prices --backfill {need}`)"
            )
        status = StageStatus.WARN if warnings else StageStatus.OK
        return Outcome(status, counts, warnings, note=f"prices as of {as_of}")


BUILD_ID_FORMAT = "%Y%m%dT%H%M%SZ"


def _changed_at(entry: dict[str, Any]) -> str:
    """A manifest entry's Last-Modified (HTTP date) or, without one, its fetch time, as ISO UTC."""
    lm = entry.get("last_modified")
    if lm:
        return datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT").isoformat() + "+00:00"  # noqa: DTZ007
    return str(entry["fetched_at"])


def as_of_fundamentals(folder: Path) -> str:
    """When SEC last rebuilt companyfacts.zip, as an ISO UTC timestamp."""
    return _changed_at(manifest(folder)["files"][COMPANYFACTS.name])


def write_build_meta(ctx: BuildContext) -> int:
    """build_meta for this build: schema version, id, and the as-of dates of its sources."""
    folder = sec_folder(ctx)
    with connect_build(ctx) as con:
        row = con.execute("SELECT max(as_of) FROM price_stats").fetchone()
    # The bars this build's price_stats came from, not whatever is newest on disk now.
    prices_as_of = row[0] if row and row[0] is not None else None
    meta = {
        "db_schema_version": str(DB_SCHEMA_VERSION),
        "build_id": ctx.build_id,
        "synthetic": "false",
        "created_at": datetime.strptime(ctx.build_id, BUILD_ID_FORMAT).isoformat()  # noqa: DTZ007
        + "+00:00",
        "as_of_fundamentals": as_of_fundamentals(folder),
    }
    if prices_as_of is not None:
        meta["as_of_prices"] = prices_as_of.isoformat()[:10]
    with connect_build(ctx) as con:
        con.execute("DELETE FROM build_meta")
        con.executemany("INSERT INTO build_meta VALUES (?, ?)", sorted(meta.items()))
    return len(meta)


class Metrics(BaseStage):
    """WT-06's `MetricsStage`: metrics_snapshot, metric_notes, metric_history and flags, then the
    point-in-time archive in GLINT_RAW_DIR/snapshots/ (under raw.lock).

    It reads its as-of dates from build_meta, so they're written first (publish rewrites them).
    """

    name = "metrics"
    deps = ("financials", "price_stats")
    writes_build = True

    def __init__(self, inner: MetricsStage | None = None) -> None:
        super().__init__()
        self.inner = inner or MetricsStage()

    def execute(self, ctx: BuildContext) -> Outcome:
        write_build_meta(ctx)
        result = self.inner.run(ctx)
        if result.status is StageStatus.FAILED:
            raise StageFailedError(result.error or "metrics failed (no message)")
        n = result.counts.get("metrics_snapshot", 0)
        flags = result.counts.get("flags_raised", 0)
        return Outcome(
            result.status, dict(result.counts), list(result.warnings),
            note=f"{n:,} companies, {flags:,} flags raised; snapshot archived",
        )  # fmt: skip


class Publish(BaseStage):
    """Record build_meta. The runner swaps current.json once this succeeds."""

    name = "publish"
    deps = ("metrics",)
    writes_build = True

    def execute(self, ctx: BuildContext) -> Outcome:
        n = write_build_meta(ctx)
        with connect_build(ctx) as con:
            con.execute("CHECKPOINT")
        return Outcome(counts={"build_meta_keys": n})


SEC_FOLDER_KEY = "sec.folder"
"""In `pipeline_runs.sources`: the SEC download folder the build was made from."""


def source_timestamps(ctx: BuildContext) -> dict[str, str]:
    """For pipeline_runs: when each source was last changed / fetched. Every value is ISO 8601
    (the API reads them as datetimes; `sec.folder` is the download folder's date)."""
    out: dict[str, str] = {}
    try:
        folder = sec_folder(ctx)
    except StageFailedError:
        folder = None
    if folder is not None:
        out[SEC_FOLDER_KEY] = folder.name
        for name, entry in manifest(folder)["files"].items():
            out[f"sec.{name}"] = _changed_at(entry)
    latest = PriceStore(ctx.paths).latest_date()
    if latest is not None:
        out["prices.latest_date"] = latest.isoformat()
    return out


def default_stages(
    gateway: GatewayFactory = SecGateway, provider: ProviderFactory | None = None
) -> list[BaseStage]:
    return [
        DownloadSec(gateway),
        ExtractFacts(),
        Companies(),
        Financials(),
        Prices(provider),
        PriceStats(),
        Metrics(),
        Publish(),
    ]


STAGE_ORDER: tuple[str, ...] = tuple(s.name for s in default_stages())


def validate_order(stages: list[BaseStage]) -> None:
    """Every dependency names an earlier stage."""
    seen: set[str] = set()
    for s in stages:
        missing = [d for d in s.deps if d not in seen]
        if missing:
            raise GlintError(f"stage {s.name} depends on {missing}, which don't run before it")
        seen.add(s.name)
