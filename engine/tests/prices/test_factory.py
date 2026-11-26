from pathlib import Path

from glint.ingest.prices.factory import make_provider
from glint.ingest.prices.massive import MassiveProvider
from glint.ingest.prices.yfinance_provider import YFinanceProvider
from tests.conftest import make_settings


def test_massive_with_key(tmp_path: Path) -> None:
    s = make_settings(raw_dir=tmp_path, massive_api_key="k")
    p = make_provider(s)
    assert isinstance(p, MassiveProvider)
    assert not p.is_fallback


def test_no_key_falls_back_to_yfinance(tmp_path: Path) -> None:
    s = make_settings(raw_dir=tmp_path, massive_api_key="")
    p = make_provider(s, tickers=["AAPL"])
    assert isinstance(p, YFinanceProvider)
    assert p.is_fallback


def test_yfinance_on_purpose_is_not_a_fallback(tmp_path: Path) -> None:
    s = make_settings(raw_dir=tmp_path, massive_api_key="k", price_provider="yfinance")
    p = make_provider(s, tickers=["AAPL"])
    assert isinstance(p, YFinanceProvider)
    assert not p.is_fallback
