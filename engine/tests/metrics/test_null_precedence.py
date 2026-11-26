"""Which null reason a metric reports when several inputs are null (`glint.metrics.core`):
INSUFFICIENT_HISTORY, then n/m, then STALE_DATA, then MISSING_INPUT; ties go to the first input."""

from datetime import date

import polars as pl
import pytest

from glint.contracts.enums import NoteCode as C
from glint.metrics.core import In, column_in, result
from tests.metrics.frames import cell, run

D = date
TTM_END = D(2026, 6, 30)
FY_ENDS = [D(2025, 12, 31), D(2024, 12, 31)]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        # S (like SEV, pre-revenue): two fiscal years, revenue never tagged
        *(("S", "net_income", "fy", e, -10) for e in FY_ENDS),
        # I: TTM filed, but neither operating income nor interest expense is tagged
        ("I", "revenue", "ttm", TTM_END, 100),
        ("I", "net_income", "ttm", TTM_END, 5),
        # K: the same, with total debt tagged as zero (positive evidence of no interest)
        ("K", "revenue", "ttm", TTM_END, 100),
        ("K", "net_income", "ttm", TTM_END, 5),
        ("K", "total_debt", "mrq", TTM_END, 0),
    ]
    return run(rows, [{"cik": c} for c in "SIK"])


def test_sev_insufficient_history_beats_missing_input(out: pl.DataFrame) -> None:
    # revenue_fy0 (listed first) is MISSING_INPUT, revenue_fy3 is INSUFFICIENT_HISTORY
    assert cell(out, "S", "revenue_cagr_3y") == (
        None, "INSUFFICIENT_HISTORY", "revenue_fy3: no fiscal year 3 years before the latest",
    )  # fmt: skip
    assert cell(out, "S", "revenue_cagr_5y")[1:] == (
        "INSUFFICIENT_HISTORY", "revenue_fy5: no fiscal year 5 years before the latest",
    )  # fmt: skip


def test_interest_coverage_missing_ebit_vs_no_interest(out: pl.DataFrame) -> None:
    # an untagged interest expense is only missing, so the first missing input (EBIT) is reported
    assert cell(out, "I", "interest_coverage") == (
        None, "MISSING_INPUT", "operating_income_ttm: operating_income is not reported",
    )  # fmt: skip
    # with debt tagged as zero it is n/m, which beats the missing EBIT
    assert cell(out, "K", "interest_coverage") == (
        None, "NO_INTEREST_EXPENSE",
        "interest_coverage: no debt at 2026-06-30 and no interest expense reported for the TTM to "
        "2026-06-30",
    )  # fmt: skip


def _pick(frame: pl.DataFrame, inputs: list[In]) -> tuple[object, ...]:
    e = result(pl.lit(1.0), inputs)
    return frame.select(e.value.alias("v"), e.code.alias("c"), e.message.alias("m")).row(0)


def _null(code: C, label: str) -> In:
    return column_in(label, code, f"{label}: {code.value}")


@pytest.fixture
def nulls() -> pl.DataFrame:
    return pl.DataFrame({k: [None] for k in "abcd"}, schema=dict.fromkeys("abcd", pl.Float64))


def test_same_tier_first_input_wins(nulls: pl.DataFrame) -> None:
    a, b = _null(C.MISSING_INPUT, "a"), _null(C.MISSING_INPUT, "b")
    assert _pick(nulls, [a, b]) == (None, "MISSING_INPUT", "a: MISSING_INPUT")
    assert _pick(nulls, [b, a]) == (None, "MISSING_INPUT", "b: MISSING_INPUT")
    h1, h2 = _null(C.INSUFFICIENT_HISTORY, "a"), _null(C.INSUFFICIENT_HISTORY, "b")
    assert _pick(nulls, [_null(C.MISSING_INPUT, "c"), h1, h2])[2] == "a: INSUFFICIENT_HISTORY"


def test_tier_order(nulls: pl.DataFrame) -> None:
    order = [C.INSUFFICIENT_HISTORY, C.NO_INTEREST_EXPENSE, C.STALE_DATA, C.MISSING_INPUT]
    # listed lowest tier first, so input order alone would pick the wrong one; drop the winner
    inputs = [_null(code, k) for code, k in zip(reversed(order), "abcd", strict=True)]
    for expected in order:
        winner = _pick(nulls, inputs)
        assert winner[1] == expected.value
        inputs = [i for i in inputs if f"{i.label}: {expected.value}" != winner[2]]


def test_present_inputs_do_not_count() -> None:
    frame = pl.DataFrame({"a": [2.0], "b": [None]}, schema={"a": pl.Float64, "b": pl.Float64})
    a, b = _null(C.INSUFFICIENT_HISTORY, "a"), _null(C.MISSING_INPUT, "b")
    assert _pick(frame, [a, b]) == (None, "MISSING_INPUT", "b: MISSING_INPUT")
