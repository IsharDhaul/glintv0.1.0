import duckdb

from glint.contracts.db import BUILD_TABLES, USER_TABLES, metrics_snapshot_ddl
from tests.contracts.test_screen import REGISTRY


def test_all_ddl_executes() -> None:
    con = duckdb.connect()
    for ddl in [*BUILD_TABLES.values(), *USER_TABLES.values(), metrics_snapshot_ddl(REGISTRY)]:
        con.execute(ddl)
    cols = {r[0]: r[1] for r in con.execute("DESCRIBE metrics_snapshot").fetchall()}
    assert cols["roic"] == "DOUBLE"
    assert cols["dps_no_cut_5y"] == "BOOLEAN"
    assert cols["cik"] == "VARCHAR"


def test_up_c_columns_default_for_producers_that_omit_them() -> None:
    """Synthetic builds and older producers insert companies without the Up-C columns."""
    con = duckdb.connect()
    con.execute(BUILD_TABLES["companies"])
    con.execute(
        "INSERT INTO companies (cik, name, tickers, sector, kind, is_foreign_filer, is_reit,"
        " has_facts, nt_filing_12m, fy_end_changed)"
        " VALUES ('1', 'X', ['X'], 'Technology', 'operating', false, false, true, false, false)"
    )
    assert con.execute("SELECT is_up_c, up_c_evidence FROM companies").fetchone() == (False, None)


def test_finance_lease_columns_are_null_for_producers_that_omit_them() -> None:
    con = duckdb.connect()
    con.execute(BUILD_TABLES["companies"])
    con.execute(
        "INSERT INTO companies (cik, name, tickers, sector, kind, is_foreign_filer, is_reit,"
        " has_facts, nt_filing_12m, fy_end_changed)"
        " VALUES ('1', 'X', ['X'], 'Technology', 'operating', false, false, true, false, false)"
    )
    row = con.execute("SELECT finance_lease_status, finance_lease_evidence FROM companies")
    assert row.fetchone() == (None, None)
