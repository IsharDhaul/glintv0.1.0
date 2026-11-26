"""DuckDB ↔ polars through temporary parquet files (pyarrow isn't a dependency; WT-03 writes the
same way)."""

import tempfile
from pathlib import Path

import duckdb
import polars as pl


def read_sql(
    con: duckdb.DuckDBPyConnection, sql: str, params: list[object] | None = None
) -> pl.DataFrame:
    with tempfile.TemporaryDirectory(prefix="glint-read-") as tmp:
        path = Path(tmp) / "q.parquet"
        con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet)", params or [])
        return pl.read_parquet(path)


def insert_frame(con: duckdb.DuckDBPyConnection, table: str, frame: pl.DataFrame) -> int:
    """Append `frame` to `table` by column name. Returns the row count."""
    if frame.is_empty():
        return 0
    with tempfile.TemporaryDirectory(prefix="glint-write-") as tmp:
        path = Path(tmp) / "rows.parquet"
        frame.write_parquet(path)
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM read_parquet(?)", [str(path)])
    return frame.height
