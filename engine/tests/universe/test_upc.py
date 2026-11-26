"""Up-C detection (universe/upc.py) on real trimmed filings plus edge cases."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from glint.ingest.sec.covers import ClassCount, Cover, NciPercent, parse_instance
from glint.universe.classify import load_rules
from glint.universe.upc import (
    UpCConfirm,
    UpCRule,
    common_classes,
    confirmed_up_c,
    detect_up_c,
    listed_class_symbols,
    review_candidate,
)

DATA = Path(__file__).parents[1] / "ingest_sec" / "data"
RULE = load_rules().up_c
AS_OF = date(2026, 8, 1)


def real(name: str, cik: str, accn: str) -> Cover:
    classes, symbols, nci = parse_instance((DATA / name).read_bytes())
    return Cover(cik, accn, "10-Q", date(2026, 8, 12), name, classes, symbols, nci)


def cover(classes: dict[str | None, float], nci: list[float], cik: str = "0000000001") -> Cover:
    return Cover(
        cik, "0000000001-26-000001", "10-Q", AS_OF, "x_htm.xml",
        [ClassCount(m, v, AS_OF) for m, v in classes.items()], {},
        [NciPercent(date(2026, 6, 30), v) for v in nci],
    )  # fmt: skip


def test_avex_is_an_up_c_with_114m_economic_shares() -> None:
    """Golden-row expectation: about 114.0M (56,470,333 Class A + 57,571,367 Class B)."""
    upc = detect_up_c(real("avex-20260630-cover.xml", "0002096300", "0002096300-26-000022"), RULE)
    assert upc is not None
    assert upc.economic_shares == 114_041_700
    assert upc.as_of == date(2026, 8, 12) and upc.accn == "0002096300-26-000022"
    assert "CommonClassA 56,470,333 + CommonClassB 57,571,367 = 114,041,700" in upc.evidence
    assert "NCI ownership 49.5%" in upc.evidence


def test_ptlo_small_class_b_still_passes() -> None:
    """Portillo's Class B is 4.5% of the total, above min_class_share (0.04); NCI 4.5%."""
    upc = detect_up_c(real("ptlo-20260628-cover.xml", "0001871509", "0001871509-26-000056"), RULE)
    assert upc is not None and upc.economic_shares == 72_518_678 + 3_424_546


def test_googl_ordinary_dual_class_is_not_an_up_c() -> None:
    """Alphabet: three economic classes, no NCI ownership % → unchanged."""
    goog = real("goog-20260930-cover.xml", "0001652044", "0001652044-26-000084")
    assert len(common_classes(goog)) == 3
    assert detect_up_c(goog, RULE) is None


def test_brk_style_two_classes_without_nci_is_not_an_up_c() -> None:
    brk = cover({"us-gaap:CommonClassAMember": 488_450, "us-gaap:CommonClassBMember": 1.4e9}, [])
    assert detect_up_c(brk, RULE) is None


def test_nci_that_matches_no_class_is_not_an_up_c() -> None:
    """An ordinary NCI (a subsidiary) that doesn't line up with any class's share."""
    c = cover({"us-gaap:CommonClassAMember": 80e6, "us-gaap:CommonClassBMember": 20e6}, [0.35])
    assert detect_up_c(c, RULE) is None


@pytest.mark.parametrize(("gap", "matches"), [(0.009, True), (0.011, False)])
def test_tolerance(gap: float, matches: bool) -> None:
    c = cover(
        {"us-gaap:CommonClassAMember": 70e6, "us-gaap:CommonClassBMember": 30e6}, [0.30 + gap]
    )
    assert (detect_up_c(c, RULE) is not None) is matches


def test_tiny_matched_class_is_a_coincidence() -> None:
    """ALIT-style: a 1% earn-out class whose share happens to equal a 1% NCI."""
    c = cover({"us-gaap:CommonClassAMember": 99e6, "x:ClassB1Member": 1e6}, [0.01])
    assert RULE.min_class_share > 0.01
    assert detect_up_c(c, RULE) is None


