"""Market cap for a multi-class company: config/share_classes.yaml entries and cover-listed
classes (companies.parquet `listed_classes`), merged with the yaml winning.

Share counts are real cover facts (Berkshire's Q3 2026 10-Q, Duolingo's yaml entry); prices here
are made up for the test.
"""

from datetime import date
from typing import Any

import polars as pl
import pytest

from glint.contracts.metrics import load_registry
from glint.financials.concepts import load_concepts
from glint.flags.engine import load_rules
from glint.metrics.params import load_params
from glint.metrics.share_classes import (
    ShareClass,
    ShareClassEntry,
    cover_entries,
    load_share_classes,
    merged_share_classes,
)
from glint.metrics.stage import run_metrics
from glint.universe.build import LISTED_CLASS_FIELDS
from tests.metrics.frames import AS_OF_FUNDAMENTALS, AS_OF_PRICES, cell, run, stats
from tests.metrics.helpers import companies, fin

BRK = "0001067983"
DUOL = "0001562088"
ROWS = [(BRK, "equity", "mrq", date(2026, 6, 30), 1)]
COMPANY = {"cik": BRK, "tickers": ["BRK.B", "BRK.A"], "primary_ticker": "BRK.B"}
ACCN = "0001193125-26-452412"
BRK_LISTED: list[dict[str, Any]] = [
    {"ticker": "BRK.A", "symbol": "BRK.A", "member": "us-gaap:CommonClassAMember",
     "shares": 480_476.0, "as_of": date(2026, 10, 28), "accn": ACCN, "form": "10-Q"},
    {"ticker": "BRK.B", "symbol": "BRK.B", "member": "us-gaap:CommonClassBMember",
     "shares": 1_403_805_594.0, "as_of": date(2026, 10, 28), "accn": ACCN, "form": "10-Q"},
]  # fmt: skip
PRICES = [{"ticker": "BRK.A", "close": 700_000.0}, {"ticker": "BRK.B", "close": 466.0}]


