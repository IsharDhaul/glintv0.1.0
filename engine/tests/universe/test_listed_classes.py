"""Separately listed cover-page classes (universe/listed_classes.py) on real trimmed filings plus
edge cases."""

import logging
from datetime import date
from pathlib import Path

import pytest
import yaml

from glint.ingest.sec.covers import ClassCount, Cover, parse_instance
from glint.universe.listed_classes import (
    CoverSymbols,
    UnlistedEconomic,
    listed_classes,
    load_cover_symbols,
    load_exclusions,
    load_unlisted_economic,
    match_ticker,
)

DATA = Path(__file__).parents[1] / "ingest_sec" / "data"
AS_OF = date(2026, 8, 1)


def real(name: str, cik: str, accn: str) -> Cover:
    classes, symbols, nci = parse_instance((DATA / name).read_bytes())
    return Cover(cik, accn, "10-Q", date(2026, 9, 1), name, classes, symbols, nci)


def cover(classes: dict[str | None, float], symbols: dict[str, str]) -> Cover:
    return Cover(
        "0000000001", "0000000001-26-000001", "10-Q", AS_OF, "x_htm.xml",
        [ClassCount(m, v, AS_OF) for m, v in classes.items()], symbols, [],
    )  # fmt: skip


A, B = "us-gaap:CommonClassAMember", "us-gaap:CommonClassBMember"


def test_heico_both_classes_listed() -> None:
    hei = real("hei-listed-classes-cover.xml", "0000046619", "0000046619-26-000020")
    out = listed_classes(hei, ["HEI", "HEI.A"], is_up_c=False)
    assert [(c.ticker, c.shares, c.as_of) for c in out] == [
        ("HEI", 55_241_647, date(2026, 8, 25)),
        ("HEI.A", 84_515_758, date(2026, 8, 25)),
    ]
    assert {c.accn for c in out} == {"0000046619-26-000020"} and out[0].form == "10-Q"


def test_brown_forman_cover_symbols_match_sec_tickers() -> None:
    """The cover says BFA/BFB; SEC (and the price data) say BF.A/BF.B. The notes' BF28 symbol is
    on another axis and isn't a class."""
    bf = real("bf-listed-classes-cover.xml", "0000014693", "0000014693-26-000052")
    out = listed_classes(bf, ["BF.B", "BF.A"], is_up_c=False)
    assert [(c.symbol, c.ticker, c.shares) for c in out] == [
        ("BFA", "BF.A", 168_480_849),
        ("BFB", "BF.B", 290_383_416),
    ]


GOOG_TICKERS = ["GOOGL", "GOOG", "GOOGM", "GOOGN"]


def confirm(
    cik: str, *classes: tuple[str, str], non_economic: str | None = None
) -> UnlistedEconomic:
    return UnlistedEconomic.model_validate({
        "cik": cik, "ticker": "X", "source": "10-K, equity note", "accn": "0000000001-26-000002",
        "quote": "The rights of the holders of each class are identical, except with respect to voting.",
        "classes": [{"member": m, "priced_at": t} for m, t in classes],
        "non_economic": [{"member": non_economic, "quote": "no economic rights"}] if non_economic else [],
        "checked_by": "test",
    })  # fmt: skip


def test_alphabet_unlisted_class_b_gives_nothing_without_a_quote() -> None:
    """GOOGL and GOOG are listed, Class B isn't: no records (never assume it's economic)."""
    goog = real("goog-20260930-cover.xml", "0001652044", "0001652044-26-000084")
    assert listed_classes(goog, GOOG_TICKERS, is_up_c=False, unlisted={}) == []


def test_alphabet_confirmed_class_b_is_priced_at_the_class_it_converts_into() -> None:
    """With the filing's quote, Class B is a record too: the cover's count, at GOOGL's close."""
    goog = real("goog-20260930-cover.xml", "0001652044", "0001652044-26-000084")
    entry = confirm(goog.cik, (B, "GOOGL"))
    out = listed_classes(goog, GOOG_TICKERS, is_up_c=False, unlisted={goog.cik: entry})
    assert [(c.ticker, c.symbol, c.member, c.shares) for c in out] == [
        ("GOOGL", "GOOGL", A, 5_888_000_000),
        ("GOOG", "GOOG", "goog:CapitalClassCMember", 5_579_000_000),
        ("GOOGL", "", B, 827_000_000),
    ]
    assert {c.accn for c in out} == {goog.accn}  # counts from the cover, never the yaml