def test_undimensioned_total_is_not_double_counted() -> None:
    c = cover(
        {None: 100e6, "us-gaap:CommonClassAMember": 60e6, "us-gaap:CommonClassBMember": 40e6},
        [0.40],
    )
    upc = detect_up_c(c, RULE)
    assert upc is not None and upc.economic_shares == 100e6


def test_preferred_and_treasury_members_are_not_common() -> None:
    c = cover(
        {"us-gaap:CommonClassAMember": 60e6, "us-gaap:CommonClassBMember": 40e6,
         "x:SeriesAPreferredStockMember": 5e6, "x:ClassATreasuryMember": 2e6},
        [0.40],
    )  # fmt: skip
    upc = detect_up_c(c, RULE)
    assert upc is not None and upc.economic_shares == 100e6


TWFG = ("twfg-20260630-cover.xml", "0002007596", "0002007596-26-000012")
OWL = ("owl-20260630-cover.xml", "0001823945", "0001823945-26-000040")
DKNG = ("dkng-20260630-cover.xml", "0001883685", "0001883685-26-000029")


def entry(cik: str, classes: tuple[str, ...] = ()) -> UpCConfirm:
    return UpCConfirm(
        cik=cik, ticker="X", source="10-K", quote="paired 1:1 with units", keyed_by="test",
        classes=classes,
    )  # fmt: skip


def test_twfg_nci_matches_the_two_unlisted_classes_together() -> None:
    """TWFG: Class B 7,277,651 + Class C 33,893,810 = 76.2% of the cover; NCI tagged 76.3%.
    No single class is within 1pp, so only the complement match finds it."""
    twfg = real(*TWFG)
    one_class = RULE.model_copy(update={"nci_tolerance": 0.01})
    upc = detect_up_c(twfg, one_class)
    assert upc is not None and upc.economic_shares == 54_051_794
    assert "the classes other than CommonClassA are 76.2%" in upc.evidence
    assert "NCI ownership 76.3%" in upc.evidence


def test_complement_is_not_tried_with_two_classes() -> None:
    """With two classes the complement of one is the other's share: nothing new to test."""
    c = cover({"us-gaap:CommonClassAMember": 70e6, "us-gaap:CommonClassBMember": 30e6}, [0.70])
    upc = detect_up_c(c, RULE)
    assert upc is not None and "the classes other than" not in upc.evidence


def test_owl_tags_no_nci_so_only_the_confirm_list_finds_it() -> None:
    """Blue Owl: Class A + C + D (B is 0) and no NCI % tagged; confirmed from its 10-K."""
    owl = real(*OWL)
    assert detect_up_c(owl, RULE) is None
    confirmed = RULE.confirmed_entry(OWL[1])
    assert confirmed is not None and confirmed.ticker == "OWL"
    upc = confirmed_up_c(owl, confirmed)
    assert upc is not None
    assert upc.economic_shares == 683_908_596 + 572_034_424 + 303_149_203
    assert "confirmed Up-C" in upc.evidence and "one -for-one basis" in upc.evidence


def test_confirmed_classes_restrict_the_sum() -> None:
    owl = real(*OWL)
    upc = confirmed_up_c(owl, entry(OWL[1], ("CommonClassA", "CommonClassC")))
    assert upc is not None and upc.economic_shares == 683_908_596 + 572_034_424


def test_confirmed_class_missing_from_the_cover_gives_none() -> None:
    """A named class gone from the cover means the structure changed: a person looks again."""
    assert confirmed_up_c(real(*OWL), entry(OWL[1], ("CommonClassA", "CommonClassV"))) is None


def test_dkng_is_excluded_and_never_a_candidate() -> None:
    """DraftKings' Class B has no economics and no paired unit."""
    dkng = real(*DKNG)
    assert RULE.is_excluded(DKNG[1])
    assert detect_up_c(dkng, RULE) is None
    assert review_candidate(dkng, RULE, None) is None


