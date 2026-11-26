from typing import Any

import orjson
import pytest

from glint.contracts.enums import Exchange
from glint.fixtures.sec import FIXTURE_DIR
from glint.universe.tickers import (
    build_ticker_map,
    canonical_symbol,
    is_common,
    normalize_exchange,
    ticker_index,
)

FIELDS = ["cik", "name", "ticker", "exchange"]


def tmap(*rows: list[Any]) -> dict[str, Any]:
    return build_ticker_map({"fields": FIELDS, "data": list(rows)})


@pytest.mark.parametrize(
    ("sec", "canon"),
    [("BRK-B", "BRK.B"), ("AAPL", "AAPL"), ("jpm-pc", "JPM.PC"), ("AAC-WT", "AAC.WT")],
)
def test_canonical_symbol(sec: str, canon: str) -> None:
    assert canonical_symbol(sec) == canon


@pytest.mark.parametrize(
    ("sec", "common"),
    [("BRK-B", True), ("BRK-A", True), ("GOOGL", True), ("JPM-PC", False), ("JPM-P", False),
     ("AAC-WT", False), ("AAC-UN", False), ("XYZ-RI", False), ("XYZ-U", False), ("XYZ-WS", False)],
)  # fmt: skip
def test_is_common(sec: str, common: bool) -> None:
    assert is_common(sec) is common


def test_exchange_normalization() -> None:
    assert normalize_exchange("Nasdaq") is Exchange.NASDAQ
    assert normalize_exchange("NYSE") is Exchange.NYSE
    assert normalize_exchange("OTC") is Exchange.OTC
    assert normalize_exchange("TXSE") is Exchange.TXSE
    assert normalize_exchange("LSE") is None
    assert normalize_exchange(None) is None


def test_share_classes_map_to_one_cik_from_fixture() -> None:
    doc = orjson.loads((FIXTURE_DIR / "company_tickers_exchange.json").read_bytes())
    m = build_ticker_map(doc)
    idx = ticker_index(m)
    assert idx["BRK.A"] == idx["BRK.B"] == "0001067983"
    assert idx["GOOG"] == idx["GOOGL"] == "0001652044"
    brk = m["0001067983"]
    assert brk.sec_symbols[:2] == ["BRK-B", "BRK-A"]
    assert brk.primary.ticker == "BRK.B"
    assert m["0001652044"].primary.ticker == "GOOGL"


def test_primary_skips_warrants_units_and_otc() -> None:
    m = tmap(
        [5, "Spac", "AAC-WT", "NYSE"], [5, "Spac", "AAC-UN", "NYSE"], [5, "Spac", "AAC", "NYSE"],
        [6, "TSMC", "TSMWF", "OTC"], [6, "TSMC", "TSM", "NYSE"],
        [7, "Pref only", "XYZ-PA", "NYSE"],
    )  # fmt: skip
    assert m["0000000005"].primary.ticker == "AAC"
    assert m["0000000005"].tickers == ["AAC.WT", "AAC.UN", "AAC"]
    assert m["0000000006"].primary.ticker == "TSM"
    assert m["0000000006"].primary.exchange is Exchange.NYSE
    assert m["0000000007"].primary.ticker == "XYZ.PA"  # nothing common: fall back to first


def test_nasdaq_style_derived_symbols_are_not_primary() -> None:
    m = tmap(
        [11, "Spac", "ABLVW", "Nasdaq"], [11, "Spac", "ABLV", "Nasdaq"],
        [12, "Reit", "AGNCP", "Nasdaq"], [12, "Reit", "AGNC", "Nasdaq"],
        [13, "Real 4-letter", "GOOGW", "Nasdaq"],  # no sibling root: stays common
    )  # fmt: skip
    assert m["0000000011"].primary.ticker == "ABLV"
    assert m["0000000012"].primary.ticker == "AGNC"
    assert m["0000000013"].primary.ticker == "GOOGW"


def test_otc_only_and_unknown_exchanges_are_kept() -> None:
    m = tmap([8, "Otc Co", "OTCC", "OTC"], [9, "Odd Co", "ODD", "LSE"], [10, "New", "NEW", None])
    assert m["0000000008"].primary.exchange is Exchange.OTC
    odd = m["0000000009"].primary
    assert odd.exchange is None and odd.sec_exchange == "LSE"
    assert m["0000000010"].primary.exchange is None


def test_txse_listing_is_a_default_exchange() -> None:
    m = tmap([1276187, "Energy Transfer LP", "ET", "TXSE"], [1276187, "Energy Transfer LP", "ET-PI", "TXSE"],
             [9, "Dual Co", "DUOF", "OTC"], [9, "Dual Co", "DUO", "TXSE"])  # fmt: skip
    et = m["0001276187"].primary
    assert et.ticker == "ET" and et.exchange is Exchange.TXSE
    duo = m["0000000009"].primary
    assert duo.ticker == "DUO" and duo.exchange is Exchange.TXSE  # TXSE outranks OTC


def test_duplicate_rows_collapse() -> None:
    m = tmap([1, "A", "AAA", "NYSE"], [1, "A", "AAA", "NYSE"])
    assert m["0000000001"].tickers == ["AAA"]
