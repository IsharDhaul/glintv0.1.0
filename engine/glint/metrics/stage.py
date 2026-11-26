"""The metrics stage (WT-06 steps 8–9): build tables in, metrics_snapshot + metric_notes +
metric_history + flags out, then the point-in-time archive.

`run_metrics` is pure (frames in, frames out). `MetricsStage` is the pipeline wrapper WT-07 runs:
it reads `companies`, `financials` and `price_stats` from the build, splits from the price store,
WT-01's `last_annual_form` from companies.parquet, and writes back into the same build.
"""

import shutil
import time
import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from glint.contracts.db import FLAGS, METRIC_HISTORY, METRIC_NOTES, metrics_snapshot_ddl
from glint.contracts.enums import Unit
from glint.contracts.metrics import MetricDefinition, MetricRegistry, load_registry
from glint.contracts.pipeline import BuildContext, StageResult, StageStatus
from glint.core.errors import GlintError
from glint.core.filelock import LockTimeoutError, raw_lock
from glint.core.log import get_logger, log_event
from glint.core.paths import Paths
from glint.financials.concepts import ConceptMap, load_concepts
from glint.flags.engine import RECENT_ADV, evaluate_flags, load_rules, recent_dollar_volume
from glint.ingest.prices.store import PriceStore
from glint.ingest.prices.ticker_changes import load_ticker_changes
from glint.metrics.compute import AFTER_FLAGS, compute_metrics, prepare
from glint.metrics.defs.composites import piotroski_parts
from glint.metrics.history import build_history
from glint.metrics.io import insert_frame, read_sql
from glint.metrics.params import Params, load_params
from glint.metrics.share_classes import (
    LISTED_COLUMN,
    ShareClassEntry,
    load_share_classes,
    merged_share_classes,
)
from glint.universe.cli import load_companies

log = get_logger(__name__)

ARCHIVE_LOCK_WAIT_S = 600.0
"""How long the archive waits for `raw.lock`. Same as the pipeline's `RAW_LOCK_WAIT_S` (a test
pins them together; importing it here would be circular: pipeline.stages imports this module)."""


@dataclass(frozen=True)
class MetricsOutput:
    frame: pl.DataFrame  # the full working frame (inputs + every metric + codes), for explain/audit
    snapshot: pl.DataFrame
    notes: pl.DataFrame
    history: pl.DataFrame
    flags: pl.DataFrame
    primary: pl.DataFrame  # cik, primary_ticker (final)


def run_metrics(
    companies: pl.DataFrame,
    fin: pl.DataFrame,
    stats: pl.DataFrame,
    splits: pl.DataFrame | None,
    *,
    as_of_fundamentals: date,
    as_of_prices: date | None,
    share_classes: dict[str, ShareClassEntry],
    registry: MetricRegistry,
    params: Params,
    concepts: ConceptMap,
    flag_cfg: dict[str, Any],
    recent_adv: pl.DataFrame | None = None,
) -> MetricsOutput:
    # cover-listed classes (companies.parquet) under the yaml's entries; the column stops here
    share_classes = merged_share_classes(
        share_classes, companies, stats,
        as_of_prices=as_of_prices, stale_days=params.price_stale_days,
    )  # fmt: skip
    companies = companies.drop(LISTED_COLUMN, strict=False)
    frame = prepare(
        companies, fin, stats, splits, concepts,
        as_of_fundamentals=as_of_fundamentals, as_of_prices=as_of_prices,
        share_classes=share_classes, split_confirm_tolerance=params.split_confirm_tolerance,
    )  # fmt: skip
    frame = compute_metrics(frame, registry, params)
    if recent_adv is not None:  # `market_cap_implausible`'s volume, on the final primary ticker
        frame = frame.join(
            recent_adv.select(pl.col("ticker").alias("primary_ticker"), RECENT_ADV),
            on="primary_ticker",
            how="left",
        )
    flags = evaluate_flags(frame, fin, flag_cfg)
    counts = flags.group_by("cik").agg(pl.len().cast(pl.Int64).alias("n_flags"))
    frame = frame.join(counts, on="cik", how="left").with_columns(pl.col("n_flags").fill_null(0))
    frame = compute_metrics(frame, registry, params, only=AFTER_FLAGS)
    live = registry.live()
    final = companies.drop("primary_ticker").join(
        frame.select("cik", "primary_ticker"), on="cik", how="left"
    )  # the primary ticker `prepare` settled on, for its splits
    history = build_history(
        final, fin, params, window=concepts.params.year_ago_window_days, registry=registry,
        splits=splits,
    )  # fmt: skip
    return MetricsOutput(
        frame=frame,
        snapshot=snapshot_frame(frame, live, params),
        notes=notes_frame(frame, live),
        history=_with_piotroski_parts(history, frame, params),
        flags=flags,
        primary=frame.select("cik", "primary_ticker"),
    )


