"""Company metadata and filing dates from SEC submissions JSON (WT-01 step 3).

Parsing is pure; `read_submissions` is the only function that touches the zip.

`filings.recent` covers at least the last year (or 1,000 filings); older filings live in extra
`CIK##########-submissions-NNN.json` pages, used only when no annual report is found in `recent`.
"""

import calendar
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import orjson
import yaml

from glint.core.settings import REPO_ROOT

ANNUAL_FORMS = frozenset({"10-K", "10-KT", "20-F", "40-F"})
QUARTERLY_FORMS = frozenset({"10-Q", "10-QT"})
FOREIGN_ANNUAL_FORMS = frozenset({"20-F", "40-F"})
TRANSITION_FORMS = frozenset({"10-KT", "10-QT"})
THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"


@dataclass(frozen=True)
class FilingRules:
    """Late-filer and fiscal-year-change rules, from `config/thresholds.yaml` (`flags.late_filer`,
    `flags.fy_change`; principle 8). No defaults here: the config is the only source."""

    nt_forms: frozenset[str]
    nt_lookback_months: int
    fy_change_lookback_years: int
    fy_end_drift_days: int


@cache
def load_filing_rules(path: Path = THRESHOLDS_PATH) -> FilingRules:
    flags: dict[str, Any] = yaml.safe_load(path.read_text())["flags"]
    late, fy = flags["late_filer"], flags["fy_change"]
    return FilingRules(
        nt_forms=frozenset(str(f) for f in late["forms"]),
        nt_lookback_months=int(late["lookback_months"]),
        fy_change_lookback_years=int(fy["lookback_years"]),
        fy_end_drift_days=int(fy["fy_end_drift_days"]),
    )


def months_before(d: date, months: int) -> date:
    """The same day `months` calendar months earlier (the month's last day when it has fewer)."""
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


@dataclass(frozen=True)
class Filing:
    form: str
    filed: date
    accn: str
    report_date: date | None


@dataclass(frozen=True)
class SubmissionRecord:
    cik: str
    name: str
    sec_tickers: list[str]
    sec_exchanges: list[str | None]
    sic: int | None
    sic_description: str | None
    state_of_inc: str | None
    fiscal_year_end: str | None
    category: str | None
    entity_type: str | None
    former_names: list[str]
    last_annual: Filing | None
    last_quarterly: Filing | None
    nt_filing_12m: bool
    fy_end_changed: bool
    fy_change_evidence: list[str] = field(default_factory=list[str])
    recent_forms: frozenset[str] = frozenset()


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def filings_from_columns(cols: dict[str, list[Any]]) -> list[Filing]:
    """Column-oriented `recent` (or a submissions page) → filings, newest first."""
    forms = cols.get("form") or []
    out: list[Filing] = []
    for i, form in enumerate(forms):
        filed = _date(cols["filingDate"][i])
        if filed is None:
            continue
        report = cols.get("reportDate")
        out.append(
            Filing(
                form=str(form),
                filed=filed,
                accn=str(cols["accessionNumber"][i]),
                report_date=_date(report[i]) if report else None,
            )
        )
    out.sort(key=lambda f: (f.filed, f.accn), reverse=True)
    return out


def latest(filings: Iterable[Filing], forms: frozenset[str]) -> Filing | None:
    return next((f for f in filings if f.form in forms), None)


def _md_distance(a: date, b: date) -> int:
    """Days between two dates' month-day, ignoring year, on a circular calendar."""
    da = (date(2001, a.month, min(a.day, 28)) - date(2001, 1, 1)).days
    db = (date(2001, b.month, min(b.day, 28)) - date(2001, 1, 1)).days
    d = abs(da - db)
    return min(d, 365 - d)


