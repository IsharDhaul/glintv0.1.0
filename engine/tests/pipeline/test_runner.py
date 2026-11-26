"""Runner: selection, timing, pipeline_runs, build-then-swap, retention, failure handling."""

from pathlib import Path

import duckdb
import orjson
import pytest

from glint.contracts.pipeline import BuildOptions, StageStatus
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.pipeline.runner import RefreshError, Runner, select_stages
from glint.pipeline.swap import read_pointer
from tests.pipeline.helpers import FakeStage, fake_pipeline, ticking_clock

ORDER = ["download_sec", "financials", "metrics", "publish"]


_CLOCK = {"now": ticking_clock()}


@pytest.fixture(autouse=True)
def _fresh_clock() -> None:
    """One clock per test, shared by every runner in it, so build ids never collide."""
    _CLOCK["now"] = ticking_clock()


def runner(settings: Settings, **overrides: dict[str, object]) -> Runner:
    return Runner(settings, fake_pipeline(**overrides), clock=_CLOCK["now"])


def run_row(db: Path) -> dict[str, object]:
    with duckdb.connect(str(db), read_only=True) as con:
        cur = con.execute("SELECT * FROM pipeline_runs")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    assert len(rows) == 1
    return dict(zip(cols, rows[0], strict=True))


def test_select_stages() -> None:
    assert select_stages(ORDER) == ORDER
    assert select_stages(ORDER, from_="metrics") == ["metrics", "publish"]
    assert select_stages(ORDER, only=["financials"]) == ["financials"]
    with pytest.raises(RefreshError, match="unknown"):
        select_stages(ORDER, only=["nope"])
    with pytest.raises(RefreshError, match="not both"):
        select_stages(ORDER, only=["metrics"], from_="metrics")


def test_full_run_publishes_and_records(settings: Settings) -> None:
    report = runner(settings).run()
    paths = Paths.from_settings(settings)
    assert report.status == "ok" and report.published
    pointer = read_pointer(paths)
    assert pointer is not None and pointer.build_id == report.build_id == "20261030T081500Z"
    assert not pointer.synthetic
    assert (paths.db_dir / pointer.path) == paths.build_db(report.build_id)

    row = run_row(paths.build_db(report.build_id))
    assert row["status"] == "ok" and row["finished"] is not None
    durations = orjson.loads(str(row["stage_durations"]))
    assert set(durations) == set(ORDER)
    assert orjson.loads(str(row["counts"]))["financials"] == {"rows": 1}


def test_warn_status_and_skips(settings: Settings) -> None:
    report = runner(
        settings,
        financials={"status": StageStatus.WARN},
        download_sec={"skip": "unchanged"},
    ).run()
    assert report.status == "warn" and report.published
    statuses = {s.name: s.status for s in report.stages}
    assert statuses["download_sec"] == "skipped"
    row = run_row(report.build_db)
    assert orjson.loads(str(row["warnings"])) == ["financials: something to read"]


def test_failure_keeps_the_previous_build_live(settings: Settings) -> None:
    paths = Paths.from_settings(settings)
    good = runner(settings).run()
    pointer_before = paths.current_pointer.read_bytes()

    r = runner(settings, metrics={"fail": True})
    bad = r.run()
    assert bad.status == "failed" and not bad.published
    assert bad.failed_stage == "metrics" and bad.error == "metrics blew up"
    assert paths.current_pointer.read_bytes() == pointer_before
    publish = next(s for s in r.stages if isinstance(s, FakeStage) and s.name == "publish")
    assert publish.calls == 0, "nothing runs after the failing stage"
    assert {s.name: s.status for s in bad.stages}["publish"] == "not run"
    # The failed build stays for inspection, marked failed; the good one is untouched.
    assert run_row(bad.build_db)["status"] == "failed"
    assert run_row(good.build_db)["status"] == "ok"


def test_keeps_the_last_two_builds(settings: Settings) -> None:
    paths = Paths.from_settings(settings)
    r = runner(settings)
    first, second = r.run(), r.run()
    failed = runner(settings, metrics={"fail": True}).run()
    third = r.run()
    assert third.pruned_builds == sorted([first.build_id, failed.build_id])
    left = sorted(p.name for p in paths.builds_dir.iterdir())
    assert left == [f"{second.build_id}.duckdb", f"{third.build_id}.duckdb"]


def test_dry_run_writes_nothing(settings: Settings) -> None:
    report = runner(settings, download_sec={"skip": "--no-download"}).run(
        BuildOptions(dry_run=True)
    )
    assert report.status == "dry-run"
    assert {s.name: s.skip_reason for s in report.stages}["download_sec"] == "--no-download"
    assert not settings.db_dir.exists()


def test_partial_run_needs_a_real_current_build(settings: Settings) -> None:
    report = runner(settings).run(only=["metrics"])
    assert report.status == "failed" and "full `glint refresh`" in (report.error or "")
    assert not Paths.from_settings(settings).current_pointer.exists()


