from datetime import date
from pathlib import Path

import orjson
import pytest

from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.ingest.prices.coverage import (
    UniverseTicker,
    coverage_report,
    load_universe,
    universe_from_tickers_doc,
)
from glint.ingest.prices.store import bars_frame
from glint.ingest.prices.symbols import (
    canonical_from_massive,
    canonical_from_sec,
    canonical_from_yahoo,
    is_common_listing,
    to_massive,
    to_yahoo,
)
from tests.prices.helpers import bar

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sec" / "company_tickers_exchange.json"
DAY = date(2026, 10, 28)
PREV = date(2026, 10, 27)


# Spellings as observed in real Massive and SEC files (2026-10-28/29).
@pytest.mark.parametrize(
    ("canonical", "massive", "yahoo", "sec"),
    [
        ("AAPL", "AAPL", "AAPL", "AAPL"),
        ("BRK.B", "BRK.B", "BRK-B", "BRK-B"),
        ("BF.A", "BF.A", "BF-A", "BF-A"),
        ("AAC.WS", "AAC.WS", "AAC-WT", "AAC-WT"),
        ("AAC.U", "AAC.U", "AAC-UN", "AAC-UN"),
        ("ABR.PD", "ABRpD", "ABR-PD", "ABR-PD"),
        ("TY.P", "TYp", "TY-P", "TY-P"),
        ("SOUL.R", "SOULr", "SOUL-R", "SOUL-RI"),
    ],
)
def test_symbol_round_trips(canonical: str, massive: str, yahoo: str, sec: str) -> None:
    assert canonical_from_massive(massive) == canonical
    assert to_massive(canonical) == massive
    assert canonical_from_yahoo(yahoo) == canonical
    assert to_yahoo(canonical) == yahoo
    assert canonical_from_sec(sec) == canonical


@pytest.mark.parametrize(
    ("ticker", "exchange", "common"),
    [
        ("AAPL", "Nasdaq", True),
        ("BRK.B", "NYSE", True),
        ("BF.A", "NYSE", True),
        ("AGM.A", "NYSE", True),
        ("AAC.WS", "NYSE", False),
        ("AAC.U", "NYSE", False),
        ("ABR.PD", "NYSE", False),
        ("TY.P", "NYSE", False),
        ("SOUL.R", "Nasdaq", False),
        ("BANFP", "Nasdaq", False),  # Nasdaq fifth letter P: preferred
        ("BCTXZ", "Nasdaq", False),  # fifth letter Z: miscellaneous (here a warrant)
        ("GOOGL", "Nasdaq", True),  # fifth letter L: a share class, not a marker
        ("ABCDW", "NYSE", True),  # the fifth-letter rule is Nasdaq's only
        ("MSGK.WI", "NYSE", False),  # when issued
        ("NE.WTA", "NYSE", False),  # warrant series A
    ],
)
def test_is_common_listing(ticker: str, exchange: str, common: bool) -> None:
    assert is_common_listing(ticker, exchange) is common


def test_universe_from_real_sec_fixture() -> None:
    universe = universe_from_tickers_doc(orjson.loads(FIXTURE.read_bytes()))
    tickers = {u.ticker for u in universe}
    assert {"AAPL", "BRK.B", "GOOG", "GOOGL"} <= tickers
    assert all(u.exchange in {"NYSE", "Nasdaq", "NYSE American"} for u in universe)


def test_load_universe_picks_newest_dated_folder(settings: Settings) -> None:
    paths = Paths.from_settings(settings)
    doc = {"fields": ["cik", "name", "ticker", "exchange"], "data": [[1, "A Co", "AAA", "NYSE"]]}
    newer = {"fields": doc["fields"], "data": [[2, "B Co", "BBB-A", "Nasdaq"]]}
    for folder, body in (("2026-10-27", doc), ("2026-10-28", newer)):
        (paths.sec_raw / folder).mkdir(parents=True)
        (paths.sec_raw / folder / "company_tickers_exchange.json").write_bytes(orjson.dumps(body))
    loaded = load_universe(paths)
    assert loaded is not None
    assert [u.ticker for u in loaded[0]] == ["BBB.A"]
    assert loaded[1].parent.name == "2026-10-28"


def test_load_universe_absent(settings: Settings) -> None:
    assert load_universe(Paths.from_settings(settings)) is None


def test_coverage_report() -> None:
    universe = [
        UniverseTicker("AAPL", "Nasdaq"),
        UniverseTicker("BRK.B", "NYSE"),
        UniverseTicker("THIN", "NYSE"),  # traded yesterday, not today
        UniverseTicker("GONE", "NYSE"),  # no recent bars at all
        UniverseTicker("ABR.PD", "NYSE"),  # preferred: counted separately
        UniverseTicker("AAC.WS", "NYSE"),
    ]
    bars = bars_frame(
        [
            bar("AAPL", DAY, 260.0, 1e6),
            bar("BRK.B", DAY, 450.0, 1e5),
            bar("ABR.PD", DAY, 20.0, 1e3),
            bar("THIN", PREV, 3.0, 10),
            bar("AAPL", PREV, 259.0, 1e6),
            bar("SPY", DAY, 600.0, 1e7),  # ETF: priced, not in the universe
            bar("QQQ", DAY, 500.0, 1e7),
        ]
    )
    r = coverage_report(universe, bars, DAY, source="sec/2026-10-29")
    assert r["common_listings"] == 4
    assert (r["priced_latest"], r["coverage_latest"]) == (2, 0.5)
    assert (r["priced_recent"], r["coverage_recent"]) == (3, 0.75)
    assert r["recent_sessions"] == 2
    assert r["common_without_price_recent"] == ["GONE"]
    assert r["common_without_price_latest_only"] == ["THIN"]
    assert (r["other_listings"], r["other_listings_priced_latest"]) == (2, 1)
    assert [x["ticker"] for x in r["prices_not_in_universe_top50"]] == ["SPY", "QQQ"]
    assert r["prices_not_in_universe_count"] == 2
    assert r["by_exchange"]["NYSE"] == {
        "common_listings": 3,
        "priced_latest": 1,
        "priced_recent": 2,
    }


def test_coverage_empty_universe() -> None:
    r = coverage_report([], bars_frame([bar("SPY", DAY, 1.0)]), DAY)
    assert r["coverage_latest"] is None
    assert r["coverage_recent"] is None
