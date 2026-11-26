"""`glint metrics TICKER [--explain id]` against a build written from the fixtures."""

from pathlib import Path

import duckdb
import polars as pl
import pytest
from typer.testing import CliRunner

from glint.cli import app
from glint.contracts.db import BUILD_TABLES
from glint.contracts.metrics import load_registry
from glint.metrics.io import insert_frame
from glint.metrics.stage import MetricsOutput, write_metrics

runner = CliRunner()


@pytest.fixture
def build(fixture_build: tuple[MetricsOutput, pl.DataFrame], db_dir: Path) -> Path:
    out, fin = fixture_build
    raw = db_dir.parent / "raw" / "sec" / "2026-10-29"
    raw.mkdir(parents=True)
    out.frame.select("cik", "last_annual_form").write_parquet(raw / "companies.parquet")
    db = db_dir / "builds" / "fixture.duckdb"
    db.parent.mkdir(parents=True)
    with duckdb.connect(str(db)) as con:
        for ddl in BUILD_TABLES.values():
            con.execute(ddl)
        insert_frame(con, "companies", out.frame.select(
            "cik", "name", "tickers", "primary_ticker", "exchange", "sector", "kind",
            "is_foreign_filer", "is_reit", "has_facts", "taxonomy", "reporting_currency",
            "last_annual_date", "last_quarterly_date", "nt_filing_12m", "fy_end_changed",
        ))  # fmt: skip
        insert_frame(con, "financials", fin)
        insert_frame(con, "price_stats", out.frame.select(
            pl.col("primary_ticker").alias("ticker"), pl.col("price_as_of").alias("as_of"),
            *(pl.col(c).alias(c.removeprefix("px__")) for c in out.frame.columns
              if c.startswith("px__")), "history_days",
        ).drop_nulls("as_of").unique("ticker"))  # fmt: skip
        con.executemany("INSERT INTO build_meta VALUES (?, ?)",
                        [["as_of_fundamentals", "2026-10-29"], ["as_of_prices", "2026-10-28"]])  # fmt: skip
        write_metrics(con, out, load_registry().live())
    return db


def test_company_table(build: Path) -> None:
    r = runner.invoke(app, ["metrics", "JPM", "--db", str(build), "--category", "valuation"],
                      env={"COLUMNS": "200"})  # fmt: skip
    assert r.exit_code == 0, r.output
    assert "JPMORGAN" in r.output.upper()
    assert "NOT_APPLICABLE_SECTOR" in r.output  # EV metrics for a bank
    assert "gross_margin" not in r.output  # --category valuation only


def test_explain_lists_inputs_with_sources(build: Path) -> None:
    r = runner.invoke(app, ["metrics", "AAPL", "--explain", "operating_margin", "--db", str(build)],
                      env={"COLUMNS": "220"})  # fmt: skip
    assert r.exit_code == 0, r.output
    assert "Formula:" in r.output and "operating_income_ttm" in r.output
    assert "revenue_ttm" in r.output and "Result:" in r.output
    assert "stored snapshot value differs" not in r.output


def test_explain_eps_shares_come_from_filings(build: Path) -> None:
    r = runner.invoke(app, ["metrics", "AAPL", "--explain", "eps_growth_yoy", "--db", str(build)],
                      env={"COLUMNS": "240"})  # fmt: skip
    assert r.exit_code == 0, r.output
    share_lines = [ln for ln in r.output.splitlines() if "diluted_shares" in ln]
    assert share_lines and not any("price_stats" in ln for ln in share_lines)
    assert any("WeightedAverageNumberOfDilutedSharesOutstanding" in ln for ln in share_lines)


def test_unknown_ticker_and_metric(build: Path) -> None:
    assert runner.invoke(app, ["metrics", "ZZZZ", "--db", str(build)]).exit_code == 1
    r = runner.invoke(app, ["metrics", "AAPL", "--explain", "nope", "--db", str(build)])
    assert r.exit_code == 2