def test_from_reruns_on_a_copy_of_the_current_build(settings: Settings) -> None:
    paths = Paths.from_settings(settings)
    runner(settings).run()
    r = runner(settings)
    second = r.run(from_="metrics")
    assert second.published
    calls = {s.name: s.calls for s in r.stages if isinstance(s, FakeStage)}
    assert calls == {"download_sec": 0, "financials": 0, "metrics": 1, "publish": 1}
    with duckdb.connect(str(second.build_db), read_only=True) as con:
        # carried over from the copy, not recomputed
        assert con.execute("SELECT ran FROM stage_financials").fetchone() == (1,)
    assert run_row(second.build_db)["run_id"] == second.build_id
    assert read_pointer(paths).build_id == second.build_id  # type: ignore[union-attr]


def test_only_raw_stages_publish_nothing(settings: Settings) -> None:
    report = runner(settings).run(only=["download_sec"])
    assert report.status == "ok" and not report.published
    assert not Paths.from_settings(settings).builds_dir.exists()


def test_user_db_is_never_opened(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = Paths.from_settings(settings)
    paths.db_dir.mkdir(parents=True)
    with duckdb.connect(str(paths.user_db)) as con:
        con.execute("CREATE TABLE saved_screens AS SELECT 'mine' AS name")
    before = paths.user_db.read_bytes(), paths.user_db.stat().st_mtime_ns

    opened: list[Path] = []
    real_connect = duckdb.connect

    def spy(database: str = ":memory:", *args: object, **kwargs: object) -> object:
        opened.append(Path(database).resolve())
        return real_connect(database, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(duckdb, "connect", spy)
    r = runner(settings)
    r.run()
    r.run(from_="metrics")
    runner(settings, metrics={"fail": True}).run()
    r.run()  # prunes builds

    assert opened, "the spy saw the build connections"
    assert paths.user_db.resolve() not in opened
    assert (paths.user_db.read_bytes(), paths.user_db.stat().st_mtime_ns) == before


def test_partial_run_carries_over_counts_and_leaves_the_live_build_alone(
    settings: Settings,
) -> None:
    paths = Paths.from_settings(settings)
    first = runner(settings, financials={"counts": {"coverage.domestic.revenue": 90}}).run()
    live = first.build_db.read_bytes(), first.build_db.stat().st_mtime_ns
    second = runner(settings).run(from_="metrics")
    assert second.published
    assert (first.build_db.read_bytes(), first.build_db.stat().st_mtime_ns) == live
    counts = orjson.loads(str(run_row(second.build_db)["counts"]))
    # financials didn't rerun, but the next build's comparison still needs its numbers
    assert counts["financials"] == {"coverage.domestic.revenue": 90}
    assert set(counts) == {"download_sec", "financials", "metrics", "publish"}
    assert read_pointer(paths).build_id == second.build_id  # type: ignore[union-attr]


def test_a_failure_after_the_swap_is_a_notice_not_a_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise OSError("disk said no")

    monkeypatch.setattr("glint.pipeline.runner.prune_sec_folders", boom)
    report = runner(settings).run()
    assert report.published and report.status == "warn"
    assert report.notices == ["old SEC folders not pruned (next run retries): disk said no"]
    assert report.report_path is not None and "disk said no" in report.report_path.read_text()


def test_dry_run_checks_a_partial_run_too(settings: Settings) -> None:
    report = runner(settings).run(BuildOptions(dry_run=True), only=["metrics"])
    assert report.status == "dry-run" and "full `glint refresh`" in (report.error or "")
    assert not settings.db_dir.exists()


def test_only_refuses_to_publish_tables_derived_from_old_data(settings: Settings) -> None:
    runner(settings).run()
    with pytest.raises(RefreshError, match="would publish metrics computed from the old data"):
        runner(settings).run(only=["financials"])
    assert runner(settings).run(only=["financials", "metrics"]).published


def test_an_unexpected_error_between_stages_fails_the_run_with_a_report(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = Paths.from_settings(settings)
    runner(settings).run()
    pointer_before = paths.current_pointer.read_bytes()

    def boom(*_: object, **__: object) -> None:
        raise ValueError("bad yaml")

    monkeypatch.setattr("glint.pipeline.runner.compare", boom)
    report = runner(settings).run()
    assert report.status == "failed" and report.error == "ValueError: bad yaml"
    assert not report.published
    assert paths.current_pointer.read_bytes() == pointer_before
    assert report.report_path is not None and report.report_path.exists()
    assert run_row(report.build_db)["status"] == "failed"


def test_partial_run_on_an_unreadable_current_build(settings: Settings) -> None:
    first = runner(settings).run()
    first.build_db.unlink()
    report = runner(settings).run(from_="metrics")
    assert report.status == "failed" and "can't read the current build" in (report.error or "")
    dry = runner(settings).run(BuildOptions(dry_run=True), from_="metrics")
    assert "can't read the current build" in (dry.error or "")
