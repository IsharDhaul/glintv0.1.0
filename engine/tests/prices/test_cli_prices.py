from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import orjson
import pytest
from typer.testing import CliRunner

from glint.cli import app
from glint.core.paths import Paths
from glint.core.settings import get_settings
from glint.ingest.prices import cli as prices_cli
from glint.ingest.prices.models import Split
from glint.ingest.prices.provider import latest_requestable
from glint.ingest.prices.store import PriceStore
from tests.prices.helpers import FakeProvider, bar

runner = CliRunner()


@pytest.fixture
def raw(db_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp GLINT_RAW_DIR with no Massive key, whatever the developer's .env says."""
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    monkeypatch.setenv("GLINT_PRICE_PROVIDER", "massive")
    monkeypatch.setenv("COLUMNS", "200")  # rich wraps tables at the terminal width
    get_settings.cache_clear()
    yield db_dir.parent / "raw"
    get_settings.cache_clear()


def _write_universe(raw: Path) -> None:
    doc = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            [789019, "Microsoft", "MSFT", "Nasdaq"],
            [1067983, "Berkshire", "BRK-B", "NYSE"],
            [1, "Pink Sheet Co", "PINK", "OTC"],
        ],
    }
    folder = raw / "sec" / "2026-10-28"
    folder.mkdir(parents=True)
    (folder / "company_tickers_exchange.json").write_bytes(orjson.dumps(doc))


def test_ingest_backfill_with_coverage(raw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_universe(raw)
    fake = FakeProvider()
    seen: dict[str, Any] = {}

    def make(settings: Any, *, tickers: Any = (), force: Any = None) -> FakeProvider:
        seen["tickers"] = list(tickers)
        return fake

    monkeypatch.setattr(prices_cli, "make_provider", make)
    result = runner.invoke(app, ["ingest", "prices", "--backfill", "3"])
    assert result.exit_code == 0, result.output
    assert "provider: fake" in result.output
    assert "fetched 3 dates (6 bars), 0 already on disk" in result.output
    # AAPL + MSFT priced; BRK.B not (the fake only returns AAPL and MSFT); OTC not counted
    assert "2/3 common listings priced that day (66.7%)" in result.output
    assert seen["tickers"] == ["AAPL", "BRK.B", "MSFT"]
    reports = list((raw / "prices" / "reports").glob("coverage-*.json"))
    assert len(reports) == 1
    assert orjson.loads(reports[0].read_bytes())["common_without_price_recent"] == ["BRK.B"]

    again = runner.invoke(app, ["ingest", "prices", "--backfill", "3"])
    assert "fetched 0 dates (0 bars), 3 already on disk" in again.output


def test_fallback_says_so_and_needs_tickers(raw: Path) -> None:
    result = runner.invoke(app, ["ingest", "prices", "--backfill", "3"])
    assert result.exit_code == 1
    assert "FALLBACK: MASSIVE_API_KEY is not set" in result.output
    assert "needs a ticker list" in result.output


def test_date_and_backfill_are_exclusive(raw: Path) -> None:
    result = runner.invoke(app, ["ingest", "prices", "--date", "2026-10-27", "--backfill", "3"])
    assert result.exit_code != 0


def _seed(raw: Path) -> date:
    store = PriceStore(Paths.from_settings(get_settings()))
    last = latest_requestable()
    days = [last - timedelta(days=i) for i in range(30)][::-1]
    with store.writer():
        for i, d in enumerate(days):
            store.write_day(
                d, [bar("AAPL", d, 100.0 + i, 1_000.0), bar("BRK.B", d, 450.0)], source="massive"
            )
        store.merge_splits([Split("AAPL", days[-5], 1, 4)])
    return last


def test_price_shows_bars_stats_and_notes(raw: Path) -> None:
    last = _seed(raw)
    result = runner.invoke(app, ["price", "AAPL", "--days", "3"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert f"AAPL  price date {last}" in out
    assert "30 sessions on disk" in out
    assert "tier 2 market data" in out
    assert "price return only, excludes dividends" in out
    assert "return_1m" in out
    assert "INSUFFICIENT_HISTORY: return_3m needs 64 sessions of prices; has 30" in out
    assert "split " in out and "4-for-1" in out


def test_price_accepts_sec_style_symbol(raw: Path) -> None:
    _seed(raw)
    result = runner.invoke(app, ["price", "BRK-B"])
    assert result.exit_code == 0, result.output
    assert "BRK.B" in result.output


def test_price_unknown_ticker(raw: Path) -> None:
    _seed(raw)
    result = runner.invoke(app, ["price", "NOPE"])
    assert result.exit_code == 1
    assert "no price bars on disk" in result.output


def test_price_with_empty_store(raw: Path) -> None:
    result = runner.invoke(app, ["price", "AAPL"])
    assert result.exit_code == 1
    assert "glint ingest prices --backfill" in result.output