def detect_fy_change(
    filings: list[Filing], as_of: date, rules: FilingRules | None = None
) -> list[str]:
    """Evidence that the fiscal year end changed in the last `fy_change_lookback_years` years
    (empty = no change).

    Signals: a transition report (10-KT / 10-QT), or two annual reports whose period-end
    month-day differ by more than the 52/53-week drift.
    """
    r = rules or load_filing_rules()
    since = months_before(as_of, 12 * r.fy_change_lookback_years)
    evidence = [
        f"{f.form} filed {f.filed} ({f.accn})"
        for f in filings
        if f.form in TRANSITION_FORMS and f.filed >= since
    ]
    annuals = [
        f
        for f in filings
        if f.form in ANNUAL_FORMS - TRANSITION_FORMS and f.report_date is not None
    ]
    for newer, older in pairwise(annuals):
        if newer.filed < since:
            break
        assert newer.report_date is not None and older.report_date is not None
        if _md_distance(newer.report_date, older.report_date) > r.fy_end_drift_days:
            evidence.append(
                f"annual period end moved {older.report_date} → {newer.report_date} "
                f"({older.form} {older.accn} → {newer.form} {newer.accn})"
            )
    return evidence


def _clean_category(raw: Any) -> str | None:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).split("<br>") if p.strip()]
    return " | ".join(parts) or None


def parse_submission(
    doc: dict[str, Any],
    as_of: date,
    older_pages: Iterable[dict[str, Any]] = (),
    rules: FilingRules | None = None,
) -> SubmissionRecord:
    r = rules or load_filing_rules()
    recent = filings_from_columns(doc.get("filings", {}).get("recent", {}))
    filings = recent
    if latest(recent, ANNUAL_FORMS) is None:
        for page in older_pages:
            filings = filings + filings_from_columns(page)
        filings.sort(key=lambda f: (f.filed, f.accn), reverse=True)
    window = months_before(as_of, r.nt_lookback_months)
    sic = str(doc.get("sic") or "").strip()
    fy_evidence = detect_fy_change(filings, as_of, r)
    tickers: list[Any] = doc.get("tickers") or []
    exchanges: list[Any] = doc.get("exchanges") or []
    former: list[dict[str, Any]] = doc.get("formerNames") or []
    return SubmissionRecord(
        cik=str(doc["cik"]).zfill(10),
        name=str(doc.get("name") or "").strip(),
        sec_tickers=[str(t) for t in tickers],
        sec_exchanges=[str(e) if e else None for e in exchanges],
        sic=int(sic) if sic.isdigit() and int(sic) > 0 else None,  # "0000" means no SIC
        sic_description=doc.get("sicDescription") or None,
        state_of_inc=doc.get("stateOfIncorporation") or None,
        fiscal_year_end=doc.get("fiscalYearEnd") or None,
        category=_clean_category(doc.get("category")),
        entity_type=doc.get("entityType") or None,
        former_names=[str(n["name"]) for n in former if n.get("name")],
        last_annual=latest(filings, ANNUAL_FORMS),
        last_quarterly=latest(filings, QUARTERLY_FORMS),
        nt_filing_12m=any(f.form in r.nt_forms and f.filed >= window for f in filings),
        fy_end_changed=bool(fy_evidence),
        fy_change_evidence=fy_evidence,
        recent_forms=frozenset(f.form for f in recent),
    )


def read_submissions(
    zip_path: Path, ciks: Iterable[str], as_of: date, rules: FilingRules | None = None
) -> tuple[dict[str, SubmissionRecord], list[str]]:
    """Parse the submissions of the given CIKs straight from the zip.

    Returns (records by CIK, CIKs with no submissions member). Older pages are read only for
    companies whose `recent` block has no annual report."""
    records: dict[str, SubmissionRecord] = {}
    missing: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for cik in sorted(set(ciks)):
            member = f"CIK{cik}.json"
            if member not in names:
                missing.append(cik)
                continue
            doc = orjson.loads(zf.read(member))
            recent = filings_from_columns(doc.get("filings", {}).get("recent", {}))
            pages: list[dict[str, Any]] = []
            if latest(recent, ANNUAL_FORMS) is None:
                files: list[dict[str, Any]] = doc.get("filings", {}).get("files") or []
                pages = [orjson.loads(zf.read(f["name"])) for f in files if f.get("name") in names]
            records[cik] = parse_submission(doc, as_of, older_pages=pages, rules=rules)
    return records, missing
