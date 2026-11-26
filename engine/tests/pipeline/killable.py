"""Subprocess for the kill test: `python -m tests.pipeline.killable <tmp> good|slow-metrics`.

`good` publishes one build. `slow-metrics` starts a second build whose metrics stage sleeps, and
writes `METRICS_STARTED` to stdout when it gets there, so the test can SIGKILL it mid-metrics.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from glint.contracts.pipeline import BuildContext
from glint.pipeline.runner import Runner
from tests.conftest import make_settings
from tests.pipeline.helpers import fake_pipeline, ticking_clock


def announce(_: BuildContext) -> None:
    sys.stdout.write("METRICS_STARTED\n")
    sys.stdout.flush()


def main(tmp: Path, mode: str) -> int:
    settings = make_settings(
        sec_user_agent="Glint tests glint-tests@example.org",
        raw_dir=tmp / "raw",
        db_dir=tmp / "data",
    )
    if mode == "good":
        stages = fake_pipeline()
        clock = ticking_clock(datetime(2026, 10, 30, 8, 0, tzinfo=UTC))
    else:
        # announce first, then sleep: FakeStage runs `action` after sleeping, so sleep here.
        def slow(ctx: BuildContext) -> None:
            announce(ctx)
            import time  # noqa: PLC0415

            time.sleep(120)

        stages = fake_pipeline(metrics={"action": slow})
        clock = ticking_clock(datetime(2026, 10, 30, 9, 0, tzinfo=UTC))
    report = Runner(settings, stages, clock=clock).run()
    sys.stdout.write(f"DONE {report.status} {report.build_id}\n")
    return 0 if report.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), sys.argv[2]))
