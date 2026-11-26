"""glint audit: §4.6 rules, distributions, null rates. Never changes a value."""

from datetime import date

import polars as pl
import pytest

from glint.metrics.params import load_thresholds
from glint.quality.audit import distribution, null_rates, rule_outliers
from tests.metrics.frames import run
from tests.metrics.helpers import fin

D = date
NOW, YEAR_AGO = D(2026, 6, 30), D(2025, 6, 30)
ROWS = [
    # G: gross profit above revenue (a tagging problem the audit must surface)
    ("G", "revenue", "ttm", NOW, 100), ("G", "gross_profit", "ttm", NOW, 250),
    # E: equity up 20x in a year
    ("E", "equity", "mrq", NOW, 2000), ("E", "equity", "mrq", YEAR_AGO, 100),
    # S: diluted shares x5 with no split
    ("S", "diluted_shares", "q", NOW, 500), ("S", "diluted_shares", "q", YEAR_AGO, 100),
    ("S", "revenue", "ttm", NOW, 10),
    # T: TTM revenue differs from FY at a FY end
    ("T", "revenue", "ttm", D(2025, 12, 31), 110), ("T", "revenue", "fy", D(2025, 12, 31), 100),
    # M: a market cap above $6T
    ("M", "shares_outstanding", "mrq", D(2026, 7, 25), 7e9), ("M", "equity", "mrq", NOW, 1),
]  # fmt: skip
COS = [{"cik": c, "tickers": [f"T{c}"], "primary_ticker": f"T{c}"} for c in "GESTM"]


@pytest.fixture(scope="module")
def frame() -> pl.DataFrame:
    return run(ROWS, COS, [{"ticker": "TM", "close": 1000.0}])


def test_rules(frame: pl.DataFrame) -> None:
    hits = rule_outliers(frame, fin(ROWS), None, load_thresholds()["audit"], top=10)
    by_rule = {r: set(df["cik"]) for r, df in hits.items()}
    assert by_rule["gross_margin_range"] == {"G"}
    assert by_rule["equity_jump"] == {"E"}
    assert by_rule["share_count_jump"] == {"S"}
    assert by_rule["ttm_vs_fy"] == {"T"}
    assert by_rule["market_cap_max"] == {"M"}
    g = hits["gross_margin_range"].row(0, named=True)
    assert g["gross_margin"] == 2.5 and g["gross_profit__ttm"] == 250 and g["revenue__ttm"] == 100


def test_distribution_and_null_rates(frame: pl.DataFrame) -> None:
    d = distribution(frame, ["gross_margin", "revenue_ttm"])
    row = d.filter(pl.col("metric_id") == "revenue_ttm").row(0, named=True)
    assert row["n"] == 3 and row["p50"] == 100.0  # G 100, S 10, T 110
    assert row["null_share"] == pytest.approx(2 / 5)  # E and M have no revenue
    rates = null_rates(frame, ["revenue_ttm"])
    assert rates.row(0, named=True)["null_share"] == pytest.approx(2 / 5)
