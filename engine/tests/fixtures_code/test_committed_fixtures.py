"""The committed real fixtures cover Appendix D and stay inside the size budget."""

import orjson

from glint.fixtures.sec import FIXED_TICKERS, FIXTURE_DIR, MAX_TOTAL_BYTES, fixture_name


def test_every_appendix_d_ticker_has_fixtures() -> None:
    for ticker, _ in FIXED_TICKERS:
        for kind in ("companyfacts", "submissions"):
            assert (FIXTURE_DIR / f"{fixture_name(ticker)}.{kind}.json").exists(), (ticker, kind)


def test_runtime_picks_are_recorded() -> None:
    manifest = orjson.loads((FIXTURE_DIR / "manifest.json").read_bytes())
    roles = " ".join(f["role"] for f in manifest["fixtures"])
    assert "SPAC" in roles and "IPO" in roles and "Fiscal-year change" in roles
    assert len(manifest["picks"]) == 3


def test_total_size_under_budget() -> None:
    total = sum(p.stat().st_size for p in FIXTURE_DIR.glob("*.json"))
    assert total < MAX_TOTAL_BYTES
