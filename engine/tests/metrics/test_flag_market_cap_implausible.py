"""`market_cap_implausible`: market cap below the average day's dollar volume (recent window)."""

import json
from datetime import date, timedelta
from typing import Any

import polars as pl
import pytest

from glint.core.paths import Paths
from glint.core.settings import Settings
from glint.flags.engine import RECENT_ADV, evaluate_flags, load_rules, recent_dollar_volume
from glint.ingest.prices.models import Bar
from glint.ingest.prices.store import PriceStore
from glint.metrics.stage import load_recent_adv
from tests.metrics.frames import run
from tests.metrics.helpers import fin

D = date
SHARES_AT = D(2026, 9, 30)
CFG = load_rules()
N: int = CFG["market_cap_implausible"]["adv_sessions"]
SESSIONS = [D(2026, 9, 1) + timedelta(days=i) for i in range(N)]  # calendar days stand in


def bars(ticker: str, close: float, volume: float | None, days: list[date]) -> list[dict[str, Any]]:
    return [{"ticker": ticker, "date": d, "close": close, "volume": volume} for d in days]


def frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {"ticker": pl.String, "date": pl.Date, "close": pl.Float64, "volume": pl.Float64}
    return pl.DataFrame(rows, schema=schema)


def test_config() -> None:
    c = CFG["market_cap_implausible"]
    assert c["adv_sessions"] == 20
    assert c["market_cap_to_adv_lt"] == 1.0
    assert f"last {c['adv_sessions']} sessions" in c["question"]  # the text names the window
    assert "?" in c["question"]


def test_recent_dollar_volume_needs_every_session() -> None:
    rows = [
        *bars("FULL", 2.0, 1_000, SESSIONS),
        *bars("GAP", 2.0, 1_000, SESSIONS[1:]),  # missing a bar
        *bars("NOVOL", 2.0, 1_000, SESSIONS[:-1]),
        *bars("NOVOL", 2.0, None, SESSIONS[-1:]),  # a bar without volume
        *bars("OLD", 2.0, 1_000, [SESSIONS[0] - timedelta(days=1)]),  # outside the window
    ]
    out = dict(recent_dollar_volume(frame(rows), SESSIONS).iter_rows())
    assert out["FULL"] == 2_000.0
    assert out["GAP"] is None
    assert out["NOVOL"] is None
    assert "OLD" not in out


def test_recent_dollar_volume_is_unadjusted_dollars() -> None:
    """A 1:10 reverse split mid-window: close × volume is the dollars traded, either side."""
    half = N // 2
    rows = [
        *bars("RS", 1.0, 10_000, SESSIONS[:half]),
        *bars("RS", 10.0, 1_000, SESSIONS[half:]),
    ]
    assert dict(recent_dollar_volume(frame(rows), SESSIONS).iter_rows())["RS"] == 10_000.0


def test_empty_inputs() -> None:
    assert recent_dollar_volume(frame([]), SESSIONS).is_empty()
    assert recent_dollar_volume(frame(bars("A", 1.0, 1.0, SESSIONS)), []).is_empty()


COS = [{"cik": c, "tickers": [c], "primary_ticker": c} for c in ("LAG", "OK", "EDGE", "NOADV")]
ROWS = [(c["cik"], "shares_outstanding", "mrq", SHARES_AT, 1_000_000) for c in COS]
PRICES = [{"ticker": c["cik"], "close": 1.0} for c in COS]  # market cap $1M each
ADV = {"LAG": 4_000_000.0, "OK": 50_000.0, "EDGE": 1_000_000.0, "NOADV": None}


@pytest.fixture(scope="module")
def flags() -> pl.DataFrame:
    base = run(ROWS, COS, PRICES)
    adv = pl.DataFrame(
        {"primary_ticker": list(ADV), RECENT_ADV: list(ADV.values())},
        schema={"primary_ticker": pl.String, RECENT_ADV: pl.Float64},
    )
    return evaluate_flags(base.join(adv, on="primary_ticker", how="left"), fin(ROWS), CFG)


def test_raised_below_one_day_of_trading(flags: pl.DataFrame) -> None:
    hits = flags.filter(pl.col("flag_id") == "market_cap_implausible")
    assert hits["cik"].to_list() == ["LAG"]  # EDGE (= 1.0×) is not below; NOADV can't be tested
    row = hits.row(0, named=True)
    assert row["question"].startswith("Market cap is only 25.0% of the average day's trading")
    assert json.loads(row["evidence"]) == {
        "market_cap": 1_000_000.0,
        "avg_dollar_volume_recent": 4_000_000.0,
        "adv_sessions": 20,
        "market_cap_to_adv": 0.25,
        "shares_as_of": "2026-09-30",
        "price_as_of": "2026-10-28",
    }


def test_no_volume_column_never_raises() -> None:
    """Without recent bars (no price store), the rule is silent rather than guessing."""
    out = evaluate_flags(run(ROWS, COS, PRICES), fin(ROWS), CFG)
    assert out.filter(pl.col("flag_id") == "market_cap_implausible").is_empty()


def test_load_recent_adv_uses_the_last_sessions_on_disk(settings: Settings) -> None:
    """The stage reads the last `adv_sessions` partitions up to the build's price date: a later
    partition is ignored, an earlier one falls out of the window."""
    store = PriceStore(Paths.from_settings(settings))
    days = [D(2026, 8, 1) + timedelta(days=i) for i in range(N + 2)]
    with store.writer():
        for i, d in enumerate(days):
            vol = 1_000_000.0 if i == 0 else 100.0  # the first day is outside the window
            store.write_day(d, [Bar("AAA", d, 1, 1, 1, 2.0, vol)], source="t")
    adv = load_recent_adv(store, days[-2])  # the last day on disk is after the price date
    assert dict(adv.iter_rows()) == {"AAA": 200.0}
    assert load_recent_adv(store, days[N - 2]).is_empty()  # fewer than N sessions by then
    assert load_recent_adv(store, None).is_empty()
