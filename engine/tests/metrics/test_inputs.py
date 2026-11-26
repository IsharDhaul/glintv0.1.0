"""Inputs frame: one TTM end and one MRQ date per company, year-ago lookups, FY ladder."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from glint.financials.concepts import load_concepts
from glint.metrics.inputs import build_inputs, period_ends, shift_years
from glint.metrics.primary import finalize_primary, listing_kind
from glint.universe.listed_classes import load_non_common_symbols
from tests.metrics.helpers import companies, fin

D = date
A = "0000000001"

ROWS = [
    # revenue reaches the latest TTM end; net income stops a quarter earlier
    (A, "revenue", "ttm", D(2026, 6, 30), 400),
    (A, "revenue", "ttm", D(2025, 6, 28), 350),  # 52/53-week drift: 2 days off a year
    (A, "net_income", "ttm", D(2026, 3, 31), 40),
    (A, "revenue", "q", D(2026, 6, 30), 100),
    (A, "diluted_shares", "q", D(2026, 6, 30), 10),
    (A, "diluted_shares", "q", D(2025, 6, 28), 9),
    # balance sheet: latest 2026-06-30, a year earlier 2025-07-20 (within ±45 days)
    (A, "equity", "mrq", D(2026, 6, 30), 200),
    (A, "equity", "mrq", D(2025, 7, 20), 180),
    (A, "shares_outstanding", "mrq", D(2026, 7, 25), 11),  # cover page: after the balance sheet
    # fiscal years: 2025, 2024 (52-week year), no 2023, then 2022
    (A, "revenue", "fy", D(2025, 12, 31), 380),
    (A, "revenue", "fy", D(2024, 12, 28), 330),
    (A, "revenue", "fy", D(2022, 12, 31), 250),
    (A, "gross_profit", "fy", D(2025, 12, 31), 150, True),
    (A, "total_assets", "fy", D(2025, 12, 31), 900),
]


def test_shift_years_leap_day() -> None:
    assert shift_years(D(2024, 2, 29), 1) == D(2023, 2, 28)
    assert shift_years(D(2025, 12, 31), 3) == D(2022, 12, 31)


def test_period_ends_are_company_level() -> None:
    ends = period_ends(fin(ROWS), load_concepts(), 45).row(0, named=True)
    assert ends["ttm_end"] == D(2026, 6, 30)  # latest across items, not per item
    assert ends["ttm_1y_end"] == D(2025, 6, 28)
    assert ends["mrq_end"] == D(2026, 6, 30)  # the share count's date doesn't count
    assert ends["mrq_1y_end"] == D(2025, 7, 20)
    assert ends["shares_as_of"] == D(2026, 7, 25)
    assert ends["q_end"] == D(2026, 6, 30)
    assert ends["q_1y_end"] == D(2025, 6, 28)
    assert ends["fy0_end"] == D(2025, 12, 31)
    assert ends["fy1_end"] == D(2024, 12, 28)
    assert ends["fy2_end"] is None  # skipped year: a gap, not a shift to 2022
    assert ends["fy3_end"] == D(2022, 12, 31)


def test_year_ago_outside_window_is_null() -> None:
    rows = [(A, "equity", "mrq", D(2026, 6, 30), 1), (A, "equity", "mrq", D(2025, 5, 1), 1)]
    ends = period_ends(fin(rows), load_concepts(), 45).row(0, named=True)
    assert ends["mrq_1y_end"] is None  # 60 days off


def test_build_inputs_values_and_derived_flags() -> None:
    frame = build_inputs(companies([{"cik": A}]), fin(ROWS), load_concepts())
    r = frame.row(0, named=True)
    assert r["revenue__ttm"] == 400
    assert r["revenue__ttm_1y"] == 350
    assert r["net_income__ttm"] is None  # not at the common TTM end
    assert r["net_income__last"] == D(2026, 3, 31)
    assert r["equity__mrq"] == 200 and r["equity__mrq_1y"] == 180
    assert r["diluted_shares__q"] == 10 and r["diluted_shares__q_1y"] == 9
    assert r["revenue__fy0"] == 380 and r["revenue__fy3"] == 250 and r["revenue__fy2"] is None
    assert r["gross_profit__fy0"] == 150 and r["gross_profit__fy0__d"] is True
    assert r["revenue__fy0__d"] is False
    assert r["total_assets__fy0"] == 900
    assert r["shares_outstanding__now"] == 11


def test_company_without_financials_keeps_its_row() -> None:
    frame = build_inputs(companies([{"cik": A}, {"cik": "0000000002"}]), fin(ROWS), load_concepts())
    r = frame.filter(pl.col("cik") == "0000000002").row(0, named=True)
    assert r["ttm_end"] is None and r["revenue__ttm"] is None


def test_primary_ticker_is_most_liquid_common_class() -> None:
    cs = companies([
        {"cik": A, "tickers": ["GOOGL", "GOOG"], "primary_ticker": "GOOGL", "exchange": "Nasdaq"},
        {"cik": "2", "tickers": ["ABLV", "ABLVW"], "primary_ticker": "ABLV", "exchange": "Nasdaq"},
        {"cik": "3", "tickers": ["BRK.B", "BRK.A"], "primary_ticker": "BRK.B", "exchange": "NYSE"},
        {"cik": "4", "tickers": ["NEW"], "primary_ticker": "NEW", "exchange": "NYSE"},
    ])  # fmt: skip
    stats = pl.DataFrame({
        "ticker": ["GOOGL", "GOOG", "ABLV", "ABLVW", "BRK.B", "BRK.A"],
        "avg_dollar_volume_3m": [5e9, 6e9, 1e6, 9e9, 2e9, 2e9],
    })  # fmt: skip
    out = finalize_primary(cs, stats)
    assert out["primary_ticker"].to_list() == ["GOOG", "ABLV", "BRK.B", "NEW"]
    # the warrant never wins; a tie keeps the provisional class; no prices keeps it too
    assert out["primary_ticker_provisional"].to_list() == ["GOOGL", "ABLV", "BRK.B", "NEW"]


def test_configured_non_common_symbol_is_never_primary() -> None:
    # Strive's 10-Q cover lists SATS as "15.00% Series A Perpetual SATS Preferred Stock"; it
    # trades more than the common (ASST), and has no suffix that marks it as a preferred
    cs = companies([
        {"cik": "0001920406", "tickers": ["ASST", "SATS", "SATA"], "primary_ticker": "SATS",
         "exchange": "Nasdaq"},
        {"cik": "5", "tickers": ["SATS"], "primary_ticker": "SATS", "exchange": "Nasdaq"},
        {"cik": "6", "tickers": ["ONLY", "PREF"], "primary_ticker": "PREF", "exchange": "NYSE"},
    ])  # fmt: skip
    stats = pl.DataFrame({
        "ticker": ["ASST", "SATS", "SATA"], "avg_dollar_volume_3m": [2.3e8, 7.2e8, 5e7],
    })  # fmt: skip
    non_common = {"0001920406": frozenset({"SATS", "SATA"}), "6": frozenset({"PREF"})}
    out = finalize_primary(cs, stats, non_common)
    # another company's SATS is unaffected; an unpriced common replaces a non-common provisional
    assert out["primary_ticker"].to_list() == ["ASST", "SATS", "ONLY"]
    assert (
        out["primary_ticker"].to_list() != finalize_primary(cs, stats)["primary_ticker"].to_list()
    )
    assert listing_kind("SATS", ["ASST", "SATS"], "Nasdaq", frozenset({"SATS"})) == "other"
    assert listing_kind("SATS", ["ASST", "SATS"], "Nasdaq") == "common"


def test_non_common_symbols_config_quotes_the_symbol(tmp_path: Path) -> None:
    assert load_non_common_symbols()["0001920406"] == frozenset({"SATS"})
    assert load_non_common_symbols()["0001831096"] == frozenset({"GEGGL"})
    bad = tmp_path / "share_classes.yaml"
    bad.write_text(
        "non_common_symbols:\n"
        "  - {cik: '0001920406', ticker: ASST, symbol: SATS, accn: '0001628280-26-071332',\n"
        "     source: s, quote: 'Class A common stock, $0.001 par value per share', checked_by: c}\n"
    )
    with pytest.raises(ValidationError, match="must differ and appear in the quote"):
        load_non_common_symbols(bad)
