"""Build the `companies` table for one SEC download folder (WT-01 steps 3–5).

One row per CIK in company_tickers_exchange.json. Written to <folder>/companies.parquet with the
contract's `companies` columns first, then provenance columns (`sec_*`, filing accessions,
evidence) that WT-07 may ignore. CIKs with tickers but no XBRL facts stay, with has_facts=false.
"""

import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import polars as pl

from glint.contracts.enums import Kind
from glint.core.log import get_logger, log_event
from glint.ingest.sec.covers import DOMESTIC_FORMS, load_cover
from glint.universe.classify import Rules, classify, load_rules, no_common_equity_reason
from glint.universe.facts_profile import (
    PER_SHARE_ITEMS,
    EquityEvidence,
    FactsProfile,
    equity_evidence,
    facts_profiles,
    line_item_tags,
    revenue_tags,
)
from glint.universe.leases import LeasePresentation, finance_lease_presentation
from glint.universe.listed_classes import ListedClass, listed_classes, load_exclusions
from glint.universe.predecessors import load_predecessors
from glint.universe.submissions import SubmissionRecord, read_submissions
from glint.universe.tickers import build_ticker_map
from glint.universe.upc import UpC, confirmed_up_c, detect_up_c

log = get_logger(__name__)

COMPANIES_FILE = "companies.parquet"
CONTRACT_COLUMNS = (
    "cik", "name", "tickers", "primary_ticker", "exchange", "sic", "sic_description", "sector",
    "state_of_inc", "fiscal_year_end", "filer_category", "kind", "is_foreign_filer", "is_reit",
    "has_facts", "taxonomy", "reporting_currency", "last_annual_date", "last_quarterly_date",
    "nt_filing_12m", "fy_end_changed", "is_up_c", "up_c_evidence", "finance_lease_status",
    "finance_lease_evidence",
)  # fmt: skip
LISTED_CLASS_FIELDS: dict[str, Any] = {
    "ticker": pl.String,
    "symbol": pl.String,
    "member": pl.String,
    "shares": pl.Float64,
    "as_of": pl.Date,
    "accn": pl.String,
    "form": pl.String,
}
SCHEMA: dict[str, Any] = {
    "cik": pl.String,
    "name": pl.String,
    "tickers": pl.List(pl.String),
    "primary_ticker": pl.String,
    "exchange": pl.String,
    "sic": pl.Int32,
    "sic_description": pl.String,
    "sector": pl.String,
    "state_of_inc": pl.String,
    "fiscal_year_end": pl.String,
    "filer_category": pl.String,
    "kind": pl.String,
    "is_foreign_filer": pl.Boolean,
    "is_reit": pl.Boolean,
    "has_facts": pl.Boolean,
    "taxonomy": pl.String,
    "reporting_currency": pl.String,
    "last_annual_date": pl.Date,
    "last_quarterly_date": pl.Date,
    "nt_filing_12m": pl.Boolean,
    "fy_end_changed": pl.Boolean,
    "is_up_c": pl.Boolean,
    "up_c_evidence": pl.String,
    "finance_lease_status": pl.String,
    "finance_lease_evidence": pl.String,
    # provenance (not in the contract)
    "sec_symbols": pl.List(pl.String),
    "sec_exchange": pl.String,
    "entity_type": pl.String,
    "former_names": pl.List(pl.String),
    "last_annual_form": pl.String,
    "last_annual_accn": pl.String,
    "last_quarterly_accn": pl.String,
    "fy_change_evidence": pl.List(pl.String),
    "classification_notes": pl.List(pl.String),
    "predecessor_cik": pl.String,
    "currency_basis": pl.String,
    # Up-C economic share count for financials/shares.py (null unless is_up_c)
    "economic_shares": pl.Float64,
    "economic_shares_as_of": pl.Date,
    "economic_shares_accn": pl.String,
    "economic_shares_filed": pl.Date,
    # Finance-lease presentation for financials (null unless finance_lease_status = 'stated'):
    # the balance-sheet lines the filing names, by part of the lease liability
    "finance_lease_lines_current": pl.List(pl.String),
    "finance_lease_lines_noncurrent": pl.List(pl.String),
    "finance_lease_lines_total": pl.List(pl.String),
    "finance_lease_accn": pl.String,
    "finance_lease_as_of": pl.Date,
    "finance_lease_since": pl.Date,
    # Separately listed cover-page classes for metrics/share_classes.py (null unless every
    # common class on the latest 10-K/10-Q cover has its own trading symbol; never for Up-Cs)
    "listed_classes": pl.List(pl.Struct(LISTED_CLASS_FIELDS)),
}


@dataclass(frozen=True)
class BuildReport:
    path: Path
    companies: int
    missing_submissions: list[str]
    seconds: float


