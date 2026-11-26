"""Brief acceptance: behaviour checks on the real trimmed fixtures (table-driven)."""

import polars as pl
import pytest

from glint.metrics.stage import MetricsOutput

CHECKS = [
    ("JPM", "enterprise_value", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "ev_ebit", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "ebit_ev", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "ev_ebitda", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "ev_sales", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "gross_margin", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "current_ratio", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "altman_z", "NOT_APPLICABLE_SECTOR"),
    ("JPM", "interest_coverage", "NOT_APPLICABLE_SECTOR"),
    ("SBUX", "pb", "NEGATIVE_DENOMINATOR"),
    ("SBUX", "debt_to_equity", "NEGATIVE_DENOMINATOR"),
    ("RIVN", "pe_ttm", "NEGATIVE_DENOMINATOR"),
    ("TSM", "market_cap", "FOREIGN_PRICE_BASIS"),
    ("TSM", "pe_ttm", "FOREIGN_PRICE_BASIS"),
    ("TSM", "ev_ebit", "FOREIGN_PRICE_BASIS"),
    ("TSM", "fcf_yield", "FOREIGN_PRICE_BASIS"),
    ("TSM", "pb", "FOREIGN_PRICE_BASIS"),
]


def _cell(out: MetricsOutput, ticker: str, metric_id: str) -> tuple[object, str | None]:
    r = out.frame.filter(pl.col("tickers").list.contains(ticker)).row(0, named=True)
    return r[metric_id], r[f"{metric_id}__code"]


@pytest.mark.parametrize(("ticker", "metric_id", "code"), CHECKS)
def test_null_reason(
    fixture_build: tuple[MetricsOutput, pl.DataFrame], ticker: str, metric_id: str, code: str
) -> None:
    assert _cell(fixture_build[0], ticker, metric_id) == (None, code)


def test_rivn_earnings_yield_negative(fixture_build: tuple[MetricsOutput, pl.DataFrame]) -> None:
    v, _ = _cell(fixture_build[0], "RIVN", "earnings_yield")
    assert isinstance(v, float) and v < 0


@pytest.mark.parametrize("metric_id", ["gross_margin", "operating_margin", "net_margin", "roic"])
def test_tsm_margins_present(
    fixture_build: tuple[MetricsOutput, pl.DataFrame], metric_id: str
) -> None:
    v, _ = _cell(fixture_build[0], "TSM", metric_id)
    assert isinstance(v, float)


def test_jpm_pe_present(fixture_build: tuple[MetricsOutput, pl.DataFrame]) -> None:
    v, _ = _cell(fixture_build[0], "JPM", "pe_ttm")
    assert isinstance(v, float) and v > 0
