"""Stage acceptance: one reason per null over the whole snapshot, determinism, write + archive."""

import logging
import re
import subprocess
import sys
import time
import traceback
from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from glint.contracts.db import BUILD_TABLES
from glint.contracts.enums import NON_NULL_NOTE_CODES
from glint.contracts.metrics import load_registry
from glint.contracts.pipeline import BuildContext, StageStatus
from glint.core.filelock import LockTimeoutError
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.financials.concepts import load_concepts
from glint.flags.engine import load_rules
from glint.metrics.io import insert_frame, read_sql
from glint.metrics.params import load_params
from glint.metrics.share_classes import load_share_classes
from glint.metrics.stage import (
    ARCHIVE_LOCK_WAIT_S,
    MetricsOutput,
    MetricsStage,
    archive,
    run_metrics,
    write_metrics,
)

INFO = {c.value for c in NON_NULL_NOTE_CODES}


def test_every_null_has_exactly_one_reason(
    fixture_build: tuple[MetricsOutput, pl.DataFrame],
) -> None:
    out = fixture_build[0]
    notes = out.notes
    assert notes.select("cik", "metric_id").is_duplicated().sum() == 0
    for m in load_registry().live():
        joined = out.snapshot.select("cik", m.id).join(
            notes.filter(pl.col("metric_id") == m.id), on="cik", how="left"
        )
        nulls = joined.filter(pl.col(m.id).is_null())
        assert nulls["code"].null_count() == 0, m.id
        assert not nulls["code"].is_in(list(INFO)).any(), m.id
        values = joined.filter(pl.col(m.id).is_not_null() & pl.col("code").is_not_null())
        assert values["code"].is_in(list(INFO)).all(), m.id


def test_same_inputs_same_snapshot(fixture_build: tuple[MetricsOutput, pl.DataFrame]) -> None:
    first, fin = fixture_build
    companies = first.frame.select(
        "cik", "name", "tickers", pl.col("primary_ticker_provisional").alias("primary_ticker"),
        "exchange", "sector", "kind", "is_foreign_filer", "is_reit", "has_facts", "taxonomy",
        "reporting_currency", "last_annual_date", "last_quarterly_date", "nt_filing_12m",
        "fy_end_changed", "last_annual_form",
    )  # fmt: skip
    stats = first.frame.select(
        pl.col("primary_ticker").alias("ticker"), pl.col("price_as_of").alias("as_of"),
        *(pl.col(c).alias(c.removeprefix("px__")) for c in first.frame.columns
          if c.startswith("px__")), "history_days",
    ).drop_nulls("as_of").unique("ticker")  # fmt: skip
    a = _run(companies, fin, stats)
    b = _run(companies.sample(fraction=1.0, shuffle=True, seed=3), fin.reverse(), stats.reverse())
    for name in ("snapshot", "notes", "history", "flags"):
        assert_frame_equal(getattr(a, name), getattr(b, name))


def _run(companies: pl.DataFrame, fin: pl.DataFrame, stats: pl.DataFrame) -> MetricsOutput:
    return run_metrics(
        companies, fin, stats, None,
        as_of_fundamentals=date(2026, 10, 29), as_of_prices=date(2026, 10, 28),
        share_classes=load_share_classes(), registry=load_registry(), params=load_params(),
        concepts=load_concepts(), flag_cfg=load_rules(),
    )  # fmt: skip


