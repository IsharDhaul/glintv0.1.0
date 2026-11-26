"""Stage registry: order, dependencies, and the adapter around WT-06's MetricsStage."""

from dataclasses import dataclass, field

import duckdb
import orjson
import pytest

from glint.contracts.pipeline import BuildContext, Stage, StageResult, StageStatus
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.sec.download import COMPANYFACTS, MANIFEST
from glint.pipeline.stages import (
    STAGE_ORDER,
    Metrics,
    StageFailedError,
    connect_build,
    default_stages,
    init_build_tables,
    validate_order,
)


def test_order_matches_the_brief() -> None:
    assert STAGE_ORDER == (
        "download_sec", "extract_facts", "companies", "financials", "prices", "price_stats",
        "metrics", "publish",
    )  # fmt: skip


def test_every_stage_satisfies_the_contract_and_deps_run_first() -> None:
    stages = default_stages()
    assert all(isinstance(s, Stage) for s in stages)
    validate_order(stages)


@dataclass
class InnerMetrics:
    """Stands in for WT-06's MetricsStage: records build_meta as it saw it."""

    status: StageStatus = StageStatus.OK
    seen_meta: dict[str, str] = field(default_factory=dict[str, str])

    def run(self, ctx: BuildContext) -> StageResult:
        with duckdb.connect(str(ctx.build_db), read_only=True) as con:
            self.seen_meta.update(con.execute("SELECT key, value FROM build_meta").fetchall())
        if self.status is StageStatus.FAILED:
            return StageResult(
                stage="metrics", status=self.status, error="no financials table", duration_s=0
            )
        return StageResult(
            stage="metrics",
            status=self.status,
            counts={"metrics_snapshot": 3, "flags_raised": 2},
            duration_s=0,
        )


def metrics_ctx(settings: Settings) -> BuildContext:
    paths = Paths.from_settings(settings)
    folder = paths.sec_raw / "2026-10-29"
    folder.mkdir(parents=True)
    entry = {"sha256": "x", "last_modified": "Thu, 29 Oct 2026 07:41:02 GMT"}
    (folder / MANIFEST).write_bytes(orjson.dumps({"files": {COMPANYFACTS.name: entry}}))
    ctx = BuildContext("20261030T091500Z", settings, paths, paths.build_db("20261030T091500Z"))
    ctx.build_db.parent.mkdir(parents=True)
    with connect_build(ctx) as con:
        init_build_tables(con)
    return ctx


def test_metrics_reads_build_meta_written_just_before_it(settings: Settings) -> None:
    inner = InnerMetrics()
    result = Metrics(inner).run(metrics_ctx(settings))  # type: ignore[arg-type]
    assert result.status is StageStatus.OK
    assert result.counts == {"metrics_snapshot": 3, "flags_raised": 2}
    assert inner.seen_meta["as_of_fundamentals"] == "2026-10-29T07:41:02+00:00"
    assert inner.seen_meta["build_id"] == "20261030T091500Z"


def test_metrics_failure_raises_so_the_runner_aborts(settings: Settings) -> None:
    metrics = Metrics(InnerMetrics(status=StageStatus.FAILED))  # type: ignore[arg-type]
    with pytest.raises(StageFailedError, match="no financials table"):
        metrics.run(metrics_ctx(settings))