def snapshot_frame(frame: pl.DataFrame, live: list[MetricDefinition], p: Params) -> pl.DataFrame:
    """metrics_snapshot rows: fixed columns + one per live metric (§4.7)."""
    stale = pl.col("last_annual_date") < pl.col("as_of_fundamentals").dt.offset_by(
        f"-{p.stale_annual_report_months}mo"
    )
    cols = [
        "cik",
        pl.max_horizontal("ttm_end", "mrq_end").alias("as_of_fundamentals"),
        pl.col("price_as_of").alias("as_of_prices"),
        pl.col("primary_ticker").alias("ticker"),
        "name",
        "sector",
        "kind",
        "exchange",
        "is_foreign_filer",
        stale.fill_null(False).alias("is_stale"),
        "has_facts",
    ]
    metric_cols = [
        pl.col(m.id).cast(pl.Boolean if m.unit is Unit.BOOL else pl.Float64) for m in live
    ]
    return frame.select(*cols, *metric_cols).sort("cik")


def notes_frame(frame: pl.DataFrame, live: list[MetricDefinition]) -> pl.DataFrame:
    """metric_notes rows: one per cell that has a code (every null, and annotated values)."""
    parts = [
        frame.select(
            "cik",
            pl.lit(m.id).alias("metric_id"),
            pl.col(f"{m.id}__code").alias("code"),
            pl.col(f"{m.id}__msg").alias("message"),
        ).filter(pl.col("code").is_not_null())
        for m in live
    ]
    if not parts:
        return pl.DataFrame(schema={"cik": pl.String, "metric_id": pl.String, "code": pl.String,
                                    "message": pl.String})  # fmt: skip
    return pl.concat(parts).sort("cik", "metric_id")


def _with_piotroski_parts(history: pl.DataFrame, frame: pl.DataFrame, p: Params) -> pl.DataFrame:
    """The 9 Piotroski tests as `piotroski_f.<test>` points at the latest FY end (drill-down)."""
    parts = frame.select("cik", "fy0_end", "piotroski_f", **piotroski_parts(p)).filter(
        pl.col("piotroski_f").is_not_null()
    )
    rows = parts.unpivot(
        index=["cik", "fy0_end"],
        on=list(piotroski_parts(p)),
        variable_name="test",
        value_name="value",
    ).select(
        "cik",
        pl.concat_str(pl.lit("piotroski_f."), pl.col("test")).alias("metric_id"),
        pl.lit("fy").alias("basis"),
        pl.col("fy0_end").alias("period_end"),
        "value",
    )
    return pl.concat([history, rows]).sort("cik", "metric_id", "basis", "period_end")


def write_metrics(
    con: duckdb.DuckDBPyConnection, out: MetricsOutput, live: list[MetricDefinition]
) -> dict[str, int]:
    """(Re)create the metric tables in a build and set the final primary tickers."""
    for table in ("metrics_snapshot", "metric_notes", "metric_history", "flags"):
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(metrics_snapshot_ddl(live))
    for ddl in (METRIC_NOTES, METRIC_HISTORY, FLAGS):
        con.execute(ddl)
    counts = {
        "metrics_snapshot": insert_frame(con, "metrics_snapshot", out.snapshot),
        "metric_notes": insert_frame(con, "metric_notes", out.notes),
        "metric_history": insert_frame(con, "metric_history", out.history),
        "flags": insert_frame(con, "flags", out.flags),
    }
    con.execute("CREATE TEMP TABLE _primary (cik VARCHAR, primary_ticker VARCHAR)")
    insert_frame(con, "_primary", out.primary)
    con.execute(
        "UPDATE companies SET primary_ticker = p.primary_ticker FROM _primary p "
        "WHERE companies.cik = p.cik"
    )
    con.execute("DROP TABLE _primary")
    return counts


def archive(
    out: MetricsOutput, paths: Paths, as_of: date, *, lock_wait_s: float = ARCHIVE_LOCK_WAIT_S
) -> Path:
    """Write the snapshot to GLINT_RAW_DIR/snapshots/date=<as_of>/ (point-in-time history).
    Built in a temp dir and swapped in under raw.lock (waiting up to `lock_wait_s` for another
    worktree's ingest to finish); a rerun for the same date replaces it."""
    final = paths.snapshots / f"date={as_of.isoformat()}"
    tmp = final.with_name(final.name + ".tmp")
    lock = ExitStack()
    try:
        lock.enter_context(raw_lock(paths.raw_dir, timeout_s=lock_wait_s))
    except LockTimeoutError as exc:
        raise LockTimeoutError(
            f"metrics archive waited {lock_wait_s:g} s for {paths.raw_lock} and gave up: "
            "another process (an ingest in another worktree?) still holds it. Nothing was "
            "archived; rerun `glint refresh` once the other process is done."
        ) from exc
    with lock:
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        tables = {
            "metrics_snapshot": out.snapshot,
            "metric_notes": out.notes,
            "metric_history": out.history,
            "flags": out.flags,
        }
        for name, frame in tables.items():
            frame.write_parquet(tmp / f"{name}.parquet")
        if final.exists():
            shutil.rmtree(final)
        tmp.rename(final)
    return final


