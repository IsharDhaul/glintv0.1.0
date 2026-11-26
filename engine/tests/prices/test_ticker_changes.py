"""Price history follows the company (CIK) across a ticker change: TCBI → TXCP on 2026-11-09."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from glint.cli import app
from glint.core.errors import ContractError
from glint.core.paths import Paths
from glint.core.settings import Settings, get_settings
from glint.ingest.prices.models import Split
from glint.ingest.prices.splits import adjust_for_splits
from glint.ingest.prices.stats import Windows, price_stats
from glint.ingest.prices.store import PriceStore
from glint.ingest.prices.ticker_changes import (
    TickerChange,
    follow_changes,
    load_ticker_changes,
    renamed_to,
)
from tests.prices.helpers import bar

CHANGE_DAY = date(2026, 11, 9)  # a Monday
BEFORE = [date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
AFTER = [date(2026, 11, 9), date(2026, 11, 10)]
TCBI_TXCP = TickerChange(
    cik="0001077428", old="TCBI", new="TXCP", effective=CHANGE_DAY,
    name="Texas Capital Bancshares", evidence="test", added=date(2026, 10, 29),
)  # fmt: skip


def write(store: PriceStore, days: list[date], symbol: str, first_close: float) -> None:
    with store.writer():
        for i, d in enumerate(days):
            store.write_day(
                d, [bar(symbol, d, first_close + i), bar("AAPL", d, 300.0)], source="massive"
            )


def test_config_has_texas_capital() -> None:
    changes = load_ticker_changes()
    tc = next(c for c in changes if c.old == "TCBI")
    assert (tc.cik, tc.new, tc.effective) == ("0001077428", "TXCP", CHANGE_DAY)


def test_store_loads_the_config_by_default(settings: Settings) -> None:
    changes = PriceStore(Paths.from_settings(settings)).ticker_changes
    assert ("TCBI", "TXCP") in [(c.old, c.new) for c in changes]


def test_history_follows_the_company_after_the_change(settings: Settings) -> None:
    store = PriceStore(Paths.from_settings(settings), [TCBI_TXCP])
    write(store, BEFORE, "TCBI", 100.0)
    write(store, AFTER, "TXCP", 103.0)

    txcp = store.read_bars(tickers=["TXCP"])
    assert txcp.select("ticker", "date", "close").rows() == [
        ("TXCP", d, c) for d, c in zip(BEFORE + AFTER, [100.0, 101.0, 102.0, 103.0, 104.0], strict=True)
    ]  # fmt: skip
    everything = store.read_bars()
    assert "TCBI" not in everything["ticker"].to_list()
    assert everything.filter(pl.col("ticker") == "TXCP").height == 5

    # Stats see one 5-session series: return over 4 sessions uses TCBI's first close.
    w = Windows(m1=4, m3=4, m6=4, m12=4, high=5, vol=4, adv=5, annualize=252)
    as_of = AFTER[-1]
    adjusted = adjust_for_splits(txcp, store.load_splits(), as_of)
    stats = price_stats(adjusted, as_of, w).stats.row(0, named=True)
    assert stats["ticker"] == "TXCP" and stats["history_days"] == 5
    assert stats["return_1m"] == pytest.approx(104.0 / 100.0 - 1)
    assert stats["avg_dollar_volume_3m"] == pytest.approx(102.0 * 1000.0)


def test_nothing_is_relabelled_before_the_change_trades(settings: Settings) -> None:
    store = PriceStore(Paths.from_settings(settings), [TCBI_TXCP])
    write(store, BEFORE, "TCBI", 100.0)  # newest date on disk is 2026-11-06
    assert store.read_bars(tickers=["TCBI"]).height == 3
    assert store.read_bars(tickers=["TXCP"]).height == 0
    assert store.active_changes() == []


def test_splits_follow_the_change_and_raw_files_keep_the_traded_symbol(
    settings: Settings,
) -> None:
    store = PriceStore(Paths.from_settings(settings), [TCBI_TXCP])
    write(store, BEFORE, "TCBI", 100.0)
    write(store, AFTER, "TXCP", 103.0)
    with store.writer():
        store.merge_splits([Split("TCBI", BEFORE[1], 1, 2)])
        store.merge_splits([Split("AAPL", BEFORE[1], 1, 4)])  # merging re-reads the raw file
    assert store.load_splits().filter(pl.col("ticker") == "TXCP").height == 1
    raw = pl.read_parquet(store.splits_path)
    assert sorted(raw["ticker"].to_list()) == ["AAPL", "TCBI"]
    raw_bars = pl.read_parquet(store.partition_path(BEFORE[0]))
    assert "TCBI" in raw_bars["ticker"].to_list()

    adjusted = adjust_for_splits(store.read_bars(tickers=["TXCP"]), store.load_splits(), AFTER[-1])
    assert adjusted["split_factor"].to_list() == [2.0, 1.0, 1.0, 1.0, 1.0]


def test_new_symbol_rows_before_the_change_are_not_this_company() -> None:
    """A symbol used by another security before the change doesn't leak into the history."""
    bars = pl.DataFrame(
        {
            "ticker": ["TXCP", "TCBI", "TXCP", "TCBI"],
            "date": [BEFORE[0], BEFORE[0], AFTER[0], AFTER[0]],
            "close": [5.0, 100.0, 103.0, 7.0],
        }
    )
    out = follow_changes(bars, [TCBI_TXCP]).sort("ticker", "date")
    assert out.rows() == [
        ("TCBI", AFTER[0], 7.0),  # the old symbol reused after the change: left alone
        ("TXCP", BEFORE[0], 100.0),
        ("TXCP", AFTER[0], 103.0),
    ]


def test_chained_changes_and_renamed_to() -> None:
    later = TCBI_TXCP.model_copy(
        update={"old": "TXCP", "new": "TXCB", "effective": date(2027, 3, 1)}
    )
    assert renamed_to("TCBI", [TCBI_TXCP, later]) == later
    assert renamed_to("TCBI", [TCBI_TXCP]) == TCBI_TXCP
    assert renamed_to("AAPL", [TCBI_TXCP]) is None


def test_duplicate_change_is_rejected(tmp_path: Path) -> None:
    entry = """  - {cik: "0001077428", old: TCBI, new: TXCP, effective: 2026-11-09,
     name: x, evidence: x, added: 2026-10-29}
"""
    path = tmp_path / "ticker_changes.yaml"
    path.write_text("changes:\n" + entry + entry)
    with pytest.raises(ContractError, match="changes twice"):
        load_ticker_changes(path)


def test_glint_price_old_symbol_points_to_the_new_one(
    db_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    get_settings.cache_clear()
    store = PriceStore(Paths.from_settings(get_settings()), [TCBI_TXCP])
    write(store, BEFORE, "TCBI", 100.0)
    write(store, AFTER, "TXCP", 103.0)
    result = CliRunner().invoke(app, ["price", "TCBI"])
    assert result.exit_code == 0, result.output
    assert "TCBI became TXCP on 2026-11-09 (same company, CIK 0001077428)" in result.output
    assert "TXCP  price date 2026-11-10" in result.output
    assert "5 sessions on disk" in result.output