def test_review_candidate_lists_an_unconfirmed_no_nci_multiclass_cover() -> None:
    c = cover({"us-gaap:CommonClassAMember": 60e6, "us-gaap:CommonClassBMember": 40e6}, [])
    note = review_candidate(c, RULE, None)
    assert note is not None and "CommonClassA 60.0%" in note and "none tagged" in note


def test_review_candidate_skips_detected_confirmed_and_two_listed_classes() -> None:
    assert review_candidate(real(*TWFG), RULE, None) is None  # detected
    assert review_candidate(real(*OWL), RULE, None) is None  # confirmed
    goog = real("goog-20260930-cover.xml", "0001652044", "0001652044-26-000084")
    assert review_candidate(goog, RULE, None) is None  # GOOGL and GOOG both listed


VGAS = ("vgas-20260930-cover.xml", "0001841425", "0001628280-26-072226")


def test_a_warrant_symbol_is_not_a_listed_class() -> None:
    """Verde Clean Fuels' cover (10-Q accn 0001628280-26-072226) tags VGAS on its Class A
    member and VGASW on `WarrantsEachWholeWarrant...Member`: one listed class, not two."""
    vgas = real(*VGAS)
    assert set(vgas.symbols.values()) == {"VGAS", "VGASW"}
    assert listed_class_symbols(vgas, RULE) == {"VGAS"}
    assert len(listed_class_symbols(real("goog-20260930-cover.xml", "0001652044", "x"), RULE)) == 2


def test_vgas_like_cover_is_now_a_review_candidate() -> None:
    """VGAS itself is confirmed (#78), so the same cover under an unlisted CIK stands in for the
    next one: Class A 22,049,621 + Class C 22,500,000, no NCI %, a warrant symbol beside VGAS."""
    _, _, accn = VGAS
    assert review_candidate(real(*VGAS), RULE, None) is None  # confirmed
    note = review_candidate(real(VGAS[0], "0000000002", accn), RULE, 22_070_453)
    assert note is not None and "CommonClassC 50.5%" in note and "of 44,549,621" in note


@pytest.mark.parametrize("word", ["Warrant", "RIGHTS", "preferred", "Depositary", "Notes"])
def test_non_equity_words_match_the_local_name_case_insensitively(word: str) -> None:
    c = cover({"us-gaap:CommonClassAMember": 60e6, "us-gaap:CommonClassBMember": 40e6}, [])
    c.symbols.update({"us-gaap:CommonClassAMember": "XYZ", f"xyz:Series{word}Member": "XYZW"})
    assert listed_class_symbols(c, RULE) == {"XYZ"}
    assert review_candidate(c, RULE, None) is not None


def test_two_listed_classes_next_to_a_warrant_are_still_skipped() -> None:
    c = cover({"us-gaap:CommonClassAMember": 60e6, "us-gaap:CommonClassBMember": 40e6}, [])
    c.symbols.update({
        "us-gaap:CommonClassAMember": "XYZ.A", "us-gaap:CommonClassBMember": "XYZ.B",
        "xyz:WarrantsMember": "XYZWS",
    })  # fmt: skip
    assert listed_class_symbols(c, RULE) == {"XYZ.A", "XYZ.B"}
    assert review_candidate(c, RULE, None) is None


def test_a_cik_in_both_lists_is_rejected() -> None:
    dup = {"cik": "0000000009", "ticker": "X", "source": "s", "quote": "q"}
    with pytest.raises(ValidationError, match="more than once"):
        UpCRule(
            nci_tolerance=0.01, min_class_share=0.04, candidate_min_ratio=1.05,
            total_member_tolerance=0.005, non_equity_symbol_words=("Warrant",),
            confirmed=(UpCConfirm(**dup, keyed_by="k"),), excluded=(dup,),  # pyright: ignore[reportArgumentType]
        )  # fmt: skip


def test_every_configured_entry_is_a_ten_digit_cik_with_a_quote() -> None:
    for e in (*RULE.confirmed, *RULE.excluded):
        assert len(e.cik) == 10 and e.quote and "accn" in e.source