def test_write_and_archive(
    fixture_build: tuple[MetricsOutput, pl.DataFrame], tmp_path: Path
) -> None:
    out = fixture_build[0]
    db = tmp_path / "b.duckdb"
    live = load_registry().live()
    with duckdb.connect(str(db)) as con:
        con.execute(BUILD_TABLES["companies"])
        insert_frame(con, "companies", out.frame.select(
            "cik", "name", "tickers", pl.col("primary_ticker_provisional").alias("primary_ticker"),
            "exchange", "sector", "kind", "is_foreign_filer", "is_reit", "has_facts",
            "nt_filing_12m", "fy_end_changed",
        ))  # fmt: skip
        counts = write_metrics(con, out, live)
        stored = read_sql(con, "SELECT * FROM metrics_snapshot ORDER BY cik")
        primary = read_sql(con, "SELECT cik, primary_ticker FROM companies ORDER BY cik")
    assert counts["metrics_snapshot"] == out.snapshot.height
    assert_frame_equal(stored, out.snapshot, check_dtypes=False)
    assert_frame_equal(primary, out.primary.sort("cik"))
    paths = Paths(raw_dir=tmp_path / "raw", db_dir=tmp_path / "data")
    folder = archive(out, paths, date(2026, 10, 29))
    assert folder == tmp_path / "raw" / "snapshots" / "date=2026-10-29"
    assert sorted(p.name for p in folder.iterdir()) == [
        "flags.parquet", "metric_history.parquet", "metric_notes.parquet",
        "metrics_snapshot.parquet",
    ]  # fmt: skip
    assert_frame_equal(pl.read_parquet(folder / "metrics_snapshot.parquet"), out.snapshot)
    archive(out, paths, date(2026, 10, 29))  # a rerun replaces the same date
    assert not (folder.parent / "date=2026-10-29.tmp").exists()


def _hold_raw_lock(raw_dir: Path, seconds: float) -> subprocess.Popen[str]:
    """Another process (as another worktree's ingest would) holding raw.lock for `seconds`."""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time, pathlib\n"
            "from glint.core.filelock import raw_lock\n"
            f"with raw_lock(pathlib.Path({str(raw_dir)!r})):\n"
            "    print('locked', flush=True)\n"
            f"    time.sleep({seconds})\n",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"
    return holder


def test_archive_waits_for_raw_lock_then_times_out_cleanly(
    fixture_build: tuple[MetricsOutput, pl.DataFrame], tmp_path: Path
) -> None:
    out = fixture_build[0]
    paths = Paths(raw_dir=tmp_path / "raw", db_dir=tmp_path / "data")
    holder = _hold_raw_lock(paths.raw_dir, 30)
    try:
        t0 = time.monotonic()
        with pytest.raises(
            LockTimeoutError, match=r"metrics archive waited 0\.6 s for .*raw\.lock"
        ):
            archive(out, paths, date(2026, 10, 29), lock_wait_s=0.6)
        assert time.monotonic() - t0 >= 0.6  # it waited, rather than failing at once
    finally:
        holder.kill()
        holder.wait()
    assert not paths.snapshots.exists()  # nothing half-written


def test_archive_proceeds_once_the_lock_is_released(
    fixture_build: tuple[MetricsOutput, pl.DataFrame], tmp_path: Path
) -> None:
    paths = Paths(raw_dir=tmp_path / "raw", db_dir=tmp_path / "data")
    holder = _hold_raw_lock(paths.raw_dir, 0.5)
    try:
        folder = archive(fixture_build[0], paths, date(2026, 10, 29), lock_wait_s=10)
    finally:
        holder.wait()
    assert (folder / "metrics_snapshot.parquet").exists()


def test_archive_lock_wait_matches_the_pipeline() -> None:
    # Imported here, not at the top: keeps the metrics tests free of the pipeline import chain.
    from glint.pipeline.stages import RAW_LOCK_WAIT_S  # noqa: PLC0415

    assert ARCHIVE_LOCK_WAIT_S == RAW_LOCK_WAIT_S


def test_failed_stage_says_where_it_broke(
    settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # An empty build database: load_inputs fails reading `companies` (a DuckDB error).
    ctx = BuildContext(
        "20261031T091500Z", settings, Paths.from_settings(settings), tmp_path / "empty.duckdb"
    )
    with caplog.at_level(logging.ERROR):
        result = MetricsStage().run(ctx)
    assert result.status is StageStatus.FAILED
    assert result.error is not None
    assert "\n" not in result.error  # one line: the report shows it in a table cell
    assert result.error.startswith("CatalogException: ")
    assert re.search(r" at glint/metrics/io\.py:\d+ in read_sql$", result.error), result.error
    # The full traceback is in the log.
    failed = [r for r in caplog.records if r.getMessage() == "metrics_failed"]
    assert failed and failed[0].exc_info is not None
    tb = "".join(traceback.format_exception(*failed[0].exc_info))
    assert "in load_inputs" in tb and "in read_sql" in tb
