"""Kind no_common_equity: issuers whose listed tickers are all debt or preferred securities."""

import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import pytest

from glint.contracts.enums import Kind
from glint.fixtures.sec import FIXTURE_DIR
from glint.ingest.sec.extract import extract_facts, load_whitelist
from glint.universe.classify import classify, load_rules, no_common_equity_reason
from glint.universe.facts_profile import (
    PER_SHARE_ITEMS,
    EquityEvidence,
    equity_evidence,
    line_item_tags,
)
from glint.universe.submissions import Filing, SubmissionRecord, parse_submission
from glint.universe.tickers import build_ticker_map

AS_OF = date(2026, 10, 30)
RULES = load_rules()
TENK = Filing(form="10-K", filed=date(2026, 8, 4), accn="0001376986-26-000036", report_date=None)
OLD_10Q = Filing(form="10-Q", filed=date(2026, 5, 5), accn="0001376986-26-000029", report_date=None)


def record(ticker: str = "AAPL", **kw: Any) -> SubmissionRecord:
    doc: dict[str, Any] = orjson.loads((FIXTURE_DIR / f"{ticker}.submissions.json").read_bytes())
    return replace(parse_submission(doc, AS_OF), **kw)


def reason(
    rec: SubmissionRecord | None,
    evidence: EquityEvidence | None,
    *,
    has_common: bool = True,
) -> str | None:
    return no_common_equity_reason(
        has_common_ticker=has_common, rec=rec, evidence=evidence, as_of=AS_OF, rules=RULES
    )


# --- rule A: no ticker is common stock ---------------------------------------------------------


def test_preferred_only_issuer_has_no_common_ticker() -> None:
    fields = ["cik", "name", "ticker", "exchange"]
    tmap = build_ticker_map({"fields": fields, "data": [
        [201533, "CONSUMERS ENERGY CO", "CMS-PB", "NYSE"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-A", "NYSE"],
        [70502, "AGNC-like", "AGNC", "Nasdaq"],
        [70502, "AGNC-like", "AGNCP", "Nasdaq"],
    ]})  # fmt: skip
    cms, brk, agnc = tmap["0000201533"], tmap["0001067983"], tmap["0000070502"]
    assert not cms.has_common and cms.primary.ticker == "CMS.PB"  # fallback primary kept
    assert brk.has_common and agnc.has_common
    assert reason(None, None, has_common=False) is not None


# --- rule B: tiny cover count and no per-share data ----------------------------------------------


def test_zero_cover_count_and_no_eps_is_no_common_equity() -> None:
    """TVA (CIK 1376986): its 10-K reports 0 common shares, and it never reports EPS."""
    rec = record(last_annual=TENK, last_quarterly=OLD_10Q)
    why = reason(rec, EquityEvidence({TENK.accn: 0.0}, None))
    assert why is not None and TENK.accn in why and "0 common shares" in why


def test_latest_filing_only() -> None:
    """SPG, TAP, FOXA: an old filing tagged 0 or 1, the latest tags its counts by class only."""
    rec = record(last_annual=OLD_10Q, last_quarterly=TENK)  # TENK filed later
    assert reason(rec, EquityEvidence({OLD_10Q.accn: 0.0}, None)) is None


def test_recent_eps_keeps_the_company() -> None:
    """SLSR (0), HQ (1), AVAL (7): tiny cover counts, but they report EPS."""
    rec = record(last_annual=TENK, last_quarterly=None)
    assert reason(rec, EquityEvidence({TENK.accn: 1.0}, date(2025, 12, 31))) is None
    # EPS older than the lookback doesn't count.
    assert reason(rec, EquityEvidence({TENK.accn: 1.0}, date(2023, 12, 31))) is not None


def test_cover_count_above_threshold_keeps_the_company() -> None:
    """Athene (203,805 shares, all held by Apollo) is above max_cover_shares on purpose."""
    rec = record(last_annual=TENK, last_quarterly=None)
    limit = RULES.no_common_equity.max_cover_shares
    assert reason(rec, EquityEvidence({TENK.accn: limit}, None)) is not None
    assert reason(rec, EquityEvidence({TENK.accn: 203_805.0}, None)) is None


def test_no_undimensioned_cover_count_keeps_the_company() -> None:
    """GOOGL and BRK tag their cover counts by class only: no undimensioned count, no rule B."""
    rec = record(last_annual=TENK, last_quarterly=None)
    assert reason(rec, EquityEvidence({}, None)) is None
    assert reason(rec, None) is None


# --- classify ---------------------------------------------------------------------------------


def test_classify_sets_the_kind_with_its_reason() -> None:
    c = classify(record(), ["TVE", "TVC"], RULES, no_common="kind no_common_equity: because")
    assert c.kind is Kind.NO_COMMON_EQUITY and "kind no_common_equity: because" in c.reasons
    assert classify(record(), ["AAPL"], RULES).kind is Kind.OPERATING


def test_spac_kind_wins() -> None:
    """A SPAC listing only units and warrants stays a SPAC."""
    spac = classify(record("AAC"), ["AAC.U"], RULES, no_common="kind no_common_equity: units")
    assert spac.kind is Kind.SPAC


def test_override_keeps_qvcg_operating_until_its_review_date() -> None:
    qvcg = RULES.overrides["QVCG"]
    assert qvcg.kind is Kind.OPERATING and qvcg.review_by is not None
    why = "kind no_common_equity: cover page reports 1 common shares"
    before = classify(record(), ["QVCG"], RULES, no_common=why, as_of=qvcg.review_by)
    assert before.kind is Kind.OPERATING
    assert not any("due for review" in r for r in before.reasons)
    after = classify(record(), ["QVCG"], RULES, no_common=why, as_of=date(2026, 12, 1))
    assert after.kind is Kind.OPERATING
    assert any("QVCG was due for review by 2026-11-30" in r for r in after.reasons)


# --- real fixtures: every Appendix D company keeps its kind --------------------------------------


@pytest.fixture(scope="module")
def fixture_evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, EquityEvidence]:
    d = tmp_path_factory.mktemp("facts")
    manifest = orjson.loads((FIXTURE_DIR / "manifest.json").read_bytes())
    with zipfile.ZipFile(d / "companyfacts.zip", "w") as zf:
        for f in manifest["fixtures"]:
            payload = (FIXTURE_DIR / f"{f['ticker']}.companyfacts.json").read_bytes()
            zf.writestr(f"CIK{f['cik']}.json", payload)
    extract_facts(
        d / "companyfacts.zip", d / "facts_raw", source_sha256="x", whitelist=load_whitelist()
    )
    return equity_evidence(d / "facts_raw", line_item_tags(*PER_SHARE_ITEMS))


