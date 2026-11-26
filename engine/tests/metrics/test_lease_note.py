"""INPUT_EXCLUDES on total_debt-based values when the filing doesn't place the finance lease
(`companies.finance_lease_status = 'not_stated'`; user decision 2026-11-22)."""

import polars as pl
import pytest

from tests.metrics.frames import cell, run
from tests.metrics.test_valuation_health import company

EVIDENCE = (
    "FinanceLeaseLiabilityNoncurrent 500,000,000 at 2026-06-30; no filing names its "
    "balance-sheet line (10-Q 0000000001-26-000020, 10-K 0000000001-26-000005)"
)
NOTE = f"total_debt leaves out a finance lease (the filing doesn't say where it's presented): {EVIDENCE}"


def _out(lease_cols: bool = True) -> pl.DataFrame:
    rows = [r for c in "USN" for r in company(c)]
    cos: list[dict[str, object]] = [{"cik": c, "tickers": [f"T{c}"], "primary_ticker": f"T{c}", "last_annual_form": "10-K"}
           for c in "USN"]  # fmt: skip
    if lease_cols:
        lease = {"U": ("not_stated", EVIDENCE), "S": ("stated", "10-K …"), "N": (None, None)}
        for c in "USN":
            status, evidence = lease[c]
            cos["USN".index(c)] |= {
                "finance_lease_status": status,
                "finance_lease_evidence": evidence,
            }
    return run(rows, cos, [{"ticker": f"T{c}", "close": 50.0} for c in "USN"])


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    return _out()


@pytest.mark.parametrize("metric_id", ["enterprise_value", "net_debt", "debt_to_equity", "roic"])
def test_unstated_lease_is_noted_on_debt_values(out: pl.DataFrame, metric_id: str) -> None:
    value, code, msg = cell(out, "U", metric_id)
    assert value is not None and code == "INPUT_EXCLUDES" and msg == NOTE
    assert value == cell(out, "N", metric_id)[0]  # the value itself is unchanged


@pytest.mark.parametrize("metric_id", ["ev_ebit", "ebit_ev", "ev_ebitda", "ev_sales"])
def test_ev_multiples_carry_the_note(out: pl.DataFrame, metric_id: str) -> None:
    value, code, msg = cell(out, "U", metric_id)
    assert value is not None and code == "INPUT_EXCLUDES"
    assert msg == f"enterprise_value: {NOTE}"


def test_stated_or_no_lease_keeps_the_usual_note(out: pl.DataFrame) -> None:
    for cik in "SN":
        assert cell(out, cik, "enterprise_value")[1] == "DERIVED_INPUT"  # total_debt is derived
        assert cell(out, cik, "ev_sales")[1] == "DERIVED_INPUT"


def test_frames_without_the_columns_still_compute() -> None:
    assert cell(_out(lease_cols=False), "U", "enterprise_value")[1] == "DERIVED_INPUT"