def test_configured_alphabet_entry_applies_by_default() -> None:
    goog = real("goog-20260930-cover.xml", "0001652044", "0001652044-26-000084")
    out = listed_classes(goog, GOOG_TICKERS, is_up_c=False)
    assert [(c.ticker, c.symbol) for c in out][-1] == ("GOOGL", "")


def test_confirmed_member_missing_from_cover_gives_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    c = cover({A: 10e6, B: 5e6}, {A: "XYZ"})
    entry = confirm(c.cik, ("us-gaap:CommonClassCMember", "XYZ"))
    with caplog.at_level(logging.INFO):
        assert listed_classes(c, ["XYZ"], is_up_c=False, unlisted={c.cik: entry}) == []
    assert any(r.message == "unlisted_economic_skipped" for r in caplog.records)


def test_shared_symbol_names_the_one_listed_class_hubg_style() -> None:
    """HUBG/META tag their symbol without a class: it belongs to the one class not named."""
    c = cover({A: 60_578_607, B: 574_903}, {"": "HUBG"})
    entry = confirm(c.cik, (B, "HUBG"))
    out = listed_classes(c, ["HUBG"], is_up_c=False, unlisted={c.cik: entry})
    assert [(x.ticker, x.symbol, x.member, x.shares) for x in out] == [
        ("HUBG", "HUBG", A, 60_578_607), ("HUBG", "", B, 574_903),
    ]  # fmt: skip
    assert listed_classes(c, ["HUBG"], is_up_c=False, unlisted={}) == []


def test_unnamed_unlisted_class_or_wrong_price_ticker_gives_nothing() -> None:
    cls_c = "us-gaap:CommonClassCMember"
    c = cover({A: 10e6, B: 5e6, cls_c: 1e6}, {A: "XYZ"})
    assert (
        listed_classes(c, ["XYZ"], is_up_c=False, unlisted={c.cik: confirm(c.cik, (B, "XYZ"))})
        == []
    )
    two = cover({A: 10e6, B: 5e6}, {A: "XYZ"})
    wrong = confirm(two.cik, (B, "ABC"))
    assert listed_classes(two, ["XYZ", "ABC"], is_up_c=False, unlisted={two.cik: wrong}) == []


def test_non_economic_member_is_left_out() -> None:
    """SHOP's Founder Share: one share with votes and no economic rights."""
    founder = "shop:FounderShareMember"
    c = cover({A: 1_208_456_928, B: 78_065_084, founder: 1}, {"": "SHOP"})
    entry = confirm(c.cik, (B, "SHOP"), non_economic=founder)
    out = listed_classes(c, ["SHOP"], is_up_c=False, unlisted={c.cik: entry})
    assert [x.member for x in out] == [A, B]


def test_up_c_wins_over_a_confirmed_entry() -> None:
    c = cover({A: 10e6, B: 5e6}, {A: "XYZ"})
    entry = confirm(c.cik, (B, "XYZ"))
    assert listed_classes(c, ["XYZ"], is_up_c=True, unlisted={c.cik: entry}) == []


def test_up_c_gets_nothing() -> None:
    c = cover({A: 10e6, B: 5e6}, {A: "XYZ", B: "XYZB"})
    assert len(listed_classes(c, ["XYZ", "XYZB"], is_up_c=False)) == 2
    assert listed_classes(c, ["XYZ", "XYZB"], is_up_c=True) == []


def test_excluded_cik_gets_nothing() -> None:
    c = cover({A: 10e6, B: 5e6}, {A: "XYZ", B: "XYZB"})
    assert listed_classes(c, ["XYZ", "XYZB"], is_up_c=False, excluded=frozenset({c.cik})) == []


