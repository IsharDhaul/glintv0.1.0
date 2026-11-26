"""Profitability and returns: hand-computed values, n/m and missing paths."""

from datetime import date

import polars as pl
import pytest

from tests.metrics.frames import cell, run

D = date
NOW, YEAR_AGO = D(2026, 6, 30), D(2025, 6, 30)


def ttm(cik: str, **items: float) -> list[tuple[object, ...]]:
    derived = {"gross_profit", "fcf", "ebitda"}
    return [(cik, k, "ttm", NOW, v, k in derived) for k, v in items.items()]


def mrq(cik: str, end: date, **items: float) -> list[tuple[object, ...]]:
    return [(cik, k, "mrq", end, v) for k, v in items.items()]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    rows = [
        # P: revenue 1,000; COGS 600 → gross profit 400 (derived); FCF 180 − 50 = 130 (derived)
        *ttm("P", revenue=1000, cost_of_revenue=600, gross_profit=400, operating_income=150,
             net_income=100, cfo=180, capex=50, fcf=130, sbc=20, dna=30, ebitda=180,
             dividends_paid=40),
        *mrq("P", NOW, equity=500, total_assets=2000),
        *mrq("P", YEAR_AGO, equity=300, total_assets=1800),
        # N: losses and negative equity
        *ttm("N", revenue=500, operating_income=-50, net_income=-80, cfo=-10, dividends_paid=5),
        *mrq("N", NOW, equity=-100, total_assets=400),
        *mrq("N", YEAR_AGO, equity=-50, total_assets=420),
        # Z: zero revenue
        *ttm("Z", revenue=0, operating_income=-5, net_income=-5),
        # K: a bank (no cost of revenue by design); no balance sheet a year ago
        *ttm("K", revenue=800, operating_income=300, net_income=200),
        *mrq("K", NOW, equity=1000, total_assets=9000),
    ]  # fmt: skip
    companies = [{"cik": c} for c in "PNZ"] + [{"cik": "K", "sector": "Banks"}]
    return run(rows, companies)


@pytest.mark.parametrize(
    ("metric_id", "value", "code"),
    [
        ("gross_margin", 0.4, "DERIVED_INPUT"),
        ("operating_margin", 0.15, None),
        ("ebitda_margin", 0.18, "DERIVED_INPUT"),
        ("net_margin", 0.1, None),
        ("fcf_margin", 0.13, "DERIVED_INPUT"),
        ("cash_conversion", 1.8, None),
        ("sbc_to_revenue", 0.02, None),
        ("fcf_after_sbc_margin", 0.11, "DERIVED_INPUT"),  # (130 − 20) / 1,000
        ("roe", 0.25, None),  # 100 / ((500 + 300) / 2)
        ("roa", 100 / 1900, None),  # 100 / ((2,000 + 1,800) / 2)
    ],
)
def test_values(out: pl.DataFrame, metric_id: str, value: float, code: str | None) -> None:
    v, c, _ = cell(out, "P", metric_id)
    assert v == pytest.approx(value, rel=1e-12)
    assert c == code


def test_derived_note_names_the_input(out: pl.DataFrame) -> None:
    assert cell(out, "P", "gross_margin")[2] == "uses derived input: gross_profit_ttm"


def test_losses(out: pl.DataFrame) -> None:
    assert cell(out, "N", "net_margin")[0] == pytest.approx(-0.16)
    assert cell(out, "N", "operating_margin")[0] == pytest.approx(-0.1)
    assert cell(out, "N", "cash_conversion")[:2] == (None, "NEGATIVE_DENOMINATOR")
    v, c, m = cell(out, "N", "roe")
    assert (v, c, m) == (None, "NEGATIVE_DENOMINATOR", "average equity ≤ 0")
    assert cell(out, "N", "roa")[0] == pytest.approx(-80 / 410)


def test_zero_revenue_is_not_meaningful(out: pl.DataFrame) -> None:
    for mid in ("operating_margin", "net_margin"):
        assert cell(out, "Z", mid) == (None, "NEGATIVE_DENOMINATOR", "revenue_ttm ≤ 0")


def test_bank(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "K", "gross_margin")
    assert (v, c) == (None, "NOT_APPLICABLE_SECTOR")
    assert m == "gross_margin is not meaningful for banks (§4.5)"
    assert cell(out, "K", "operating_margin")[0] == pytest.approx(0.375)
    v, c, m = cell(out, "K", "roe")
    assert (v, c) == (None, "INSUFFICIENT_HISTORY")
    assert m == "equity_mrq_1y: no balance sheet about a year before the latest"


def test_missing_input_names_the_item(out: pl.DataFrame) -> None:
    v, c, m = cell(out, "Z", "fcf_margin")
    assert (v, c) == (None, "MISSING_INPUT")
    assert m is not None and m.startswith("fcf_ttm: fcf is not reported")
