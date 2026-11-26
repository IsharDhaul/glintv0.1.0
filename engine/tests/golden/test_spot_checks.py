"""WT-11 metric spot-checks (spot_checks.csv): the sheet is current, and every hand-recomputed
value agrees with Glint within 0.5% or carries a note explaining the difference (brief step 2:
"20 spot-checks agree or are explained"). Unfilled rows are pending, never passed."""

import csv
from pathlib import Path

import pytest

from tests.golden.spotcheck import COLUMNS, PICKS, SHEET, read_sheet, sheet_rows

TOLERANCE = 0.005  # §5.8
ABS_TOLERANCE = 1e-4  # values near zero (BRK.B revenue growth): 0.01 pp


@pytest.fixture(scope="module")
def fresh(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], dict[str, str]]:
    rows = sheet_rows(tmp_path_factory.mktemp("spot") / "2026-10-29")
    return {(r["ticker"], r["metric_id"]): r for r in rows}


def test_sheet_columns_and_picks() -> None:
    with SHEET.open(newline="") as f:
        assert next(csv.reader(f)) == COLUMNS
    assert [(r["ticker"], r["metric_id"]) for r in read_sheet()] == PICKS
    assert len(PICKS) == 20


def test_sheet_is_current(fresh: dict[tuple[str, str], dict[str, str]]) -> None:
    """Glint's columns match a fresh fixture build (else: python -m tests.golden.spotcheck --write)."""
    for r in read_sheet():
        new = fresh[(r["ticker"], r["metric_id"])]
        for k in ("glint_value", "definition", "inputs", "period_end"):
            assert r[k] == new[k], f"{r['ticker']} {r['metric_id']} {k} changed: rerun --write"


@pytest.mark.parametrize(
    "row", read_sheet(Path(SHEET)), ids=lambda r: f"{r['ticker']}-{r['metric_id']}"
)
def test_spot_check(row: dict[str, str]) -> None:
    if not row["your_value"].strip():
        pytest.skip("pending: recompute by hand from the inputs and the filing")
    assert row["verified_by"].strip() and row["verified_on"].strip(), "who checked it, and when"
    if not row["glint_value"]:
        assert row["note"].strip(), "Glint has no value: say why (n/m, not reported…)"
        return
    mine, glint = float(row["your_value"]), float(row["glint_value"])
    agrees = abs(mine - glint) <= max(ABS_TOLERANCE, TOLERANCE * abs(glint))
    assert agrees or row["note"].strip(), (
        f"{mine} vs Glint {glint}: investigate with `glint metrics {row['ticker']} --explain "
        f"{row['metric_id']}` and explain it in `note`"
    )
