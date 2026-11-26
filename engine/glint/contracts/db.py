"""Database contract: DDL for every table in §4.7, the build pointer, and `DB_SCHEMA_VERSION`.

A build records `DB_SCHEMA_VERSION` in `build_meta`. The API refuses to serve a build whose
version differs ("rebuild"). Bump it whenever a table's shape changes (§8.6).
"""

from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from glint.contracts.enums import Unit
from glint.contracts.metrics import MetricDefinition

DB_SCHEMA_VERSION = 4

# --- Build database (data/builds/<build_id>.duckdb) -------------------------------------------

BUILD_META = """
CREATE TABLE IF NOT EXISTS build_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
)"""
"""Keys: db_schema_version, build_id, synthetic, created_at, as_of_fundamentals, as_of_prices."""

COMPANIES = """
CREATE TABLE IF NOT EXISTS companies (
    cik VARCHAR PRIMARY KEY,               -- 10-digit, zero-padded
    name VARCHAR NOT NULL,
    tickers VARCHAR[] NOT NULL,
    primary_ticker VARCHAR,
    exchange VARCHAR,
    sic INTEGER,
    sic_description VARCHAR,
    sector VARCHAR NOT NULL,
    state_of_inc VARCHAR,
    fiscal_year_end VARCHAR,               -- MMDD, as SEC gives it
    filer_category VARCHAR,
    kind VARCHAR NOT NULL,                 -- operating|spac|fund|shell|no_common_equity|synthetic
    is_foreign_filer BOOLEAN NOT NULL,
    is_reit BOOLEAN NOT NULL,
    has_facts BOOLEAN NOT NULL,           -- false: tickers but no XBRL financial facts
    taxonomy VARCHAR,                      -- us-gaap | ifrs-full
    reporting_currency VARCHAR,
    last_annual_date DATE,
    last_quarterly_date DATE,
    nt_filing_12m BOOLEAN NOT NULL,
    fy_end_changed BOOLEAN NOT NULL,
    -- Up-C: an unlisted class paired with exchangeable units of the operating subsidiary, so
    -- market cap counts every cover-page common class (WT-01 detection, WT-03 share count).
    is_up_c BOOLEAN NOT NULL DEFAULT false,
    up_c_evidence VARCHAR,                 -- filing, classes and NCI % behind is_up_c
    -- Finance leases (ASC 842) in total_debt go by the filing's own word: the balance-sheet line
    -- the latest 10-Q (else 10-K) names for the lease liability (WT-01 reads it, WT-03 counts
    -- the lease unless that line is the debt tag already picked, WT-06 notes it).
    finance_lease_status VARCHAR,          -- 'stated' | 'not_stated'; NULL: no finance lease
    finance_lease_evidence VARCHAR         -- filing and the line(s) it names for the lease
)"""

FINANCIALS = """
CREATE TABLE IF NOT EXISTS financials (
    cik VARCHAR NOT NULL,
    line_item VARCHAR NOT NULL,
    basis VARCHAR NOT NULL,                -- fy | q | ttm | mrq
    period_end DATE NOT NULL,
    period_start DATE,                     -- null for instants
    value DOUBLE NOT NULL,
    unit VARCHAR NOT NULL,
    source_tag VARCHAR,                    -- null when derived
    source_accn VARCHAR,
    filed DATE,
    first_filed_value DOUBLE,
    first_filed_date DATE,
    derived BOOLEAN NOT NULL,
    PRIMARY KEY (cik, line_item, basis, period_end)
)"""

PRICE_STATS = """
CREATE TABLE IF NOT EXISTS price_stats (
    ticker VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    close DOUBLE,
    return_1m DOUBLE,
    return_3m DOUBLE,
    return_6m DOUBLE,
    return_12m DOUBLE,
    momentum_12_1 DOUBLE,
    high_52w DOUBLE,
    pct_from_52w_high DOUBLE,
    volatility_1y DOUBLE,
    avg_dollar_volume_3m DOUBLE,
    history_days INTEGER NOT NULL,
    PRIMARY KEY (ticker, as_of)
)"""

METRIC_NOTES = """
CREATE TABLE IF NOT EXISTS metric_notes (
    cik VARCHAR NOT NULL,
    metric_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,                 -- NoteCode
    message VARCHAR NOT NULL,
    PRIMARY KEY (cik, metric_id)
)"""

METRIC_HISTORY = """
CREATE TABLE IF NOT EXISTS metric_history (
    cik VARCHAR NOT NULL,
    metric_id VARCHAR NOT NULL,
    basis VARCHAR NOT NULL,                -- fy | ttm
    period_end DATE NOT NULL,
    value DOUBLE,
    PRIMARY KEY (cik, metric_id, basis, period_end)
)"""

