"""The real stages end to end, WT-06's metrics included, against a fake SEC and a fake price
provider."""

import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import httpx
import orjson
import polars as pl
import pytest

from glint.contracts.pipeline import BuildContext, BuildOptions
from glint.core.filelock import raw_lock
from glint.core.http import SecGateway
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.prices import backfill
from glint.ingest.prices.models import Bar
from glint.ingest.prices.provider import PriceProvider, latest_requestable
from glint.ingest.prices.store import PriceStore
from glint.pipeline.runner import Runner
from glint.pipeline.stages import BaseStage, connect_build, default_stages
from glint.pipeline.swap import read_pointer
from tests.ingest_sec.test_run import bodies
from tests.pipeline.helpers import ticking_clock
from tests.prices.helpers import FakeProvider

# The runner's clock (ticking_clock) starts here; the price stage reads the wall clock instead.
PINNED_NOW = datetime(2026, 10, 30, 8, 15, tzinfo=UTC)


@pytest.fixture(autouse=True)
def pinned_price_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin "yesterday in New York" to the runner's clock, so the price stage fetches the same
    days whatever the date. Unpinned, a cold store fetches nothing on a Sunday or Monday."""

    def pinned(_now: datetime | None = None) -> date:
        return latest_requestable(PINNED_NOW)

    monkeypatch.setattr(backfill, "latest_requestable", pinned)


def fake_sec() -> tuple[httpx.MockTransport, list[str]]:
    files = bodies()
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        name = req.url.path.rsplit("/", 1)[-1]
        if name == "index.json":  # a filing index (cover facts, ingest/sec/covers.py): no instance
            seen.append(f"200 {name}")
            return httpx.Response(200, json={"directory": {"item": []}})
        if req.headers.get("If-None-Match") == f'"{name}"':
            seen.append(f"304 {name}")
            return httpx.Response(304)
        seen.append(f"200 {name}")
        headers = {"ETag": f'"{name}"', "Last-Modified": "Mon, 26 Oct 2026 21:10:44 GMT"}
        return httpx.Response(200, content=files[name], headers=headers)

    return httpx.MockTransport(handler), seen


def stages(transport: httpx.MockTransport, provider: PriceProvider) -> list[BaseStage]:
    return default_stages(
        gateway=lambda settings: SecGateway(settings, transport=transport),
        provider=lambda _settings, _tickers: provider,
    )


@pytest.fixture
def user_db_spy(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    opened: list[Path] = []
    real = duckdb.connect

    def spy(database: str = ":memory:", *args: object, **kwargs: object) -> object:
        opened.append(Path(database).resolve())
        return real(database, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(duckdb, "connect", spy)
    return opened


def test_cold_then_warm_then_offline(settings: Settings, user_db_spy: list[Path]) -> None:
    paths = Paths.from_settings(settings)
    transport, seen = fake_sec()
    provider = FakeProvider()
    runner = Runner(settings, stages(transport, provider), clock=ticking_clock())

    cold = runner.run()
    assert cold.status in {"ok", "warn"}, cold.error
    assert cold.published
    st = {s.name: s.status for s in cold.stages}
    assert st["download_sec"] == "ok" and st["extract_facts"] == "ok"
    assert all(x.startswith("200") for x in seen)

    with duckdb.connect(str(cold.build_db), read_only=True) as con:
        companies = con.execute("SELECT count(*) FROM companies").fetchone()
        financials = con.execute("SELECT count(DISTINCT cik) FROM financials").fetchone()
        stats = con.execute("SELECT ticker FROM price_stats ORDER BY ticker").fetchall()
        meta = dict(con.execute("SELECT key, value FROM build_meta").fetchall())
        (sources,) = con.execute("SELECT source_timestamps FROM pipeline_runs").fetchone() or ("",)
    # The API reads every one as a datetime (contracts/api.py: dict[str, datetime | None]).
    parsed = {k: datetime.fromisoformat(v) for k, v in orjson.loads(sources).items()}
    assert parsed["sec.companyfacts.zip"] == datetime(2026, 10, 26, 21, 10, 44, tzinfo=UTC)
    assert meta["as_of_fundamentals"] == "2026-10-26T21:10:44+00:00"
    assert companies == (5,) and financials is not None and financials[0] >= 3
    assert stats == [("AAPL",), ("MSFT",)]
    assert meta["build_id"] == cold.build_id and meta["synthetic"] == "false"
    assert meta["as_of_prices"] == provider.calls[-1].isoformat()
    with duckdb.connect(str(cold.build_db), read_only=True) as con:
        snapshot = con.execute("SELECT count(*) FROM metrics_snapshot").fetchone()
    assert snapshot == (5,)
    assert cold.comparison is not None and cold.comparison.nulls is not None
    (archive,) = paths.snapshots.iterdir()
    assert archive.name == f"date={meta['as_of_fundamentals'][:10]}"
    assert sorted(p.name for p in archive.iterdir()) == [
        "flags.parquet", "metric_history.parquet", "metric_notes.parquet",
        "metrics_snapshot.parquet",
    ]  # fmt: skip

    # Same day again: SEC answers 304, facts_raw and companies.parquet are reused.
    seen.clear()
    warm = runner.run()
    assert warm.published, warm.error
    st = {s.name: s for s in warm.stages}
    assert st["download_sec"].status == "skipped"
    assert st["extract_facts"].status == "skipped"
    assert "reused" in (st["companies"].note or "")
    assert st["financials"].status == "ok", "financials always recompute"
    assert all(x.startswith("304") for x in seen)
    assert st["prices"].status == "skipped", "no new dates to fetch"

    # Offline rebuild: no network at all.
    seen.clear()
    offline = runner.run(BuildOptions(no_download=True))
    assert offline.published, offline.error
    assert seen == []
    st = {s.name: s for s in offline.stages}
    assert st["download_sec"].skip_reason and st["prices"].skip_reason

    pointer = read_pointer(paths)
    assert pointer is not None and pointer.build_id == offline.build_id
    assert sorted(p.stem for p in paths.builds_dir.glob("*.duckdb")) == [
        warm.build_id, offline.build_id,
    ]  # fmt: skip
    assert paths.user_db.resolve() not in user_db_spy


def test_price_stats_follow_ticker_changes(settings: Settings) -> None:
    """config/ticker_changes.yaml: TCBI trades as TXCP from 2026-11-09 (same CIK)."""
    paths = Paths.from_settings(settings)
    store = PriceStore(paths)
    days = [date(2026, 11, d) for d in (4, 5, 6, 9, 10)]

    def bar(t: str, d: date) -> Bar:
        return Bar(t, d, 50.0, 50.0, 50.0, 50.0 + d.day, 1000.0, 50.0)

    with store.writer():
        for d in days:
            store.write_day(d, [bar("TCBI" if d < date(2026, 11, 9) else "TXCP", d)], source="t")
    ctx = BuildContext("20261111T091500Z", settings, paths, paths.build_db("20261111T091500Z"))
    ctx.build_db.parent.mkdir(parents=True)
    with connect_build(ctx) as con:
        from glint.pipeline.stages import init_build_tables  # noqa: PLC0415

        init_build_tables(con)
    price_stats = next(s for s in default_stages() if s.name == "price_stats")
    price_stats.run(ctx)
    with duckdb.connect(str(ctx.build_db), read_only=True) as con:
        rows = con.execute("SELECT ticker, history_days, close FROM price_stats").fetchall()
    assert rows == [("TXCP", 5, 60.0)]


def meta_of(db: Path) -> dict[str, str]:
    with duckdb.connect(str(db), read_only=True) as con:
        return dict(con.execute("SELECT key, value FROM build_meta").fetchall())


def test_partial_run_stays_on_its_build_s_sources(settings: Settings) -> None:
    """--only metrics after a newer SEC folder and newer bars appear on disk: the build's
    as-of dates and the archive date stay those of the data it was built from."""
    paths = Paths.from_settings(settings)
    transport, _ = fake_sec()
    provider = FakeProvider()
    runner = Runner(settings, stages(transport, provider), clock=ticking_clock())
    cold = runner.run()
    assert cold.published, cold.error
    before = meta_of(cold.build_db)

    (old,) = [p for p in paths.sec_raw.iterdir() if p.is_dir()]
    newer = paths.sec_raw / "2099-01-01"
    newer.mkdir()
    m = orjson.loads((old / "manifest.json").read_bytes())
    for entry in m["files"].values():
        entry["fetched_at"], entry["last_modified"] = "2099-01-01T06:00:00+00:00", None
    (newer / "manifest.json").write_bytes(orjson.dumps(m))
    store = PriceStore(paths)
    later = date.fromisoformat(before["as_of_prices"]) + timedelta(days=7)
    with store.writer():
        store.write_day(later, [Bar("AAPL", later, 1, 1, 1, 1, 1, 1)], source="t")

    partial = runner.run(only=["metrics"])
    assert partial.published, partial.error
    after = meta_of(partial.build_db)
    assert after["as_of_fundamentals"] == before["as_of_fundamentals"]
    assert after["as_of_prices"] == before["as_of_prices"]
    assert [p.name for p in paths.snapshots.iterdir()] == [
        f"date={before['as_of_fundamentals'][:10]}"
    ]


def test_a_rewritten_companies_parquet_is_not_reused(settings: Settings) -> None:
    from glint.pipeline.stages import companies_are_current  # noqa: PLC0415
    from glint.universe.build import COMPANIES_FILE  # noqa: PLC0415

    paths = Paths.from_settings(settings)
    transport, _ = fake_sec()
    runner = Runner(settings, stages(transport, FakeProvider()), clock=ticking_clock())
    assert runner.run().published
    (folder,) = [p for p in paths.sec_raw.iterdir() if p.is_dir()]
    assert companies_are_current(folder)
    # another checkout's `glint ingest sec` rewrites it (here: one company fewer)
    df = pl.read_parquet(folder / COMPANIES_FILE)
    df.head(df.height - 1).write_parquet(folder / COMPANIES_FILE)
    assert not companies_are_current(folder)
    # financials alone notices it no longer matches what the companies stage loaded
    report = runner.run(only=["financials", "metrics"])
    assert report.status == "failed" and report.failed_stage == "financials"
    assert "--from companies" in (report.error or "")
    again = runner.run(BuildOptions(no_download=True))
    assert again.published, again.error
    assert "rebuilt" in ({s.name: s for s in again.stages}["companies"].note or "")


def test_stages_wait_for_another_holder_of_raw_lock(settings: Settings) -> None:
    paths = Paths.from_settings(settings)
    transport, _ = fake_sec()
    runner = Runner(settings, stages(transport, FakeProvider()), clock=ticking_clock())
    held, release = threading.Event(), threading.Event()

    def other_worktree() -> None:
        with raw_lock(paths.raw_dir):
            held.set()
            release.wait(5)

    t = threading.Thread(target=other_worktree)
    t.start()
    held.wait(5)
    threading.Timer(0.5, release.set).start()
    report = runner.run()
    t.join()
    assert report.published, report.error


def test_financials_holds_raw_lock_while_it_reads_the_sec_folder(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another worktree's publish prunes old SEC folders under raw.lock; it must wait until
    financials (which may be reading an older, pinned folder) is done with it."""
    import glint.pipeline.stages as stages_mod  # noqa: PLC0415
    from glint.core.filelock import LockTimeoutError  # noqa: PLC0415

    paths = Paths.from_settings(settings)
    real = stages_mod.build_financials
    seen: list[str] = []

    def other_worktree_prunes() -> None:
        try:
            with raw_lock(paths.raw_dir):  # no wait, like a prune that finds it busy
                seen.append("pruner got the lock")
        except LockTimeoutError:
            seen.append("pruner blocked")

    def spy(*args: object, **kwargs: object) -> object:
        t = threading.Thread(target=other_worktree_prunes)
        t.start()
        t.join()
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(stages_mod, "build_financials", spy)
    transport, _ = fake_sec()
    report = Runner(settings, stages(transport, FakeProvider()), clock=ticking_clock()).run()
    assert report.published, report.error
    assert seen == ["pruner blocked"]


