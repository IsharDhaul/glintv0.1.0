"""Fake stages for runner tests: same shape as the real ones, no data needed."""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from glint.contracts.pipeline import BuildContext, StageStatus
from glint.pipeline.stages import BaseStage, Outcome, StageFailedError, connect_build


class FakeStage(BaseStage):
    def __init__(
        self,
        name: str,
        deps: tuple[str, ...] = (),
        *,
        writes_build: bool = True,
        fail: bool = False,
        sleep_s: float = 0.0,
        status: StageStatus = StageStatus.OK,
        skip: str | None = None,
        action: Callable[[BuildContext], None] | None = None,
        counts: dict[str, int] | None = None,
    ) -> None:
        super().__init__()
        self.name, self.deps, self.writes_build = name, deps, writes_build
        self.fail, self.sleep_s, self.status, self.skip, self.action = (
            fail, sleep_s, status, skip, action,
        )  # fmt: skip
        self.counts = counts or {"rows": 1}
        self.calls = 0

    def skip_reason(self, ctx: BuildContext) -> str | None:
        return self.skip

    def execute(self, ctx: BuildContext) -> Outcome:
        self.calls += 1
        if self.sleep_s:
            time.sleep(self.sleep_s)
        if self.fail:
            raise StageFailedError(f"{self.name} blew up")
        if self.writes_build:
            with connect_build(ctx) as con:
                con.execute(f"CREATE OR REPLACE TABLE stage_{self.name} AS SELECT 1 AS ran")
        if self.action is not None:
            self.action(ctx)
        warnings = ["something to read"] if self.status is StageStatus.WARN else []
        return Outcome(self.status, self.counts, warnings, note=f"{self.name} note")


def fake_pipeline(**overrides: dict[str, object]) -> list[BaseStage]:
    """download → financials → metrics → publish, with per-stage keyword overrides."""
    spec: list[tuple[str, tuple[str, ...], bool]] = [
        ("download_sec", (), False),
        ("financials", ("download_sec",), True),
        ("metrics", ("financials",), True),
        ("publish", ("metrics",), True),
    ]
    return [
        FakeStage(n, d, writes_build=w, **overrides.get(n, {}))  # type: ignore[arg-type]
        for n, d, w in spec
    ]


def ticking_clock(start: datetime | None = None) -> Callable[[], datetime]:
    """A clock that moves 1 minute per call, so every run gets its own build id."""
    times: Iterator[datetime] = (
        (start or datetime(2026, 10, 30, 8, 15, tzinfo=UTC)) + timedelta(minutes=i)
        for i in range(10_000)
    )
    return lambda: next(times)
