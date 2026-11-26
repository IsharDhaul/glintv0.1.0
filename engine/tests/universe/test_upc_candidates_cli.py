"""`glint universe --up-c-candidates`: filtered on Glint's latest shares_outstanding."""

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import polars as pl
from typer.testing import CliRunner

from glint.cli import app
from glint.contracts.db import DB_SCHEMA_VERSION, CurrentPointer
from glint.ingest.sec.covers import ClassCount, Cover, cover_path
from glint.universe.build import COMPANIES_FILE, SCHEMA

runner = CliRunner()
AS_OF = date(2026, 11, 1)
# cik → ticker; every cover is Class A 60M + Class B 40M, unlisted B, no NCI % tagged
COMPANIES = {"0000000101": "AAA", "0000000102": "BBB", "0000000103": "CCC"}


def write_raw(raw: Path) -> None:
    folder = raw / "sec" / "2026-11-21"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"files": {}}')
    base = dict.fromkeys(SCHEMA)
    rows: list[dict[str, object]] = []
    for cik, tk in COMPANIES.items():
        accn = f"{cik}-26-000001"
        rows.append({
            **base, "cik": cik, "name": tk, "tickers": [tk], "primary_ticker": tk,
            "exchange": "NYSE", "kind": "operating", "is_foreign_filer": False, "is_reit": False,
            "has_facts": True, "is_up_c": False, "last_quarterly_date": date(2026, 11, 5),
            "last_quarterly_accn": accn,
        })  # fmt: skip
        c = Cover(
            cik, accn, "10-Q", date(2026, 11, 5), "x_htm.xml",
            [ClassCount("us-gaap:CommonClassAMember", 60e6, AS_OF),
             ClassCount("us-gaap:CommonClassBMember", 40e6, AS_OF)],
            {"us-gaap:CommonClassAMember": tk}, [],
        )  # fmt: skip
        path = cover_path(raw / "sec", cik, accn)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(c.to_json())
    pl.DataFrame(rows, schema=SCHEMA).write_parquet(folder / COMPANIES_FILE)


def write_build(data: Path) -> None:
    """AAA: Glint already counts A + B (98M, ratio 1.02). BBB: Glint counts Class A only
    (60M latest; an older 100M row must not win). CCC: no Glint count."""
    db = data / "builds" / "b1.duckdb"
    db.parent.mkdir(parents=True)
    with duckdb.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE financials (cik VARCHAR, line_item VARCHAR, period_end DATE, "
            "filed DATE, value DOUBLE)"
        )
        con.executemany(
            "INSERT INTO financials VALUES (?, ?, ?, ?, ?)",
            [
                ("0000000101", "shares_outstanding", date(2026, 9, 30), date(2026, 11, 5), 98e6),
                ("0000000102", "shares_outstanding", date(2025, 12, 31), date(2026, 2, 1), 100e6),
                ("0000000102", "shares_outstanding", date(2026, 9, 30), date(2026, 11, 5), 60e6),
                ("0000000103", "revenue", date(2026, 9, 30), date(2026, 11, 5), 1e9),
            ],
        )
    pointer = CurrentPointer(
        build_id="b1", path="builds/b1.duckdb", db_schema_version=DB_SCHEMA_VERSION,
        synthetic=False, created_at=datetime(2026, 11, 22, tzinfo=UTC),
    )  # fmt: skip
    (data / "current.json").write_text(pointer.model_dump_json())


def test_candidates_drop_covers_glint_already_counts(db_dir: Path) -> None:
    write_raw(db_dir.parent / "raw")
    write_build(db_dir)
    r = runner.invoke(app, ["universe", "--up-c-candidates"], terminal_width=250)
    assert r.exit_code == 0, r.output
    assert "Up-C review candidates: 2" in r.output and "1.05" in r.output
    assert "AAA" not in r.output
    assert "BBB" in r.output and "60,000,000" in r.output and "1.67x" in r.output
    assert "CCC" in r.output


def test_without_a_build_the_list_is_unfiltered(db_dir: Path) -> None:
    write_raw(db_dir.parent / "raw")
    r = runner.invoke(app, ["universe", "--up-c-candidates"], terminal_width=250)
    assert r.exit_code == 0, r.output
    assert "No published build" in r.output
    assert "Up-C review candidates: 3" in r.output and "unfiltered" in r.output