# Kind/foreign status of these rows is unverified; the build report lists them.
NO_SUBMISSIONS = "no submissions member"


def build_companies(folder: Path, as_of: date, rules: Rules | None = None) -> pl.DataFrame:
    rules = rules or load_rules()
    tmap = build_ticker_map(orjson.loads((folder / "company_tickers_exchange.json").read_bytes()))
    predecessors = load_predecessors()
    wanted = set(tmap) | {link.predecessor_cik for link in predecessors.values()}
    subs, _ = read_submissions(folder / "submissions.zip", wanted, as_of)
    profiles = facts_profiles(folder / "facts_raw", revenue_tags())
    evidence = equity_evidence(folder / "facts_raw", line_item_tags(*PER_SHARE_ITEMS))
    none = FactsProfile(False, None, None)
    excluded = frozenset(load_exclusions())

    rows: list[dict[str, Any]] = []
    for cik in sorted(tmap):
        info = tmap[cik]
        rec = subs.get(cik)
        prof = profiles.get(cik, none)
        link = predecessors.get(cik)
        notes: list[str] = []
        if link is not None:
            pred = subs.get(link.predecessor_cik)
            if not prof.has_facts or prof.taxonomy is None:
                prof = profiles.get(link.predecessor_cik, prof)
            if rec is not None and rec.last_annual is None and pred and pred.last_annual:
                rec = replace(rec, last_annual=pred.last_annual)
                notes.append(f"last annual report from predecessor CIK {link.predecessor_cik}")
        row: dict[str, Any] = {
            "cik": cik,
            "name": (rec.name if rec else "") or info.sec_name,
            "tickers": info.tickers,
            "primary_ticker": info.primary.ticker,
            "exchange": info.primary.exchange.value if info.primary.exchange else None,
            "sec_symbols": info.sec_symbols,
            "sec_exchange": info.primary.sec_exchange,
            "has_facts": prof.has_facts,
            "taxonomy": prof.taxonomy,
            "reporting_currency": prof.reporting_currency,
            "currency_basis": prof.basis,
            "predecessor_cik": link.predecessor_cik if link else None,
        }
        ev = evidence.get(cik)
        if link is not None and link.predecessor_cik in evidence:
            # rec.last_annual may be the predecessor's 10-K (above): use its facts too.
            ev = (ev or EquityEvidence()).merged(evidence[link.predecessor_cik])
        no_common = no_common_equity_reason(
            has_common_ticker=info.has_common,
            rec=rec,
            evidence=ev,
            as_of=as_of,
            rules=rules,
        )
        if rec is None:
            kind = Kind.NO_COMMON_EQUITY if no_common else Kind.OPERATING
            sub_notes = [NO_SUBMISSIONS, *([no_common] if no_common else [])]
            row.update(sector=rules.default_sector.value, kind=kind.value, is_foreign_filer=False,
                       is_reit=False, nt_filing_12m=False, fy_end_changed=False,
                       classification_notes=sub_notes)  # fmt: skip
        else:
            c = classify(rec, info.tickers, rules, no_common=no_common, as_of=as_of)
            row.update(
                sic=rec.sic,
                sic_description=rec.sic_description,
                sector=c.sector.value,
                state_of_inc=rec.state_of_inc,
                fiscal_year_end=rec.fiscal_year_end,
                filer_category=rec.category,
                kind=c.kind.value,
                is_foreign_filer=c.is_foreign_filer,
                is_reit=c.is_reit,
                last_annual_date=rec.last_annual.filed if rec.last_annual else None,
                last_quarterly_date=rec.last_quarterly.filed if rec.last_quarterly else None,
                nt_filing_12m=rec.nt_filing_12m,
                fy_end_changed=rec.fy_end_changed,
                entity_type=rec.entity_type,
                former_names=rec.former_names,
                last_annual_form=rec.last_annual.form if rec.last_annual else None,
                last_annual_accn=rec.last_annual.accn if rec.last_annual else None,
                last_quarterly_accn=rec.last_quarterly.accn if rec.last_quarterly else None,
                fy_change_evidence=rec.fy_change_evidence,
                classification_notes=c.reasons + notes,
            )
            upc = _up_c(folder.parent, rec, c.is_foreign_filer, rules)
            if upc is not None:
                row.update(
                    is_up_c=True,
                    up_c_evidence=upc.evidence,
                    economic_shares=upc.economic_shares,
                    economic_shares_as_of=upc.as_of,
                    economic_shares_accn=upc.accn,
                    economic_shares_filed=upc.filed,
                    classification_notes=[*row["classification_notes"], f"Up-C: {upc.evidence}"],
                )
            lease = _finance_lease(folder.parent, rec, c.is_foreign_filer)
            if lease is not None:
                row.update(
                    finance_lease_status=lease.status,
                    finance_lease_evidence=lease.evidence,
                    finance_lease_lines_current=lease.lines.get("current"),
                    finance_lease_lines_noncurrent=lease.lines.get("noncurrent"),
                    finance_lease_lines_total=lease.lines.get("total"),
                    finance_lease_accn=lease.accn,
                    finance_lease_as_of=lease.as_of,
                    finance_lease_since=lease.since,
                )
            listed = _listed(folder.parent, rec, c.is_foreign_filer, info.tickers,
                             is_up_c=upc is not None, excluded=excluded)  # fmt: skip
            if listed:
                row["listed_classes"] = [vars(x) for x in listed]
        row.setdefault("is_up_c", False)
        rows.append(row)
    return pl.DataFrame(rows, schema=SCHEMA)