def with_listed(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """companies rows with a `listed_classes` column typed like companies.parquet."""
    listed = [r.pop("listed_classes", None) for r in rows]
    return companies(rows).with_columns(
        pl.Series("listed_classes", listed, dtype=pl.List(pl.Struct(LISTED_CLASS_FIELDS)))
    )


def test_yaml_has_no_hand_keyed_counts() -> None:
    """BRK comes from its cover; HUBG and DUOL from their cover plus the filing's quote
    (`unlisted_economic`), so no count is keyed by hand."""
    assert load_share_classes() == {}


GOOGL = "0001652044"
GOOG_COMPANY = {"cik": GOOGL, "tickers": ["GOOGL", "GOOG"], "primary_ticker": "GOOGL"}
GOOG_ACCN = "0001652044-26-000084"
GOOG_LISTED: list[dict[str, Any]] = [
    {"ticker": "GOOGL", "symbol": "GOOGL", "member": "us-gaap:CommonClassAMember",
     "shares": 5_888_000_000.0, "as_of": date(2026, 10, 23), "accn": GOOG_ACCN, "form": "10-Q"},
    {"ticker": "GOOG", "symbol": "GOOG", "member": "goog:CapitalClassCMember",
     "shares": 5_579_000_000.0, "as_of": date(2026, 10, 23), "accn": GOOG_ACCN, "form": "10-Q"},
    {"ticker": "GOOGL", "symbol": "", "member": "us-gaap:CommonClassBMember",
     "shares": 827_000_000.0, "as_of": date(2026, 10, 23), "accn": GOOG_ACCN, "form": "10-Q"},
]  # fmt: skip


def test_unlisted_class_is_priced_at_the_class_it_converts_into() -> None:
    """GOOGL's Class B (cover count, filing-confirmed economics) at the GOOGL close."""
    frame = with_listed([{**GOOG_COMPANY, "listed_classes": GOOG_LISTED}])
    entries = cover_entries(frame, {"GOOGL", "GOOG"})
    goog_rows = [(GOOGL, "equity", "mrq", date(2026, 6, 30), 1)]
    prices = [{"ticker": "GOOGL", "close": 300.0}, {"ticker": "GOOG", "close": 301.0}]
    v, _, m = cell(
        run(goog_rows, [GOOG_COMPANY], prices, share_classes=entries), GOOGL, "market_cap"
    )
    assert v == (5_888_000_000 + 827_000_000) * 300.0 + 5_579_000_000 * 301.0
    assert m == (
        f"share classes from the cover page (10-Q accn {GOOG_ACCN}; unlisted class economics per "
        "Alphabet 10-K FY2025, Note 11 (Stockholders' Equity), accn 0001652044-26-000018): "
        "GOOGL 5,888,000,000 × 300.00 + GOOG 5,579,000,000 × 301.00 + "
        "CommonClassB (unlisted, at GOOGL) 827,000,000 × 300.00"
    )
    assert "unlisted" in entries[GOOGL].classes[2].reason


def test_conversion_ratio_is_optional() -> None:
    c = ShareClass(ticker="X", shares_outstanding=1, as_of=date(2026, 1, 1), accn="a", reason="r")
    assert c.conversion_ratio is None


def test_yaml_cannot_claim_cover_origin(tmp_path: Any) -> None:
    path = tmp_path / "sc.yaml"
    path.write_text(
        'companies:\n  - {cik: "1", name: n, source: s, keyed_by: k, origin: cover, classes: ['
        "{ticker: A, shares_outstanding: 1, as_of: 2026-01-01, accn: a, reason: r},"
        "{ticker: B, shares_outstanding: 1, as_of: 2026-01-01, accn: a, reason: r}]}\n"
    )
    with pytest.raises(ValueError, match="origin"):
        load_share_classes(path)


def test_cover_entry_sums_each_class_at_its_own_close() -> None:
    entries = cover_entries(with_listed([{**COMPANY, "listed_classes": BRK_LISTED}]),
                            {"BRK.A", "BRK.B"})  # fmt: skip
    out = run(ROWS, [COMPANY], PRICES, share_classes=entries)
    v, c, m = cell(out, BRK, "market_cap")
    assert v == 480_476 * 700_000.0 + 1_403_805_594 * 466.0
    assert c == "DERIVED_INPUT"
    assert m == (
        f"share classes from the cover page (10-Q accn {ACCN}): "
        "BRK.A 480,476 × 700,000.00 + BRK.B 1,403,805,594 × 466.00"
    )
    assert all(x.conversion_ratio is None for x in entries[BRK].classes)


def test_class_without_close_gives_no_cover_entry() -> None:
    """WSOB-style: a listed class with no bars keeps the single-count market cap, not a
    MISSING_INPUT."""
    frame = with_listed([{**COMPANY, "listed_classes": BRK_LISTED}])
    assert cover_entries(frame, {"BRK.B"}) == {}
    merged = merged_share_classes({}, frame, stats([{"ticker": "BRK.B", "close": 466.0}]),
                                  as_of_prices=AS_OF_PRICES, stale_days=7)  # fmt: skip
    assert merged == {}


def test_stale_class_close_gives_no_cover_entry() -> None:
    """BIO-style: one class last traded 11 days before the price date. The cover entry would make
    the cell STALE_DATA, so the single-count market cap is kept instead."""
    frame = with_listed([{**COMPANY, "listed_classes": BRK_LISTED}])
    old = date(2026, 10, 17)
    prices = stats([PRICES[0] | {"as_of": old}, PRICES[1]])
    assert merged_share_classes({}, frame, prices, as_of_prices=AS_OF_PRICES, stale_days=7) == {}
    fresh = merged_share_classes({}, frame, stats(PRICES), as_of_prices=AS_OF_PRICES, stale_days=7)
    assert list(fresh) == [BRK]


def test_no_column_or_one_class_gives_nothing() -> None:
    assert cover_entries(companies([COMPANY]), {"BRK.A", "BRK.B"}) == {}
    one = with_listed([{**COMPANY, "listed_classes": BRK_LISTED[:1]}])
    assert cover_entries(one, {"BRK.A", "BRK.B"}) == {}


def test_yaml_entry_wins_for_its_cik() -> None:
    hand = ShareClassEntry(
        cik=DUOL, name="Duolingo", source="test", keyed_by="test",
        classes=[ShareClass(ticker="DUOL", shares_outstanding=n, as_of=date(2026, 11, 3),
                            accn="a", reason="r") for n in (40_779_003, 6_399_257)],
    )  # fmt: skip
    listed = [{**c, "ticker": t} for c, t in zip(BRK_LISTED, ["DUOL", "DUOLB"], strict=True)]
    frame = with_listed([
        {"cik": DUOL, "tickers": ["DUOL"], "primary_ticker": "DUOL", "listed_classes": listed},
        {**COMPANY, "listed_classes": BRK_LISTED},
    ])  # fmt: skip
    prices = stats([*PRICES, {"ticker": "DUOL", "close": 200.0},
                    {"ticker": "DUOLB", "close": 200.0}])  # fmt: skip
    merged = merged_share_classes({DUOL: hand}, frame, prices, as_of_prices=None, stale_days=7)
    assert merged[DUOL] is hand
    assert merged[BRK].origin == "cover"


def test_yaml_class_without_price_is_still_missing_input() -> None:
    entry = ShareClassEntry(
        cik=BRK, name="Berkshire", source="test", keyed_by="test",
        classes=[ShareClass(ticker=c["ticker"], shares_outstanding=c["shares"],
                            as_of=c["as_of"], accn=ACCN, reason="r") for c in BRK_LISTED],
    )  # fmt: skip
    out = run(ROWS, [COMPANY], [{"ticker": "BRK.B", "close": 466.0}], share_classes={BRK: entry})
    assert cell(out, BRK, "market_cap") == (None, "MISSING_INPUT", "close: no price bars for BRK.A")


def test_run_metrics_merges_the_column_and_drops_it() -> None:
    out = run_metrics(
        with_listed([{**COMPANY, "listed_classes": BRK_LISTED}]), fin(ROWS), stats(PRICES), None,
        as_of_fundamentals=AS_OF_FUNDAMENTALS, as_of_prices=AS_OF_PRICES,
        share_classes={}, registry=load_registry(), params=load_params(),
        concepts=load_concepts(), flag_cfg=load_rules(),
    )  # fmt: skip
    assert "listed_classes" not in out.frame.columns
    assert out.snapshot["market_cap"][0] == 480_476 * 700_000.0 + 1_403_805_594 * 466.0