def test_combined_member_is_their_total_not_a_third_class() -> None:
    """ZETA's cover tags `CommonClassAAndCommonClassB` (A + B) next to CommonClassA and
    CommonClassB (10-Q accn 0001193125-26-453696)."""
    zeta = cover({
        "zeta:CommonClassAAndCommonClassBMember": 255_458_977,
        "us-gaap:CommonClassAMember": 231_820_551,
        "us-gaap:CommonClassBMember": 23_638_426,
    }, [])  # fmt: skip
    assert common_classes(zeta) == {
        "us-gaap:CommonClassAMember": 231_820_551,
        "us-gaap:CommonClassBMember": 23_638_426,
    }


def test_and_member_is_kept_unless_both_parts_are_present() -> None:
    c = cover({"x:CommonClassAAndCommonClassBMember": 50e6, "us-gaap:CommonClassAMember": 40e6}, [])
    assert len(common_classes(c)) == 2


@pytest.mark.parametrize(
    ("glint", "listed"), [(None, True), (100e6, False), (95.3e6, False), (95.2e6, True)]
)
def test_review_candidate_needs_the_cover_above_glints_count(
    glint: float | None, listed: bool
) -> None:
    """Cover total 100M: listed if ≥ 1.05 × Glint's shares, or Glint has no count."""
    assert RULE.candidate_min_ratio == 1.05
    c = cover({"us-gaap:CommonClassAMember": 60e6, "us-gaap:CommonClassBMember": 40e6}, [])
    assert (review_candidate(c, RULE, glint) is not None) is listed


def test_gct_common_stock_member_is_the_total_of_its_classes() -> None:
    """GigaCloud's cover (10-Q accn 0001628280-26-070475) tags `CommonStockMember` 35,624,024
    next to Class A 29,167,292 and Class B 6,456,732: exactly their sum, so it isn't a class."""
    gct = real("gct-20260930-cover.xml", "0001857816", "0001628280-26-070475")
    assert len(gct.classes) == 3
    assert common_classes(gct) == {
        "us-gaap:CommonClassAMember": 29_167_292,
        "us-gaap:CommonClassBMember": 6_456_732,
    }
    assert review_candidate(gct, RULE, None) is not None  # still a 2-class cover to read


def test_knsa_total_member_over_four_classes_is_dropped() -> None:
    """Kiniksa's cover (10-Q accn 0001104659-26-119186): CommonStock 78,571,705 = Class A
    48,836,965 + Class B 895,158 + Class A-1 12,781,964 + Class B-1 16,057,618."""
    knsa = cover({
        "us-gaap:CommonStockMember": 78_571_705,
        "us-gaap:CommonClassAMember": 48_836_965,
        "us-gaap:CommonClassBMember": 895_158,
        "knsa:CommonClassA1Member": 12_781_964,
        "knsa:CommonClassB1Member": 16_057_618,
    }, [])  # fmt: skip
    classes = common_classes(knsa)
    assert "us-gaap:CommonStockMember" not in classes and len(classes) == 4
    assert sum(classes.values()) == 78_571_705


@pytest.mark.parametrize(("total", "dropped"), [(100.4e6, True), (99.6e6, True), (100.6e6, False)])
def test_total_member_tolerance(total: float, dropped: bool) -> None:
    """A member within `up_c.total_member_tolerance` (0.5%) of the other members' sum."""
    assert RULE.total_member_tolerance == 0.005
    c = cover({"x:AllCommonMember": total, "us-gaap:CommonClassAMember": 60e6,
               "us-gaap:CommonClassBMember": 40e6}, [])  # fmt: skip
    assert ("x:AllCommonMember" not in common_classes(c)) is dropped


def test_total_member_needs_two_other_members() -> None:
    """With two members, one equal to the other is a duplicate class count, not a total."""
    c = cover({"us-gaap:CommonStockMember": 50e6, "us-gaap:CommonClassAMember": 50e6}, [])
    assert len(common_classes(c)) == 2


def test_explicit_tolerance_overrides_config() -> None:
    c = cover({"x:AllCommonMember": 100e6, "us-gaap:CommonClassAMember": 60e6,
               "us-gaap:CommonClassBMember": 40e6}, [])  # fmt: skip
    assert len(common_classes(c, -1.0)) == 3 and len(common_classes(c)) == 2


