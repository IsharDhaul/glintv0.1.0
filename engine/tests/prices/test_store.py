from datetime import date

import polars as pl
import pytest

from glint.core.filelock import LockTimeoutError, raw_lock
from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.prices.models import Split
from glint.ingest.prices.splits import SplitIndex, adjust_for_splits
from glint.ingest.prices.store import NotLockedError, PriceStore
from tests.prices.helpers import bar

D1, D2, D3 = date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)


@pytest.fixture
def store(settings: Settings) -> PriceStore:
    return PriceStore(Paths.from_settings(settings))


def test_write_and_read_partitions(store: PriceStore) -> None:
    with store.writer():
        store.write_day(D1, [bar("MSFT", D1, 400.0), bar("AAPL", D1, 260.0)], source="massive")
        store.write_day(D2, [bar("AAPL", D2, 262.0)], source="massive")
    assert store.partition_path(D1).name == "part.parquet"
    assert store.partition_path(D1).parent.name == "date=2026-10-26"
    assert store.dates_on_disk() == [D1, D2]
    df = store.read_bars()
    assert df.columns == ["ticker", "date", "open", "high", "low", "close", "volume", "vwap"]
    assert df.select("ticker", "date", "close").rows() == [
        ("AAPL", D1, 260.0),
        ("AAPL", D2, 262.0),
        ("MSFT", D1, 400.0),
    ]
    assert store.read_bars(tickers=["MSFT"]).height == 1
    assert store.read_bars(start=D2).height == 1


def test_writes_need_the_lock(store: PriceStore) -> None:
    with pytest.raises(NotLockedError):
        store.write_day(D1, [bar("AAPL", D1, 1.0)], source="massive")
    with pytest.raises(NotLockedError):
        store.add_holiday(D1, source="test")


def test_writer_takes_raw_lock(store: PriceStore) -> None:
    with raw_lock(store.paths.raw_dir), pytest.raises(LockTimeoutError):  # noqa: SIM117
        with store.writer():
            pass


def test_rejects_empty_and_mismatched_days(store: PriceStore) -> None:
    with store.writer():
        with pytest.raises(ValueError, match="holiday"):
            store.write_day(D1, [], source="massive")
        with pytest.raises(ValueError, match="passed as"):
            store.write_day(D1, [bar("AAPL", D2, 1.0)], source="massive")


def test_no_temp_files_left(store: PriceStore) -> None:
    with store.writer():
        store.write_day(D1, [bar("AAPL", D1, 1.0)], source="massive")
    leftovers = [p for p in store.root.rglob("*") if p.name.endswith(".tmp")]
    assert leftovers == []


def test_stray_temp_partition_is_not_a_date(store: PriceStore) -> None:
    # a process killed mid-write leaves only a .tmp file: that date must still count as missing
    tmp = store.partition_path(D3).with_name("part.parquet.tmp")
    tmp.parent.mkdir(parents=True)
    tmp.write_bytes(b"half a file")
    assert store.dates_on_disk() == []


def test_holidays_are_recorded_once(store: PriceStore) -> None:
    with store.writer():
        store.add_holiday(date(2026, 1, 1), source="massive")
        store.add_holiday(date(2026, 1, 1), source="massive")
        store.add_holiday(date(2025, 12, 25), source="massive")
    assert store.holidays() == {date(2026, 1, 1), date(2025, 12, 25)}


def test_merge_splits_dedupes(store: PriceStore) -> None:
    s = Split("NVDA", date(2024, 6, 10), 1, 10, "forward_split")
    with store.writer():
        assert store.merge_splits([s]) == 1
        assert store.merge_splits([s, Split("X", date(2024, 1, 2), 10, 1)]) == 1
    df = store.load_splits()
    assert df.select("ticker", "execution_date").rows() == [
        ("X", date(2024, 1, 2)),
        ("NVDA", date(2024, 6, 10)),
    ]


TTSH_DAY = date(2025, 12, 16)
# Massive's real rows for Tile Shop's odd-lot transaction (cached 2025-08-20 response)
TTSH_LEGS = [
    Split("TTSH", TTSH_DAY, 1, 3000, "forward_split"),
    Split("TTSH", TTSH_DAY, 3000, 1, "reverse_split"),
]


def test_same_day_legs_are_both_kept(store: PriceStore) -> None:
    with store.writer():
        assert store.merge_splits(TTSH_LEGS) == 2
        assert store.merge_splits(TTSH_LEGS) == 0  # seen before
    raw = pl.read_parquet(store.splits_path)
    assert raw.select("split_from", "split_to").rows() == [(1.0, 3000.0), (3000.0, 1.0)]


def test_a_lost_leg_is_restored_by_a_later_merge(store: PriceStore) -> None:
    """The store kept one leg before this fix; merging the provider's rows again adds the other."""
    with store.writer():
        store.merge_splits(TTSH_LEGS[:1])
        assert store.merge_splits(TTSH_LEGS) == 1


def test_same_event_with_rounding_differences_is_one_row(store: PriceStore) -> None:
    """Massive's CRESY stock dividend is 1.00846; the same event as 1.008459562 is not new."""
    day = date(2025, 11, 28)
    with store.writer():
        store.merge_splits([Split("CRESY", day, 1, 1.00846, "stock_dividend")])
        assert store.merge_splits([Split("CRESY", day, 1, 1.008459562)]) == 0


def test_load_splits_nets_same_day_legs(store: PriceStore) -> None:
    with store.writer():
        store.merge_splits([*TTSH_LEGS, Split("NVDA", date(2024, 6, 10), 1, 10, "forward_split")])
    df = store.load_splits()
    assert df.rows() == [
        ("NVDA", date(2024, 6, 10), 1.0, 10.0, "forward_split"),
        ("TTSH", TTSH_DAY, 3000.0, 3000.0, "forward_split+reverse_split"),
    ]


def test_odd_lot_pair_does_not_adjust_prices(store: PriceStore) -> None:
    """Before this fix the kept forward leg divided every earlier TTSH close by 3,000."""
    before, after = date(2025, 12, 15), date(2025, 12, 17)
    with store.writer():
        store.merge_splits(TTSH_LEGS)
    bars = pl.DataFrame(
        {"ticker": ["TTSH", "TTSH"], "date": [before, after], "close": [3.6, 3.7],
         "volume": [1000.0, 900.0]},
    )  # fmt: skip
    adjusted = adjust_for_splits(bars, store.load_splits(), after)
    assert adjusted["adj_close"].to_list() == pytest.approx([3.6, 3.7])
    assert SplitIndex(store.load_splits()).split_between("TTSH", before, after) == 1.0


def test_empty_store_reads_cleanly(store: PriceStore) -> None:
    assert store.dates_on_disk() == []
    assert store.latest_date() is None
    assert store.read_bars().height == 0
    assert store.load_splits().schema["execution_date"] == pl.Date