def _up_c(sec_raw: Path, rec: SubmissionRecord, foreign: bool, rules: Rules) -> UpC | None:
    """Up-C evidence from the latest 10-K/10-Q's cover facts (fetched by ingest/sec/covers.py;
    none cached → not detected). Domestic filers only. `up_c.excluded` wins, then
    `up_c.confirmed` (the sum of the cover classes), then the NCI rule."""
    filings = [f for f in (rec.last_annual, rec.last_quarterly) if f is not None]
    if foreign or not filings:
        return None
    latest = max(filings, key=lambda f: (f.filed, f.accn))
    if latest.form not in DOMESTIC_FORMS:
        return None
    if rules.up_c.is_excluded(rec.cik):
        return None
    cover = load_cover(sec_raw, rec.cik, latest.accn)
    if cover is None:
        return None
    detected = detect_up_c(cover, rules.up_c)
    entry = rules.up_c.confirmed_entry(rec.cik)
    if entry is None:
        return detected
    if detected is not None:
        log_event(log, "up_c_confirmed_entry_redundant", cik=rec.cik, ticker=entry.ticker)
    confirmed = confirmed_up_c(cover, entry)
    if confirmed is None:
        log_event(log, "up_c_confirmed_cover_mismatch", cik=rec.cik, ticker=entry.ticker,
                  accn=latest.accn, classes=list(entry.classes))  # fmt: skip
    return confirmed


def _finance_lease(sec_raw: Path, rec: SubmissionRecord, foreign: bool) -> LeasePresentation | None:
    """Finance-lease presentation from the latest 10-K/10-Q's cover facts, else the latest
    10-K's (both fetched by ingest/sec/covers.py; none cached → None). Domestic filers only."""
    filings = [f for f in (rec.last_annual, rec.last_quarterly) if f is not None]
    if foreign or not filings:
        return None
    latest = max(filings, key=lambda f: (f.filed, f.accn))
    if latest.form not in DOMESTIC_FORMS:
        return None
    annual = rec.last_annual
    older = annual is not None and annual is not latest and annual.form in DOMESTIC_FORMS
    return finance_lease_presentation(
        load_cover(sec_raw, rec.cik, latest.accn),
        load_cover(sec_raw, rec.cik, annual.accn) if older and annual else None,
    )


def _listed(
    sec_raw: Path,
    rec: SubmissionRecord,
    foreign: bool,
    tickers: list[str],
    *,
    is_up_c: bool,
    excluded: frozenset[str],
) -> list[ListedClass]:
    """Separately listed classes from the latest 10-K/10-Q's cached cover (none cached → none).
    Domestic filers only; Up-Cs and `cover_excluded` CIKs get none."""
    filings = [f for f in (rec.last_annual, rec.last_quarterly) if f is not None]
    if foreign or is_up_c or not filings or rec.cik in excluded:
        return []
    latest = max(filings, key=lambda f: (f.filed, f.accn))
    if latest.form not in DOMESTIC_FORMS:
        return []
    cover = load_cover(sec_raw, rec.cik, latest.accn)
    if cover is None:
        return []
    return listed_classes(cover, tickers, is_up_c=is_up_c, excluded=excluded)


def write_companies(folder: Path, as_of: date) -> BuildReport:
    started = time.monotonic()
    df = build_companies(folder, as_of)
    path = folder / COMPANIES_FILE
    tmp = path.with_suffix(".parquet.tmp")
    df.write_parquet(tmp, compression="zstd")
    tmp.replace(path)
    missing = df.filter(pl.col("classification_notes").list.contains(NO_SUBMISSIONS))["cik"]
    report = BuildReport(path, df.height, missing.to_list(), round(time.monotonic() - started, 1))
    log_event(log, "companies_written", rows=df.height, path=str(path), seconds=report.seconds)
    return report