@pytest.mark.parametrize(
    ("ticker", "cik", "where"),
    [
        ("FPH", "0001574197", "confirmed"),
        ("OPAL", "0001842279", "confirmed"),
        ("ANDG", "0002065708", "excluded"),
        ("AVAT", "0002092446", "excluded"),
        ("MC", "0001596967", "excluded"),
        ("SUN", "0001552275", "confirmed"),  # Class D summed, Class C not (2026-11-23)
        ("BXBL", "0001906364", None),  # ordinary dual-class: economically identical classes
        # 2026-11-23: Class B "no economic rights" but paired 1:1 with exchangeable units
        ("MDLN", "0002046386", "confirmed"),
        ("CNM", "0001856525", "confirmed"),
        ("TPG", "0001880661", "confirmed"),
        ("BLK", "0002012383", "confirmed"),
    ],
)
def test_reviewed_multi_class_filers_are_resolved(ticker: str, cik: str, where: str | None) -> None:
    confirmed = RULE.confirmed_entry(cik)
    assert (confirmed is not None) is (where == "confirmed")
    assert RULE.is_excluded(cik) is (where == "excluded")
    if confirmed is not None:
        assert confirmed.ticker == ticker


BLK = ("blk-20260930-cover.xml", "0002012383", "0001193125-26-447043")
SUN = ("sun-20260930-cover.xml", "0001552275", "0001552275-26-000096")


def test_blk_sums_common_and_exchangeable_subco_units_not_the_fully_diluted_total() -> None:
    """BlackRock's 10-Q cover: common 154,423,421, `ExchangeableUnitsMember` 7,606,927 (Subco
    Class B-2 units, exchangeable 1:1 into common) and `FullyDilutedSharesMember` 162,030,348,
    their exact total. Not an Up-C by the NCI rule (no NCI % tagged; two listed symbols)."""
    blk = real(*BLK)
    assert len(blk.classes) == 3
    assert detect_up_c(blk, RULE) is None
    confirmed = RULE.confirmed_entry(BLK[1])
    assert confirmed is not None and confirmed.classes == ("CommonStock", "ExchangeableUnits")
    upc = confirmed_up_c(blk, confirmed)
    assert upc is not None
    assert upc.economic_shares == 154_423_421 + 7_606_927 == 162_030_348
    assert upc.as_of == date(2026, 10, 31)
    assert "not a classic Up-C" in upc.evidence and "FullyDilutedShares" not in upc.evidence


def test_blk_without_its_exchangeable_units_on_the_cover_gives_none() -> None:
    blk = real(*BLK)
    gone = Cover(
        blk.cik, blk.accn, blk.form, blk.filed, blk.instance,
        [c for c in blk.classes if "ExchangeableUnits" not in (c.member or "")],
        blk.symbols, blk.nci,
    )  # fmt: skip
    confirmed = RULE.confirmed_entry(BLK[1])
    assert confirmed is not None and confirmed_up_c(gone, confirmed) is None


def test_sun_sums_common_and_class_d_units_never_class_c() -> None:
    """Sunoco LP's 10-Q cover: common 136,896,738, Class C 16,410,780 (held by its own
    subsidiaries) and Class D 51,517,198 (held by SunocoCorp, economically equivalent)."""
    sun = real(*SUN)
    assert len(common_classes(sun)) == 3
    confirmed = RULE.confirmed_entry(SUN[1])
    assert confirmed is not None and confirmed.classes == ("SUN", "CommonClassDUnits")
    upc = confirmed_up_c(sun, confirmed)
    assert upc is not None
    assert upc.economic_shares == 136_896_738 + 51_517_198
    assert "CommonClassC" not in upc.evidence and "not an Up-C" in upc.evidence


def test_structure_defaults_to_up_c_in_the_evidence() -> None:
    upc = confirmed_up_c(real(*OWL), entry(OWL[1]))
    assert upc is not None and "confirmed Up-C (" in upc.evidence
