"""Write `financials` rows into a build database (DDL from contracts/db.py)."""

import tempfile
from collections.abc import Iterable
from dataclasses import fields
from operator import attrgetter
from pathlib import Path

import duckdb
import polars as pl

from glint.contracts.db import FINANCIALS
from glint.financials.normalize import FinancialRow

COLUMNS = tuple(f.name for f in fields(FinancialRow))
SCHEMA: dict[str, pl.DataType] = {
    "cik": pl.String(),
    "line_item": pl.String(),
    "basis": pl.String(),
    "period_end": pl.Date(),
    "period_start": pl.Date(),
    "value": pl.Float64(),
    "unit": pl.String(),
    "source_tag": pl.String(),
    "source_accn": pl.String(),
    "filed": pl.Date(),
    "first_filed_value": pl.Float64(),
    "first_filed_date": pl.Date(),
    "derived": pl.Boolean(),
}


_AS_TUPLE = attrgetter(*COLUMNS)


def rows_frame(rows: Iterable[FinancialRow]) -> pl.DataFrame:
    data = list(map(_AS_TUPLE, rows))
    return pl.DataFrame(data, schema=SCHEMA, orient="row").sort(
        "cik", "line_item", "basis", "period_end"
    )


def write_financials(con: duckdb.DuckDBPyConnection, rows: Iterable[FinancialRow]) -> int:
    """Create the table if needed and append rows, in a stable order. Returns the row count.

    Rows go through a temporary parquet file: DuckDB reads polars frames only via pyarrow.
    """
    con.execute(FINANCIALS)
    frame = rows_frame(rows)
    cols = ", ".join(COLUMNS)
    with tempfile.TemporaryDirectory(prefix="glint-financials-") as tmp:
        path = Path(tmp) / "rows.parquet"
        frame.write_parquet(path)
        con.execute(
            f"INSERT INTO financials ({cols}) SELECT {cols} FROM read_parquet(?)", [str(path)]
        )
    return frame.height
