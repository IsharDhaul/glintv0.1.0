import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import pytest

from glint.fixtures.sec import FIXTURE_DIR
from glint.universe.submissions import (
    FilingRules,
    detect_fy_change,
    filings_from_columns,
    load_filing_rules,
    months_before,
    parse_submission,
    read_submissions,
)

AS_OF = date(2026, 10, 29)


def fixture(ticker: str) -> dict[str, Any]:
    return orjson.loads((FIXTURE_DIR / f"{ticker}.submissions.json").read_bytes())


def cols(*rows: tuple[str, str, str | None]) -> dict[str, list[Any]]:
    """rows: (form, filingDate, reportDate)"""
    return {
        "form": [r[0] for r in rows],
        "filingDate": [r[1] for r in rows],
        "reportDate": [r[2] or "" for r in rows],
        "accessionNumber": [f"0000000001-00-{i:06d}" for i in range(len(rows))],
    }


def doc(*rows: tuple[str, str, str | None], **extra: Any) -> dict[str, Any]:
    return {"cik": "1", "name": "X", "filings": {"recent": cols(*rows)}, **extra}


def test_aapl_from_fixture() -> None:
    rec = parse_submission(fixture("AAPL"), AS_OF)
    assert rec.cik == "0000320193"
    assert rec.name == "Apple Inc."
    assert rec.sic == 3571 and rec.sic_description == "Electronic Computers"
    assert rec.fiscal_year_end == "0926"
    assert rec.state_of_inc == "CA"
    assert rec.entity_type == "operating"
    assert rec.sec_tickers == ["AAPL"] and rec.sec_exchanges == ["Nasdaq"]
    assert rec.last_annual is not None and rec.last_annual.form == "10-K"
    assert rec.last_annual.filed.year >= 2025
    assert rec.last_quarterly is not None and rec.last_quarterly.form == "10-Q"
    assert not rec.fy_end_changed


@pytest.mark.parametrize("ticker", ["NVDA", "MU", "MSFT", "KO"])
def test_52_53_week_and_regular_years_are_not_fy_changes(ticker: str) -> None:
    rec = parse_submission(fixture(ticker), AS_OF)
    assert not rec.fy_end_changed, rec.fy_change_evidence


def test_foreign_filer_annual_is_20f() -> None:
    rec = parse_submission(fixture("TSM"), AS_OF)
    assert rec.last_annual is not None and rec.last_annual.form == "20-F"
    assert rec.last_quarterly is None


def test_anab_transition_report_flags_fy_change() -> None:
    rec = parse_submission(fixture("ANAB"), AS_OF)
    assert rec.fy_end_changed
    assert any("10-KT" in e for e in rec.fy_change_evidence)


def test_category_html_is_cleaned() -> None:
    rec = parse_submission(
        doc(category="Non-accelerated filer<br>Smaller reporting company"), AS_OF
    )
    assert rec.category == "Non-accelerated filer | Smaller reporting company"


def test_nt_filing_window_is_12_months() -> None:
    recent = parse_submission(doc(("NT 10-K", "2026-03-31", None)), AS_OF)
    old = parse_submission(doc(("NT 10-Q", "2025-08-01", None)), AS_OF)
    assert recent.nt_filing_12m and not old.nt_filing_12m


def test_period_end_shift_between_annual_reports() -> None:
    filings = filings_from_columns(
        cols(("10-K", "2026-08-20", "2026-06-30"), ("10-K", "2026-02-25", "2025-12-31"))
    )
    evidence = detect_fy_change(filings, AS_OF)
    assert evidence and "2025-12-31 → 2026-06-30" in evidence[0]


def test_old_fy_change_is_ignored() -> None:
    filings = filings_from_columns(
        cols(
            ("10-K", "2026-08-20", "2026-06-30"),
            ("10-K", "2025-08-20", "2025-06-30"),
            ("10-KT", "2023-09-01", "2023-06-30"),
        )
    )
    assert detect_fy_change(filings, AS_OF) == []


def test_read_submissions_from_zip(tmp_path: Path) -> None:
    z = tmp_path / "submissions.zip"
    old = doc(("8-K", "2026-09-01", None))
    old["cik"] = "2"
    old["filings"]["files"] = [{"name": "CIK0000000002-submissions-001.json"}]
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CIK0000320193.json", orjson.dumps(fixture("AAPL")))
        zf.writestr("CIK0000000002.json", orjson.dumps(old))
        zf.writestr(
            "CIK0000000002-submissions-001.json",
            orjson.dumps(cols(("10-K", "2024-03-01", "2023-12-31"))),
        )
    records, missing = read_submissions(z, ["0000320193", "0000000002", "0000000099"], AS_OF)
    assert set(records) == {"0000320193", "0000000002"}
    assert missing == ["0000000099"]
    two = records["0000000002"].last_annual
    assert two is not None and two.filed == date(2024, 3, 1)


def test_falls_back_to_older_pages_for_annual_report() -> None:
    d = doc(("8-K", "2026-09-01", None))
    page = cols(("10-K", "2024-03-01", "2023-12-31"))
    rec = parse_submission(d, AS_OF, older_pages=[page])
    assert rec.last_annual is not None and rec.last_annual.filed == date(2024, 3, 1)
    assert parse_submission(d, AS_OF).last_annual is None


def test_filing_rules_come_from_thresholds_yaml() -> None:
    """Principle 8: the late-filer and FY-change rules are config, not constants."""
    assert load_filing_rules() == FilingRules(
        nt_forms=frozenset({"NT 10-K", "NT 10-Q"}),
        nt_lookback_months=12,
        fy_change_lookback_years=2,
        fy_end_drift_days=10,
    )


def test_months_before_is_calendar_months() -> None:
    assert months_before(date(2026, 10, 29), 12) == date(2025, 10, 29)
    assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)  # month-end clamps
    assert months_before(date(2028, 2, 29), 12) == date(2027, 2, 28)  # leap day
    assert months_before(date(2026, 1, 15), 24) == date(2024, 1, 15)


def test_changing_the_config_changes_the_result() -> None:
    nt = doc(("NT 10-K", "2025-08-01", None))
    base = load_filing_rules()
    assert not parse_submission(nt, AS_OF, rules=base).nt_filing_12m
    longer = FilingRules(base.nt_forms, 18, base.fy_change_lookback_years, base.fy_end_drift_days)
    assert parse_submission(nt, AS_OF, rules=longer).nt_filing_12m
    only_q = FilingRules(frozenset({"NT 10-Q"}), 18, 2, 10)
    assert not parse_submission(nt, AS_OF, rules=only_q).nt_filing_12m
    moved = filings_from_columns(cols(
        ("10-K", "2026-02-20", "2025-10-14"), ("10-K", "2025-02-20", "2024-10-01"),
    ))  # fmt: skip  # period ends 13 days apart
    assert detect_fy_change(moved, AS_OF, base)
    assert not detect_fy_change(moved, AS_OF, FilingRules(base.nt_forms, 12, 2, 15))
    assert not detect_fy_change(moved, date(2028, 3, 1), FilingRules(base.nt_forms, 12, 1, 10))