def test_zero_share_class_is_ignored_and_one_left_is_not_enough() -> None:
    c = cover({A: 10e6, B: 0.0, "us-gaap:CommonClassCMember": 3e6},
              {A: "XYZ", "us-gaap:CommonClassCMember": "XYZC"})  # fmt: skip
    assert [x.ticker for x in listed_classes(c, ["XYZ", "XYZC"], is_up_c=False)] == ["XYZ", "XYZC"]
    assert listed_classes(cover({A: 10e6, B: 0.0}, {A: "XYZ"}), ["XYZ"], is_up_c=False) == []


def test_undimensioned_count_or_shared_symbol_gives_nothing() -> None:
    assert listed_classes(cover({None: 10e6}, {"": "XYZ"}), ["XYZ"], is_up_c=False) == []
    same = cover({A: 10e6, B: 5e6}, {A: "XYZ", B: "XYZ"})
    assert listed_classes(same, ["XYZ"], is_up_c=False) == []


def test_match_ticker() -> None:
    assert match_ticker("CRD-A", ["CRD.A", "CRD.B"]) == "CRD.A"
    assert match_ticker("WSOB", ["WSO", "WSO.B"]) == "WSO.B"
    assert match_ticker("HVTA", ["HVT", "HVT.A"]) == "HVT.A"
    assert match_ticker("WLYB", ["WLY", "WLYB"]) == "WLYB"
    assert match_ticker("ZZZ", ["XYZ"]) == "ZZZ"  # no match: canonical spelling, finds no price


def test_config_unlisted_economic_entries_carry_quotes() -> None:
    entries = load_unlisted_economic()
    tickers = {e.ticker for e in entries.values()}
    assert {"GOOGL", "UAA", "Z", "FWONK", "CENT", "HUBG", "DUOL"} <= tickers
    assert all(len(e.quote) > 60 and e.accn and e.checked_by for e in entries.values())
    assert entries["0001652044"].classes[0].priced_at == "GOOGL"


def test_unlisted_economic_schema(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="named twice"):
        UnlistedEconomic.model_validate(
            confirm("0000000001", (B, "X")).model_dump()
            | {"non_economic": [{"member": B, "quote": "q"}]}
        )
    path = tmp_path / "sc.yaml"
    one = confirm("0000000001", (B, "X")).model_dump()
    path.write_text(yaml.safe_dump({"unlisted_economic": [one, one]}))
    with pytest.raises(ValueError, match="one `unlisted_economic` entry per CIK"):
        load_unlisted_economic(path)
    path.write_text(yaml.safe_dump({"unlisted_economic": [one | {"shares_outstanding": 5}]}))
    with pytest.raises(ValueError):  # counts are never keyed: they come from the cover
        load_unlisted_economic(path)


def test_config_exclusions_carry_evidence() -> None:
    ex = load_exclusions()
    assert {e.ticker for e in ex.values()} == {"USCI", "YSAG", "ESBA", "SF", "TAP"}
    assert all(len(e.reason) > 40 for e in ex.values())


TAP_CIK = "0000024545"


def keyed(cik: str, symbols: dict[str, str]) -> CoverSymbols:
    return CoverSymbols.model_validate({
        "cik": cik, "ticker": "X", "accn": "0000000001-26-000002", "source": "10-K cover page",
        "quote": "Class A Common Stock | XYZ | New York Stock Exchange", "symbols": symbols,
        "checked_by": "test",
    })  # fmt: skip


def test_molson_coors_symbols_from_the_10k_cover_table() -> None:
    """TAP tags its symbols on the exchange axis too, so the parsed cover has none: configured
    10-K cover-table symbols name each class, and each is priced at its own close. The real
    config leaves TAP out (`cover_excluded`: the cover misses its exchangeable shares)."""
    tap = real("tap-20260930-cover.xml", TAP_CIK, "0000024545-26-000079")
    assert tap.symbols == {}
    assert listed_classes(tap, ["TAP", "TAP.A"], is_up_c=False, cover_symbols={}) == []
    entry = keyed(TAP_CIK, {A: "TAP.A", B: "TAP"})
    out = listed_classes(tap, ["TAP", "TAP.A"], is_up_c=False, cover_symbols={TAP_CIK: entry})
    assert [(c.ticker, c.symbol, c.member, c.shares, c.as_of) for c in out] == [
        ("TAP.A", "TAP.A", A, 2_563_034, date(2026, 10, 29)),
        ("TAP", "TAP", B, 173_017_657, date(2026, 10, 29)),
    ]
    assert listed_classes(tap, ["TAP", "TAP.A"], is_up_c=False) == []  # config/share_classes.yaml
    assert TAP_CIK in load_exclusions()