def load_side_inputs(
    con: duckdb.DuckDBPyConnection, paths: Paths, companies: pl.DataFrame
) -> dict[str, Any]:
    """What the build tables don't hold: WT-01's `last_annual_form` and `listed_classes`
    (companies.parquet; folders built before the column existed give none), splits
    and the recent dollar volume (`market_cap_implausible`) from the price store, and the
    build's as-of dates (build_meta)."""
    raw_companies, _ = load_companies(paths.sec_raw)
    extra = [c for c in ("last_annual_form", LISTED_COLUMN) if c in raw_companies.columns]
    companies = companies.join(raw_companies.select("cik", *extra), on="cik", how="left")
    meta = dict(con.execute("SELECT key, value FROM build_meta").fetchall())
    as_of_prices = meta.get("as_of_prices")
    prices_date = date.fromisoformat(as_of_prices[:10]) if as_of_prices else None
    store = PriceStore(paths, load_ticker_changes())
    return {
        "companies": companies,
        "splits": store.load_splits(),
        "as_of_fundamentals": date.fromisoformat(meta["as_of_fundamentals"][:10]),
        "as_of_prices": prices_date,
        "recent_adv": load_recent_adv(store, prices_date),
    }


def load_recent_adv(store: PriceStore, as_of_prices: date | None) -> pl.DataFrame:
    """`recent_dollar_volume` over the last `adv_sessions` market sessions on disk up to the
    build's price date. With fewer sessions on disk than that, an empty frame: the flag can't
    fire."""
    n = int(load_rules()["market_cap_implausible"]["adv_sessions"])
    days = [d for d in store.dates_on_disk() if as_of_prices is not None and d <= as_of_prices]
    if len(days) < n:
        return recent_dollar_volume(pl.DataFrame(), [])
    sessions = days[-n:]
    return recent_dollar_volume(store.read_bars(start=sessions[0], end=sessions[-1]), sessions)


def load_inputs(con: duckdb.DuckDBPyConnection, paths: Paths) -> dict[str, Any]:
    """Build tables + raw side inputs for `run_metrics`."""
    companies = read_sql(con, "SELECT * FROM companies ORDER BY cik")
    return {
        **load_side_inputs(con, paths, companies),
        "fin": read_sql(con, "SELECT * FROM financials ORDER BY cik, line_item, basis, period_end"),
        "stats": read_sql(con, "SELECT * FROM price_stats ORDER BY ticker"),
    }


def build(
    db: Path, paths: Paths, *, archive_snapshot: bool = True
) -> tuple[MetricsOutput, dict[str, int]]:
    registry = load_registry()
    with duckdb.connect(str(db)) as con:
        inputs = load_inputs(con, paths)
        out = run_metrics(
            **inputs,
            share_classes=load_share_classes(),
            registry=registry,
            params=load_params(),
            concepts=load_concepts(),
            flag_cfg=load_rules(),
        )
        counts = write_metrics(con, out, registry.live())
    if archive_snapshot:
        archive(out, paths, inputs["as_of_fundamentals"])
    return out, counts


def where(exc: BaseException) -> str:
    """One line: the error and the innermost Glint frame it came through (a library frame only
    if no Glint frame is on the stack), e.g. `KeyError: 'x' at glint/metrics/compute.py:123 in
    prepare`. The full traceback goes to the log."""
    msg = exc.message if isinstance(exc, GlintError) else str(exc)
    head = " ".join(f"{type(exc).__name__}: {msg}".split())
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return head
    ours = [f for f in frames if "/glint/" in Path(f.filename).as_posix()]
    f = (ours or frames)[-1]
    path = Path(f.filename).as_posix()
    if "/glint/" in path:
        path = "glint/" + path.rsplit("/glint/", 1)[1]
    return f"{head} at {path}:{f.lineno} in {f.name}"


@dataclass(frozen=True)
class MetricsStage:
    """Pipeline stage (contracts/pipeline.py) for WT-07's runner."""

    name: str = "metrics"
    deps: tuple[str, ...] = ("financials", "prices")

    def run(self, ctx: BuildContext) -> StageResult:
        started = time.monotonic()
        try:
            out, counts = build(ctx.build_db, ctx.paths, archive_snapshot=not ctx.options.dry_run)
        except Exception as exc:  # the runner records failures; never half-report success
            # Full traceback to the run log; a one-line "where it broke" into the result, which
            # the pipeline report shows in a table cell (one line, so the table stays intact).
            log.exception("metrics_failed")
            return StageResult(stage=self.name, status=StageStatus.FAILED, error=where(exc),
                               duration_s=time.monotonic() - started)  # fmt: skip
        counts["flags_raised"] = out.flags.height
        log_event(log, "metrics_built", **counts, seconds=round(time.monotonic() - started, 1))
        return StageResult(
            stage=self.name, status=StageStatus.OK, counts=counts,
            duration_s=time.monotonic() - started,
        )  # fmt: skip
