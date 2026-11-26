"""Hand-verified metric values (tests/golden/golden_values.csv, metric rows) vs the FY points the
stage writes to metric_history, on the committed fixtures. An empty `expected` means the metric
must be null for that year (the reason is in `where_in_filing`)."""

import csv
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from _pytest.mark import ParameterSet

from glint.contracts.metrics import load_registry
from glint.metrics.stage import MetricsOutput

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "golden_values.csv"
TOLERANCE = 0.005  # §5.8
PENDING: dict[tuple[str, str], str] = {}  # (ticker, metric) → reason, run as strict xfails


NOT_IN_FIXTURES = {
    # The committed XOM fixture is the new holding-company CIK only; FY2025 lives under the
    # predecessor CIK 34088, which the real build merges (WT-03) but the fixture set doesn't hold.
    "XOM": "XOM FY2025 is under predecessor CIK 34088, absent from the fixtures (real build only)",
}


def _rows() -> list[ParameterSet]:
    reg = load_registry()
    with GOLDEN.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["item"] in reg]
    return [
        pytest.param(
            r,
            id=f"{r['ticker']}-{r['item']}",
            marks=[pytest.mark.xfail(reason=PENDING[(r["ticker"], r["item"])], strict=True)]
            if (r["ticker"], r["item"]) in PENDING
            else [],
        )
        for r in rows
    ]


@pytest.mark.parametrize("row", _rows())
def test_golden_metric(
    fixture_build: tuple[MetricsOutput, pl.DataFrame], row: dict[str, str]
) -> None:
    if row["ticker"] in NOT_IN_FIXTURES:
        pytest.skip(NOT_IN_FIXTURES[row["ticker"]])
    out = fixture_build[0]
    cik = out.frame.filter(pl.col("tickers").list.contains(row["ticker"]))["cik"][0]
    hit = out.history.filter(
        (pl.col("cik") == cik)
        & (pl.col("metric_id") == row["item"])
        & (pl.col("basis") == "fy")
        & (pl.col("period_end") == date.fromisoformat(row["period_end"]))
    )
    if row["expected"] == "":
        assert hit.is_empty(), "expected null"
        return
    assert hit.height == 1, "no FY value"
    assert hit["value"][0] == pytest.approx(float(row["expected"]), rel=TOLERANCE)
