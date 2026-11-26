from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from glint.cli import app
from glint.universe.build import COMPANIES_FILE, SCHEMA

runner = CliRunner()


def write_companies(raw: Path) -> None:
    folder = raw / "sec" / "2026-10-29"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"files": {}}')
    base = dict.fromkeys(SCHEMA)
    rows = [
        {**base, "cik": "0001067983", "name": "BERKSHIRE HATHAWAY INC", "tickers": ["BRK.B", "BRK.A"],
         "primary_ticker": "BRK.B", "exchange": "NYSE", "sector": "Insurance", "kind": "operating",
         "is_foreign_filer": False, "is_reit": False, "has_facts": True},
        {**base, "cik": "0001046179", "name": "TAIWAN SEMICONDUCTOR", "tickers": ["TSM", "TSMWF"],
         "primary_ticker": "TSM", "exchange": "NYSE", "sector": "Technology", "kind": "operating",
         "is_foreign_filer": True, "is_reit": False, "has_facts": True},
        {**base, "cik": "0001999999", "name": "Otc Co", "tickers": ["OTCC"], "primary_ticker": "OTCC",
         "exchange": "OTC", "sector": "Unclassified", "kind": "operating",
         "is_foreign_filer": False, "is_reit": False, "has_facts": False},
        {**base, "cik": "0001276187", "name": "Energy Transfer LP", "tickers": ["ET", "ET.PI"],
         "primary_ticker": "ET", "exchange": "TXSE", "sector": "Energy", "kind": "operating",
         "is_foreign_filer": False, "is_reit": False, "has_facts": True},
    ]  # fmt: skip
    pl.DataFrame(rows, schema=SCHEMA).write_parquet(folder / COMPANIES_FILE)


def test_summary(db_dir: Path) -> None:
    write_companies(db_dir.parent / "raw")
    r = runner.invoke(app, ["universe", "--summary"])
    assert r.exit_code == 0, r.output
    assert "4 CIKs" in r.output
    assert "Default universe (NYSE/Nasdaq/NYSE American/TXSE, operating, has facts): 3" in r.output
    assert "CIKs with no XBRL financial facts: 1" in r.output
    assert "Insurance" in r.output and "foreign" in r.output


def test_lookup_by_any_class_and_sec_spelling(db_dir: Path) -> None:
    write_companies(db_dir.parent / "raw")
    for t in ("BRK.B", "brk.a", "BRK-A"):
        r = runner.invoke(app, ["universe", t])
        assert r.exit_code == 0, r.output
        assert "BERKSHIRE HATHAWAY INC" in r.output and "0001067983" in r.output


def test_unknown_ticker_and_missing_build(db_dir: Path) -> None:
    r = runner.invoke(app, ["universe", "AAPL"])
    assert r.exit_code == 1 and "glint ingest sec" in r.output
    write_companies(db_dir.parent / "raw")
    r = runner.invoke(app, ["universe", "NOPE"])
    assert r.exit_code == 1 and "unknown ticker" in r.output