@pytest.mark.parametrize(
    "ticker",
    ["AAPL", "MSFT", "NVDA", "KO", "JPM", "O", "BRK.B", "GOOGL", "TSM", "ASML", "SEV", "ANAB"],
)
def test_appendix_d_companies_have_common_equity(
    ticker: str, fixture_evidence: dict[str, EquityEvidence]
) -> None:
    rec = record(ticker)
    assert reason(rec, fixture_evidence.get(rec.cik)) is None


def test_equity_evidence_reads_cover_counts_and_eps(
    fixture_evidence: dict[str, EquityEvidence],
) -> None:
    aapl = fixture_evidence[record("AAPL").cik]
    assert aapl.cover_by_accn and all(v > 1e8 for v in aapl.cover_by_accn.values())
    assert aapl.last_per_share_end is not None and aapl.last_per_share_end >= date(2025, 1, 1)


def test_missing_facts_dir_gives_no_evidence(tmp_path: Path) -> None:
    (tmp_path / "facts_raw").mkdir()
    assert equity_evidence(tmp_path / "facts_raw", line_item_tags(*PER_SHARE_ITEMS)) == {}


def test_evidence_keys_match_submission_accessions(
    fixture_evidence: dict[str, EquityEvidence],
) -> None:
    """Rule B looks up the latest filing's accession in facts_raw: the two must use one format."""
    for ticker in ("AAPL", "MSFT", "KO"):
        rec = record(ticker)
        filings = [f for f in (rec.last_annual, rec.last_quarterly) if f is not None]
        assert any(f.accn in fixture_evidence[rec.cik].cover_by_accn for f in filings), ticker


def test_predecessor_evidence_is_merged() -> None:
    """XOM-style successor: its latest annual report is the predecessor's 10-K."""
    succ = EquityEvidence({"succ-10q": 5.0}, None)
    pred = EquityEvidence({TENK.accn: 0.0, "succ-10q": 9.0}, date(2025, 12, 31))
    m = succ.merged(pred)
    assert m.cover_by_accn == {TENK.accn: 0.0, "succ-10q": 5.0}  # the successor's own wins
    assert m.last_per_share_end == date(2025, 12, 31)
    assert succ.merged(None) is succ


def test_missing_thresholds_are_a_contract_error(tmp_path: Path) -> None:
    from glint.core.errors import ContractError  # noqa: PLC0415
    from glint.universe.classify import OVERRIDES_PATH, SECTORS_PATH  # noqa: PLC0415

    doc = SECTORS_PATH.read_text().split("no_common_equity:\n")[0]
    (tmp_path / "sectors.yaml").write_text(doc)
    with pytest.raises(ContractError, match="no_common_equity"):
        load_rules(tmp_path / "sectors.yaml", OVERRIDES_PATH)


def test_lookback_cutoff_is_calendar_months() -> None:
    from glint.universe.classify import months_before  # noqa: PLC0415

    assert months_before(date(2026, 10, 30), 24) == date(2024, 10, 30)
    assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