def test_cover_tag_wins_over_a_configured_symbol() -> None:
    c = cover({A: 10e6, B: 5e6}, {A: "XYZ"})
    sym = {c.cik: keyed(c.cik, {A: "ABC", B: "XYZB"})}
    out = listed_classes(c, ["XYZ", "XYZB"], is_up_c=False, cover_symbols=sym)
    assert [(x.ticker, x.member) for x in out] == [("XYZ", A), ("XYZB", B)]


def test_configured_symbol_names_the_listed_class_unlisted_still_needs_a_quote() -> None:
    """NC: Class A is listed, Class B isn't. The symbol alone gives nothing (RPC); with the
    filing's quote, Class B is priced at NC."""
    c = cover({A: 5_984_941, B: 1_561_754}, {})
    sym = {c.cik: keyed(c.cik, {A: "NC"})}
    assert listed_classes(c, ["NC"], is_up_c=False, unlisted={}, cover_symbols=sym) == []
    entry = {c.cik: confirm(c.cik, (B, "NC"))}
    out = listed_classes(c, ["NC"], is_up_c=False, unlisted=entry, cover_symbols=sym)
    assert [(x.ticker, x.symbol, x.member, x.shares) for x in out] == [
        ("NC", "NC", A, 5_984_941), ("NC", "", B, 1_561_754),
    ]  # fmt: skip
    assert listed_classes(c, ["NC"], is_up_c=True, unlisted=entry, cover_symbols=sym) == []


def test_configured_member_not_on_the_cover_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    cls_c = "us-gaap:CommonClassCMember"
    c = cover({A: 10e6, B: 5e6}, {})
    sym = {c.cik: keyed(c.cik, {A: "XYZ", B: "XYZB", cls_c: "XYZC"})}
    with caplog.at_level(logging.INFO):
        out = listed_classes(c, ["XYZ", "XYZB"], is_up_c=False, cover_symbols=sym)
    assert [x.ticker for x in out] == ["XYZ", "XYZB"]
    assert any(r.message == "cover_symbols_member_missing" for r in caplog.records)


def test_config_cover_symbols_carry_quotes() -> None:
    entries = load_cover_symbols()
    assert {e.ticker for e in entries.values()} == {"NC", "RPC"}
    assert entries["0000789933"].symbols == {A: "NC"}
    assert all("|" in e.quote and e.accn and e.checked_by for e in entries.values())
    unlisted = load_unlisted_economic()
    for cik, e in entries.items():  # a class is either listed (here) or unlisted (quoted), not both
        named: set[str] = {u.member for u in unlisted[cik].classes} if cik in unlisted else set()
        assert not named & set(e.symbols)


def test_cover_symbols_schema(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="two members on one symbol"):
        keyed("0000000001", {A: "XYZ", B: "XYZ"})
    with pytest.raises(ValueError, match="blank"):
        keyed("0000000001", {A: " "})
    with pytest.raises(ValueError):
        keyed("0000000001", {})
    path = tmp_path / "sc.yaml"
    one = keyed("0000000001", {A: "XYZ"}).model_dump()
    path.write_text(yaml.safe_dump({"cover_symbols": [one, one]}))
    with pytest.raises(ValueError, match="one `cover_symbols` entry per CIK"):
        load_cover_symbols(path)
    path.write_text(yaml.safe_dump({"cover_symbols": [one | {"shares_outstanding": 5}]}))
    with pytest.raises(ValueError):  # counts are never keyed: they come from the cover
        load_cover_symbols(path)
