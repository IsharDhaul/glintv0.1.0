"""Run report: coverage and null-rate comparison with the previous build, markdown output."""

from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.pipeline.report import coverage_drop_threshold, coverage_from_counts
from glint.pipeline.runner import Runner
from tests.pipeline.helpers import fake_pipeline, ticking_clock


def coverage(revenue: int, cash: int, n: int = 100) -> dict[str, int]:
    return {
        "rows": 1,
        "coverage.domestic.companies": n,
        "coverage.domestic.revenue": revenue,
        "coverage.domestic.cash": cash,
        "coverage.financial.companies": 0,
        "coverage.financial.revenue": 0,
    }


def test_threshold_comes_from_config() -> None:
    assert coverage_drop_threshold() == 0.02


def test_coverage_from_counts() -> None:
    shares = coverage_from_counts(coverage(95, 50))
    assert shares["domestic"] == {"cash": 0.5, "revenue": 0.95}
    assert shares["financial"] == {"revenue": None}, "no companies: unknown, not 0%"
    assert shares["foreign"] == {}


def test_drop_over_two_pp_warns_and_is_in_the_report(settings: Settings) -> None:
    clock = ticking_clock()
    first = Runner(
        settings, fake_pipeline(financials={"counts": coverage(95, 50)}), clock=clock
    ).run()
    assert first.status == "ok"
    assert first.comparison is not None and first.comparison.coverage_prev is None

    second = Runner(
        settings, fake_pipeline(financials={"counts": coverage(92, 49)}), clock=clock
    ).run()
    assert second.published, "a coverage drop is a warning, not a failure"
    assert second.status == "warn"
    assert second.comparison is not None
    assert second.comparison.previous_build == first.build_id
    assert second.comparison.warnings == [
        "coverage of revenue (domestic non-financial) fell 3.0 pp: 95.0% → 92.0%. "
        "What changed in the source?"
    ]  # cash fell 1 pp: under the threshold

    paths = Paths.from_settings(settings)
    md = (paths.db_dir / "reports" / f"{second.build_id}.md").read_text()
    assert second.report_path == paths.db_dir / "reports" / f"{second.build_id}.md"
    assert "| revenue | 92.0% | 95.0% | **-3.0 ⚠** |" in md
    assert "| cash | 49.0% | 50.0% | -1.0 |" in md
    assert f"**Previous build:** {first.build_id}" in md
    assert "No metrics in this build yet" in md
    assert "report: coverage of revenue" in md
    assert "UTC" in md and "London" in md and "New York" in md


def test_failed_run_still_writes_a_report(settings: Settings) -> None:
    report = Runner(settings, fake_pipeline(metrics={"fail": True}), clock=ticking_clock()).run()
    assert report.report_path is not None
    md = report.report_path.read_text()
    assert "failed in `metrics`: metrics blew up" in md
    assert "**Published:** no" in md


def test_synthetic_previous_build_is_not_compared(settings: Settings) -> None:
    from glint.fixtures.synthetic import run as synthetic_run  # noqa: PLC0415

    paths = Paths.from_settings(settings)
    synthetic_run(50, 7, paths, mocks_dir=None)
    report = Runner(
        settings, fake_pipeline(financials={"counts": coverage(95, 50)}), clock=ticking_clock()
    ).run()
    assert report.published and report.comparison is not None
    assert report.comparison.previous_build is None
    assert report.comparison.nulls_prev is None
    assert report.report_path is not None
    assert "(synthetic, not compared)" in report.report_path.read_text()