class BrokenProvider(FakeProvider):
    def bars_for_date(self, day: date) -> list[Bar]:
        raise ValueError("maintenance page, not JSON")


def test_any_price_provider_error_is_a_warning(settings: Settings) -> None:
    """SPEC §4.1: prices failing never stops the fundamentals build, whatever the exception."""
    transport, _ = fake_sec()
    runner = Runner(settings, stages(transport, BrokenProvider()), clock=ticking_clock())
    report = runner.run()
    assert report.published, report.error
    prices = report.result("prices")
    assert prices is not None and prices.status == "warn"
    assert "ValueError: maintenance page" in prices.warnings[0]


def test_a_reused_companies_parquet_keeps_its_warning(settings: Settings) -> None:
    from glint.pipeline.stages import COMPANIES_STAMP, MISSING_KEY  # noqa: PLC0415

    paths = Paths.from_settings(settings)
    transport, _ = fake_sec()
    runner = Runner(settings, stages(transport, FakeProvider()), clock=ticking_clock())
    assert runner.run().published
    (folder,) = [p for p in paths.sec_raw.iterdir() if p.is_dir()]
    stamp = orjson.loads((folder / COMPANIES_STAMP).read_bytes())
    stamp[MISSING_KEY] = 3  # as if 3 CIKs had no submissions record when it was built
    (folder / COMPANIES_STAMP).write_bytes(orjson.dumps(stamp))
    again = runner.run(BuildOptions(no_download=True))
    run = {s.name: s for s in again.stages}["companies"]
    assert "reused" in (run.note or "") and run.result is not None
    assert run.result.warnings == [
        "3 CIKs have no submissions record (kind and foreign status unverified)"
    ]


def test_partial_run_after_its_sec_folder_was_pruned(settings: Settings) -> None:
    from glint.universe.build import COMPANIES_FILE  # noqa: PLC0415

    paths = Paths.from_settings(settings)
    transport, _ = fake_sec()
    runner = Runner(settings, stages(transport, FakeProvider()), clock=ticking_clock())
    assert runner.run().published
    (folder,) = [p for p in paths.sec_raw.iterdir() if p.is_dir()]
    (folder / COMPANIES_FILE).unlink()
    report = runner.run(only=["metrics"])
    assert report.status == "failed" and "has since been pruned" in (report.error or "")
