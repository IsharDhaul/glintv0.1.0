from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import pytest
from pydantic import ValidationError

from glint.contracts.enums import Kind, Sector
from glint.fixtures.sec import FIXTURE_DIR
from glint.universe.classify import SECTORS_PATH, load_rules, sic_range
from glint.universe.classify import classify as classify_rec
from glint.universe.submissions import SubmissionRecord, parse_submission

AS_OF = date(2026, 10, 29)
RULES = load_rules()

# Appendix D: expected Glint sector (SIC-based, Appendix C) and kind, per fixture ticker.
EXPECTED: list[tuple[str, Sector, Kind, bool, bool]] = [
    # ticker, sector, kind, is_reit, is_foreign_filer
    ("AAPL", Sector.TECHNOLOGY, Kind.OPERATING, False, False),
    ("MSFT", Sector.TECHNOLOGY, Kind.OPERATING, False, False),
    ("NVDA", Sector.TECHNOLOGY, Kind.OPERATING, False, False),
    ("KO", Sector.CONSUMER_STAPLES, Kind.OPERATING, False, False),
    ("MU", Sector.TECHNOLOGY, Kind.OPERATING, False, False),
    ("KHC", Sector.CONSUMER_STAPLES, Kind.OPERATING, False, False),
    ("RIVN", Sector.CONSUMER_DISCRETIONARY, Kind.OPERATING, False, False),
    ("SBUX", Sector.CONSUMER_DISCRETIONARY, Kind.OPERATING, False, False),
    ("XOM", Sector.ENERGY, Kind.OPERATING, False, False),
    ("F", Sector.CONSUMER_DISCRETIONARY, Kind.OPERATING, False, False),
    ("JPM", Sector.BANKS, Kind.OPERATING, False, False),
    ("O", Sector.REAL_ESTATE, Kind.OPERATING, True, False),
    ("BRK.B", Sector.INSURANCE, Kind.OPERATING, False, False),
    ("GOOGL", Sector.TECHNOLOGY, Kind.OPERATING, False, False),
    ("TSM", Sector.TECHNOLOGY, Kind.OPERATING, False, True),
    ("ASML", Sector.INDUSTRIALS, Kind.OPERATING, False, True),  # SIC 3559 machinery
    ("AAC", Sector.UNCLASSIFIED, Kind.SPAC, False, False),
    ("SEV", Sector.CONSUMER_DISCRETIONARY, Kind.OPERATING, False, False),
    ("ANAB", Sector.HEALTH_CARE, Kind.OPERATING, False, False),
]


def record(ticker: str) -> SubmissionRecord:
    doc: dict[str, Any] = orjson.loads((FIXTURE_DIR / f"{ticker}.submissions.json").read_bytes())
    return parse_submission(doc, AS_OF)


@pytest.mark.parametrize(("ticker", "sector", "kind", "reit", "foreign"), EXPECTED)
def test_appendix_d_classification(
    ticker: str, sector: Sector, kind: Kind, reit: bool, foreign: bool
) -> None:
    c = classify_rec(record(ticker), [ticker], RULES)
    assert (c.sector, c.kind, c.is_reit, c.is_foreign_filer) == (sector, kind, reit, foreign)


def test_narrowest_range_wins() -> None:
    # 2834 sits in pharma (2833–2836), not chemicals; 7372 in software, not business services.
    r1 = sic_range(2834, RULES)
    r2 = sic_range(7372, RULES)
    assert r1 is not None and r1.sector is Sector.HEALTH_CARE
    assert r2 is not None and r2.sector is Sector.TECHNOLOGY
    assert sic_range(9999, RULES) is None


@pytest.mark.parametrize(
    ("sic", "sector"),
    [(8200, Sector.CONSUMER_DISCRETIONARY), (7513, Sector.INDUSTRIALS),
     (7532, Sector.CONSUMER_DISCRETIONARY), (3743, Sector.INDUSTRIALS), (6792, Sector.ENERGY),
     (6795, Sector.MATERIALS), (8351, Sector.CONSUMER_DISCRETIONARY), (8111, Sector.INDUSTRIALS)],
)  # fmt: skip
def test_wt01_range_additions(sic: int, sector: Sector) -> None:
    r = sic_range(sic, RULES)
    assert r is not None and r.sector is sector


@pytest.mark.parametrize("sic", [8880, 8900, 9995])
def test_deliberately_unclassified(sic: int) -> None:
    assert sic_range(sic, RULES) is None


def test_sic_zero_is_blank() -> None:
    rec = parse_submission({"cik": "1", "sic": "0000", "filings": {"recent": {}}}, AS_OF)
    assert rec.sic is None


def blank(**kw: Any) -> SubmissionRecord:
    base = record("AAPL")
    return replace(base, sic=None, sic_description=None, **kw)


def test_blank_sic_funds() -> None:
    by_forms = classify_rec(blank(recent_forms=frozenset({"N-CSR", "8-K"})), ["X"], RULES)
    by_type = classify_rec(blank(entity_type="investment", recent_forms=frozenset()), ["X"], RULES)
    adr_only = classify_rec(
        blank(entity_type="other", recent_forms=frozenset({"F-6EF"})), ["X"], RULES
    )
    assert by_forms.kind is Kind.FUND and by_type.kind is Kind.FUND
    assert adr_only.kind is Kind.OPERATING
    assert adr_only.sector is Sector.UNCLASSIFIED


def test_investment_entity_with_sic_is_not_a_fund() -> None:
    reit = replace(record("O"), entity_type="investment")
    assert classify_rec(reit, ["SELF"], RULES).kind is Kind.OPERATING


def test_overrides(tmp_path: Path) -> None:
    sectors = tmp_path / "sectors.yaml"
    sectors.write_text(SECTORS_PATH.read_text())
    ov = tmp_path / "overrides.yaml"
    ov.write_text(
        "overrides:\n"
        "  - {ticker: ASML, sector: Technology, reason: 'semis equipment'}\n"
        "  - {ticker: AAPL, kind: shell, reason: 'test only'}\n"
    )
    rules = load_rules(sectors, ov)
    asml = classify_rec(record("ASML"), ["ASML"], rules)
    assert asml.sector is Sector.TECHNOLOGY and "semis equipment" in asml.reasons[-1]
    assert classify_rec(record("AAPL"), ["AAPL"], rules).kind is Kind.SHELL

    ov.write_text("overrides:\n  - {ticker: X, reason: 'nothing set'}\n")
    with pytest.raises(ValidationError):
        load_rules(sectors, ov)