FLAGS = """
CREATE TABLE IF NOT EXISTS flags (
    cik VARCHAR NOT NULL,
    flag_id VARCHAR NOT NULL,              -- FlagId
    question VARCHAR NOT NULL,
    evidence JSON NOT NULL,
    PRIMARY KEY (cik, flag_id)
)"""

PIPELINE_RUNS = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id VARCHAR PRIMARY KEY,
    started TIMESTAMPTZ NOT NULL,
    finished TIMESTAMPTZ,
    status VARCHAR NOT NULL,               -- running | ok | warn | failed
    stage_durations JSON NOT NULL,
    counts JSON NOT NULL,
    source_timestamps JSON NOT NULL,
    warnings JSON NOT NULL
)"""

# metrics_snapshot is wide: fixed columns plus one column per registry metric id.
SNAPSHOT_FIXED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("cik", "VARCHAR PRIMARY KEY"),
    ("as_of_fundamentals", "DATE"),
    ("as_of_prices", "DATE"),
    ("ticker", "VARCHAR NOT NULL"),
    ("name", "VARCHAR NOT NULL"),
    ("sector", "VARCHAR NOT NULL"),
    ("kind", "VARCHAR NOT NULL"),
    ("exchange", "VARCHAR"),
    ("is_foreign_filer", "BOOLEAN NOT NULL"),
    ("is_stale", "BOOLEAN NOT NULL"),
    ("has_facts", "BOOLEAN NOT NULL"),
)


def metric_column_type(unit: Unit) -> str:
    return "BOOLEAN" if unit is Unit.BOOL else "DOUBLE"


def metrics_snapshot_ddl(metrics: Iterable[MetricDefinition]) -> str:
    cols = [f"    {name} {sql}" for name, sql in SNAPSHOT_FIXED_COLUMNS]
    cols += [f"    {m.id} {metric_column_type(m.unit)}" for m in metrics]
    return "CREATE TABLE IF NOT EXISTS metrics_snapshot (\n" + ",\n".join(cols) + "\n)"


BUILD_TABLES: dict[str, str] = {
    "build_meta": BUILD_META,
    "companies": COMPANIES,
    "financials": FINANCIALS,
    "price_stats": PRICE_STATS,
    "metric_notes": METRIC_NOTES,
    "metric_history": METRIC_HISTORY,
    "flags": FLAGS,
    "pipeline_runs": PIPELINE_RUNS,
}
"""Every build table except `metrics_snapshot`, whose DDL depends on the registry."""

# --- Parquet datasets in GLINT_RAW_DIR (column name -> DuckDB type) -------------------------------

FACTS_RAW_COLUMNS: dict[str, str] = {
    "cik": "VARCHAR",
    "taxonomy": "VARCHAR",
    "tag": "VARCHAR",
    "unit": "VARCHAR",
    "start": "DATE",
    "end": "DATE",
    "val": "DOUBLE",
    "accn": "VARCHAR",
    "fy": "INTEGER",
    "fp": "VARCHAR",
    "form": "VARCHAR",
    "filed": "DATE",
    "frame": "VARCHAR",
}

PRICES_DAILY_COLUMNS: dict[str, str] = {
    "ticker": "VARCHAR",
    "date": "DATE",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "volume": "DOUBLE",
    "vwap": "DOUBLE",
}

# --- User database (data/user.duckdb, v1; the pipeline never opens it) -----------------------

USER_SAVED_SCREENS = """
CREATE TABLE IF NOT EXISTS saved_screens (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    screen_json JSON NOT NULL,
    created TIMESTAMPTZ NOT NULL,
    updated TIMESTAMPTZ NOT NULL
)"""

USER_SCREEN_RUNS = """
CREATE TABLE IF NOT EXISTS screen_runs (
    screen_id VARCHAR NOT NULL,
    build_id VARCHAR NOT NULL,
    tickers VARCHAR[] NOT NULL,
    counts JSON NOT NULL,
    PRIMARY KEY (screen_id, build_id)
)"""

USER_WATCHLISTS = """
CREATE TABLE IF NOT EXISTS watchlists (
    id VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    added_at TIMESTAMPTZ NOT NULL,
    note VARCHAR,
    PRIMARY KEY (id, ticker)
)"""

USER_TABLES: dict[str, str] = {
    "saved_screens": USER_SAVED_SCREENS,
    "screen_runs": USER_SCREEN_RUNS,
    "watchlists": USER_WATCHLISTS,
}


# --- Build pointer (data/current.json) ---------------------------------------------------------


class CurrentPointer(BaseModel):
    """`data/current.json`: which build the API serves. Replaced atomically on publish."""

    model_config = ConfigDict(extra="forbid")

    build_id: str
    path: str  # relative to GLINT_DB_DIR, e.g. "builds/<build_id>.duckdb"
    db_schema_version: int
    synthetic: bool
    created_at: datetime
