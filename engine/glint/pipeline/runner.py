"""`glint refresh`: run the stages in order, time them, record `pipeline_runs`, then swap.

- A full run writes a fresh `data/builds/<build_id>.duckdb` (`build_id` = UTC start time).
- `--only` / `--from` start from a *copy* of the current build and rerun just those stages
  (plus `publish` when any of them writes the build). The live build is never written.
- The first failing stage aborts the run. Nothing after it runs, `current.json` is untouched,
  and the failed build file stays in `builds/` for inspection until the next successful run.
- `--dry-run` writes nothing: it prints what each stage would do and why.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson

from glint.contracts.db import DB_SCHEMA_VERSION, CurrentPointer
from glint.contracts.pipeline import BuildContext, BuildOptions, StageResult, StageStatus
from glint.core.errors import GlintError
from glint.core.filelock import exclusive_lock, raw_lock
from glint.core.log import get_logger, log_event
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.sec.download import prune as prune_sec_folders
from glint.pipeline.report import Comparison, compare, render, run_warnings, write_report
from glint.pipeline.stages import (
    BUILD_ID_FORMAT,
    SEC_FOLDER_KEY,
    BaseStage,
    connect_build,
    init_build_tables,
    source_timestamps,
    validate_order,
)
from glint.pipeline.swap import (
    KEEP_BUILDS,
    pointer_db,
    prune_builds,
    read_pointer,
    seed_from,
    write_pointer,
)
from glint.universe.build import COMPANIES_FILE

log = get_logger(__name__)

PUBLISH = "publish"


class RefreshError(GlintError):
    code = "REFRESH_ERROR"


@dataclass
class StageRun:
    name: str
    selected: bool
    result: StageResult | None = None
    note: str | None = None
    skip_reason: str | None = None  # decided before running (options, incremental)

    @property
    def status(self) -> str:
        if not self.selected:
            return "not selected"
        return self.result.status.value if self.result else "not run"


@dataclass
class RunReport:
    build_id: str
    started: datetime
    paths: Paths
    stages: list[StageRun]
    previous: CurrentPointer | None
    dry_run: bool = False
    partial: bool = False
    finished: datetime | None = None
    status: str = "running"  # running | ok | warn | failed
    error: str | None = None
    failed_stage: str | None = None
    published: bool = False
    pruned_builds: list[str] = field(default_factory=list[str])
    log_path: Path | None = None
    comparison: Comparison | None = None
    report_path: Path | None = None
    # --only/--from: counts of the stages not rerun, carried over from the copied build so the
    # next run's comparison still has every stage's numbers.
    inherited_counts: dict[str, dict[str, int]] = field(default_factory=dict[str, dict[str, int]])
    notices: list[str] = field(default_factory=list[str])  # after the swap (can't fail the run)

    @property
    def build_db(self) -> Path:
        return self.paths.build_db(self.build_id)

    def counts(self) -> dict[str, dict[str, int]]:
        ran = {s.name: s.result.counts for s in self.stages if s.result is not None}
        return {**self.inherited_counts, **ran}

    def result(self, name: str) -> StageResult | None:
        return next((s.result for s in self.stages if s.name == name), None)

    @property
    def seconds(self) -> float:
        end = self.finished or datetime.now(UTC)
        return (end - self.started).total_seconds()


def new_build_id(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime(BUILD_ID_FORMAT)


def select_stages(
    order: Sequence[str], only: Sequence[str] = (), from_: str | None = None
) -> list[str]:
    """Which stages run. `only` and `from_` are exclusive; neither means all."""
    unknown = [s for s in [*only, *([from_] if from_ else [])] if s not in order]
    if unknown:
        raise RefreshError(f"unknown stage(s) {unknown}; stages are: {', '.join(order)}")
    if only and from_:
        raise RefreshError("use --only or --from, not both")
    if from_:
        return list(order[order.index(from_) :])
    if only:
        return [s for s in order if s in only]
    return list(order)


class Runner:
    def __init__(
        self,
        settings: Settings,
        stages: list[BaseStage],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        validate_order(stages)
        if not stages or stages[-1].name != PUBLISH:
            raise RefreshError(f"the last stage must be {PUBLISH}")
        self.settings = settings
        self.paths = Paths.from_settings(settings)
        self.stages = stages
        self.clock = clock

    # --- planning ------------------------------------------------------------------------

    def plan(
        self, options: BuildOptions, only: Sequence[str] = (), from_: str | None = None
    ) -> tuple[list[StageRun], bool]:
        """Selected stages (publish added when a build stage runs) and whether it's partial."""
        order = [s.name for s in self.stages]
        names = select_stages(order, only, from_)
        partial = bool(only or from_)
        by_name = {s.name: s for s in self.stages}
        stale = self._stale_dependents(names)
        if stale:
            raise RefreshError(
                f"--only {','.join(names)} would publish {', '.join(stale)} computed from the "
                f"old data: add {'it' if len(stale) == 1 else 'them'} to --only, or use --from"
            )
        if any(by_name[n].writes_build for n in names) and PUBLISH not in names:
            names.append(PUBLISH)
        return [StageRun(s.name, s.name in names) for s in self.stages], partial

    def _stale_dependents(self, names: Sequence[str]) -> list[str]:
        """Build tables not rerun that are derived from ones that are: publishing them would
        mix old and new data in one build."""
        changed = {n for n in names if self._stage(n).writes_build}
        stale: list[str] = []
        for s in self.stages:  # dependency order, so staleness carries downstream
            fresh = s.name in names or s.name == PUBLISH or not s.writes_build
            if not fresh and any(d in changed for d in s.deps):
                stale.append(s.name)
                changed.add(s.name)
        return stale

    # --- running -------------------------------------------------------------------------

    def run(
        self,
        options: BuildOptions | None = None,
        *,
        only: Sequence[str] = (),
        from_: str | None = None,
        on_stage: Callable[[StageRun], None] | None = None,
        log_path: Path | None = None,
        build_id: str | None = None,
    ) -> RunReport:
        options = options or BuildOptions()
        started = self.clock()
        build_id = build_id or new_build_id(started)
        runs, partial = self.plan(options, only, from_)
        report = RunReport(
            build_id=build_id,
            started=started,
            paths=self.paths,
            stages=runs,
            previous=read_pointer(self.paths),
            dry_run=options.dry_run,
            partial=partial,
            log_path=log_path,
        )
        ctx = BuildContext(
            build_id=build_id,
            settings=self.settings,
            paths=self.paths,
            build_db=self.paths.build_db(build_id),
            options=options,
        )
        if options.dry_run:
            self._dry_run(ctx, report)
            return report

        self.paths.db_dir.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.paths.db_dir / "refresh.lock"):
            self._run_locked(ctx, report, on_stage)
        return report

    def _dry_run(self, ctx: BuildContext, report: RunReport) -> None:
        if report.partial and self._needs_build(report):
            try:
                self._inherit(ctx, report, pointer_db(self.paths, self._partial_source(report)))
            except GlintError as exc:
                report.error = exc.message
        downloads = False
        for run in report.stages:
            if not run.selected:
                continue
            if run.name == "extract_facts" and downloads:
                run.note = "runs unless SEC answers 304 (decided after download_sec)"
                continue
            stage = self._stage(run.name)
            try:
                run.skip_reason = stage.skip_reason(ctx)
            except GlintError as exc:
                run.skip_reason = f"would fail: {exc.message}"
            downloads = downloads or (run.name == "download_sec" and run.skip_reason is None)
        report.status = "dry-run"

    def _stage(self, name: str) -> BaseStage:
        return next(s for s in self.stages if s.name == name)

    def _needs_build(self, report: RunReport) -> bool:
        return any(r.selected and self._stage(r.name).writes_build for r in report.stages)

    def _partial_source(self, report: RunReport) -> CurrentPointer:
        prev = report.previous
        if prev is None or prev.synthetic:
            raise RefreshError(
                "--only/--from rerun stages on a copy of the current real build, and there "
                "isn't one (current.json is missing or synthetic): run a full `glint refresh`"
            )
        if prev.db_schema_version != DB_SCHEMA_VERSION:
            raise RefreshError(
                f"current build is schema v{prev.db_schema_version}, engine is "
                f"v{DB_SCHEMA_VERSION}: run a full `glint refresh`"
            )
        return prev

    def _inherit(self, ctx: BuildContext, report: RunReport, db: Path) -> None:
        """A partial run keeps the copied build's SEC folder (unless it rebuilds companies) and
        the counts of the stages it doesn't rerun."""
        try:
            with duckdb.connect(str(db), read_only=True) as con:
                row = con.execute(
                    "SELECT counts, source_timestamps FROM pipeline_runs "
                    "WHERE status IN ('ok', 'warn') ORDER BY finished DESC LIMIT 1"
                ).fetchone()
        except duckdb.Error as exc:
            raise RefreshError(
                f"can't read the current build {db.name} ({exc}): run a full `glint refresh`"
            ) from exc
        if row is None:
            return
        counts: dict[str, dict[str, int]] = orjson.loads(row[0])
        sources: dict[str, str] = orjson.loads(row[1])
        selected = {r.name for r in report.stages if r.selected}
        report.inherited_counts = {k: v for k, v in counts.items() if k not in selected}
        folder = sources.get(SEC_FOLDER_KEY)
        if folder is not None and "companies" not in selected:
            if not (self.paths.sec_raw / folder / COMPANIES_FILE).exists():
                raise RefreshError(
                    f"the current build was made from SEC folder {folder}, which has since been "
                    "pruned: use --from companies or run a full `glint refresh`"
                )
            ctx.raw_date = date.fromisoformat(folder)

    def _prepare_build(self, ctx: BuildContext, report: RunReport) -> bool:
        """Create (or, for a partial run, seed) the build file. False: no build needed."""
        if not self._needs_build(report):
            return False
        if ctx.build_db.exists():
            raise RefreshError(f"{ctx.build_db} already exists; wait a second and rerun")
        if report.partial:
            source = pointer_db(self.paths, self._partial_source(report))
            self._inherit(ctx, report, source)
            seed_from(source, ctx.build_db)
        ctx.build_db.parent.mkdir(parents=True, exist_ok=True)
        with connect_build(ctx) as con:
            init_build_tables(con)
            con.execute("DELETE FROM pipeline_runs")  # a seeded copy keeps only its own run
        return True

    def _run_locked(
        self,
        ctx: BuildContext,
        report: RunReport,
        on_stage: Callable[[StageRun], None] | None,
    ) -> None:
        has_build = False
        try:
            has_build = self._prepare_build(ctx, report)
            if has_build:
                self._record(ctx, report)
            for run in report.stages:
                if not run.selected:
                    continue
                self._run_stage(ctx, run)
                if on_stage is not None:
                    on_stage(run)
                if run.result is not None and run.result.status is StageStatus.FAILED:
                    report.failed_stage, report.error = run.name, run.result.error
                    break
                if has_build:
                    if run.name == PUBLISH:
                        report.comparison = compare(
                            self.paths, ctx.build_db, report.counts(), report.previous
                        )
                        report.status = _final_status(report)
                        report.finished = self.clock()
                    self._record(ctx, report)
        except GlintError as exc:
            report.error = exc.message
        except Exception as exc:
            # A bug or I/O error between stages (recording, comparing): a failed run, not a crash.
            log.exception("refresh_error")
            report.error = f"{type(exc).__name__}: {exc}"
        except BaseException:
            # Ctrl-C (or anything else): record the abort if we can, never swap, re-raise.
            report.error = report.error or "interrupted"
            report.status = "failed"
            report.finished = self.clock()
            if has_build:
                self._record(ctx, report, quiet=True)
            self._write_report(report)
            raise

        if report.error is not None:
            report.status = "failed"
            report.finished = self.clock()
            if has_build:
                self._record(ctx, report, quiet=True)
            log_event(
                log, "refresh_failed", build_id=ctx.build_id, stage=report.failed_stage,
                error=report.error,
            )  # fmt: skip
            self._write_report(report)
            return

        if has_build:
            self._swap(ctx, report)
        else:
            report.status = _final_status(report)
            report.finished = self.clock()
        log_event(
            log, "refresh_done", build_id=ctx.build_id, status=report.status,
            published=report.published, seconds=round(report.seconds, 1),
        )  # fmt: skip
        self._write_report(report)

    def _write_report(self, report: RunReport) -> None:
        try:
            report.report_path = write_report(
                self.paths, report.build_id, render(report, report.comparison)
            )
        except OSError:
            log.exception("report_not_written")

    def _run_stage(self, ctx: BuildContext, run: StageRun) -> None:
        stage = self._stage(run.name)
        t0 = time.monotonic()
        try:
            run.skip_reason = stage.skip_reason(ctx)
            if run.skip_reason is not None:
                result = StageResult(stage=run.name, status=StageStatus.SKIPPED, duration_s=0)
            else:
                log_event(log, "stage_start", stage=run.name)
                result = stage.run(ctx)
                run.note = stage.note
        except Exception as exc:
            message = exc.message if isinstance(exc, GlintError) else f"{type(exc).__name__}: {exc}"
            log.exception("stage_failed", extra={"stage": run.name})
            result = StageResult(
                stage=run.name, status=StageStatus.FAILED, duration_s=0, error=message
            )
        run.result = result.model_copy(update={"duration_s": round(time.monotonic() - t0, 3)})
        ctx.results[run.name] = run.result
        log_event(
            log,
            "stage_done",
            stage=run.name,
            status=run.result.status.value,
            seconds=run.result.duration_s,
            **{k.replace(".", "_"): v for k, v in run.result.counts.items() if "." not in k},
        )

    def _record(self, ctx: BuildContext, report: RunReport, *, quiet: bool = False) -> None:
        """Upsert this run's `pipeline_runs` row in the build (never the live one)."""
        results = [r.result for r in report.stages if r.result is not None]
        try:
            row: list[Any] = [
                ctx.build_id,
                report.started,
                report.finished,
                report.status,
                orjson.dumps({r.stage: r.duration_s for r in results}).decode(),
                orjson.dumps(report.counts()).decode(),
                orjson.dumps(source_timestamps(ctx)).decode(),
                orjson.dumps(run_warnings(report)).decode(),
            ]
            with connect_build(ctx) as con:
                con.execute("DELETE FROM pipeline_runs WHERE run_id = ?", [ctx.build_id])
                con.execute("INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
        except Exception:
            if not quiet:
                raise
            log.exception("pipeline_runs_not_recorded")

    def _swap(self, ctx: BuildContext, report: RunReport) -> None:
        created = datetime.strptime(ctx.build_id, BUILD_ID_FORMAT).replace(tzinfo=UTC)
        write_pointer(self.paths, ctx.build_id, created)
        report.published = True
        # The build is live: tidying up can only add a notice, never turn this into a failure.
        keep = {ctx.build_id}
        if report.previous is not None:
            keep.add(report.previous.build_id)
        assert len(keep) <= KEEP_BUILDS
        try:
            report.pruned_builds = prune_builds(self.paths, keep)
        except OSError as exc:
            report.notices.append(f"old builds not pruned: {exc}")
        # Old SEC folders go only after a build from the new one succeeded (WT-01's rule).
        try:
            with raw_lock(self.paths.raw_dir, timeout_s=60):
                prune_sec_folders(self.paths.sec_raw, marker=COMPANIES_FILE)
        except (GlintError, OSError) as exc:
            msg = exc.message if isinstance(exc, GlintError) else str(exc)
            report.notices.append(f"old SEC folders not pruned (next run retries): {msg}")
        if report.notices:
            log.warning("post_publish_notices", extra={"notices": report.notices})
            report.status = "warn"


def _final_status(report: RunReport) -> str:
    warn = any(r.result is not None and r.result.status is StageStatus.WARN for r in report.stages)
    return "warn" if warn or run_warnings(report) else "ok"
