"""Search, the company drawer (§2.9) and metric history."""

import json
from functools import cache
from typing import Annotated, Any

from fastapi import APIRouter, Query

from glint.api.build import Build
from glint.api.deps import CurrentBuild
from glint.api.errors import ApiError
from glint.api.routers.meta import as_of
from glint.api.search import SearchIndex
from glint.api.why import decode_screen, why_passed
from glint.contracts.api import (
    CellNote,
    CompanyHeader,
    CompanyResponse,
    ErrorCode,
    FlagOut,
    HistoryPoint,
    HistoryResponse,
    MetricValue,
    SearchResponse,
    SourceFiling,
)
from glint.contracts.enums import FlagId, FlagSeverity, NoteCode
from glint.core.log import get_logger, log_event
from glint.metrics.params import load_thresholds

log = get_logger(__name__)

router = APIRouter(tags=["companies"])

SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/"


def _index(build: Build) -> SearchIndex:
    return build.cached("search", lambda b: SearchIndex.from_connection(b.cursor()))


@router.get("/api/search")
def search(build: CurrentBuild, q: str = Query(min_length=1)) -> SearchResponse:
    """Up to 10 companies: exact ticker, then ticker prefix, then name prefix, then fuzzy name.
    Every kind is searchable; the hit says which kind it is."""
    query = q.strip()
    if not query:
        raise ApiError(422, ErrorCode.INVALID_REQUEST, "q is blank", ["query", "q"])
    return SearchResponse(build_id=build.build_id, query=query, results=_index(build).search(query))


def sec_filing_url(cik: str, accn: str) -> str:
    return SEC_ARCHIVE_URL.format(cik=int(cik), accn=accn.replace("-", ""))


def _cik_for(build: Build, ticker: str) -> tuple[str, str]:
    found = _index(build).lookup(ticker)
    if found is None:
        raise ApiError(404, ErrorCode.UNKNOWN_TICKER, f"No company with ticker {ticker!r}")
    entry, stored = found
    return entry.cik, stored


def _header(build: Build, cik: str) -> CompanyHeader:
    cur = build.cursor().execute(
        "SELECT cik, name, tickers, primary_ticker, exchange, sector, sic, sic_description, kind,"
        " is_foreign_filer, is_reit, has_facts, filer_category, fiscal_year_end,"
        " reporting_currency, last_annual_date, last_quarterly_date FROM companies WHERE cik = ?",
        [cik],
    )
    row = cur.fetchone()
    assert row is not None, "the search index comes from this table"
    names = [d[0] for d in cur.description]
    r: dict[str, Any] = dict(zip(names, row, strict=True))
    return CompanyHeader.model_validate({**r, "tickers": list(r["tickers"])})


def _metrics(build: Build, cik: str) -> dict[str, MetricValue]:
    """Every live metric, in registry order, with its null reason where there is one."""
    live = [m.id for m in build.registry.live()]
    cur = build.cursor().execute("SELECT * FROM metrics_snapshot WHERE cik = ?", [cik])
    row = cur.fetchone()
    if row is None:
        return {}
    snapshot = dict(zip([d[0] for d in cur.description], row, strict=True))
    notes = {
        metric_id: CellNote(code=NoteCode(code), message=message)
        for metric_id, code, message in build.cursor()
        .execute("SELECT metric_id, code, message FROM metric_notes WHERE cik = ?", [cik])
        .fetchall()
    }
    out: dict[str, MetricValue] = {}
    for mid in live:
        raw = snapshot.get(mid)
        value = raw if raw is None or isinstance(raw, bool) else float(raw)
        out[mid] = MetricValue(value=value, note=notes.get(mid))
    return out


@cache
def flag_severity() -> dict[str, FlagSeverity]:
    """Each flag's severity, from `config/thresholds.yaml` (principle 8)."""
    return {fid: FlagSeverity(cfg["severity"]) for fid, cfg in load_thresholds()["flags"].items()}


def _flags(build: Build, cik: str) -> list[FlagOut]:
    rows = (
        build.cursor()
        .execute(
            "SELECT flag_id, question, evidence FROM flags WHERE cik = ? ORDER BY flag_id", [cik]
        )
        .fetchall()
    )
    severity = flag_severity()
    return [
        FlagOut(flag_id=FlagId(f), severity=severity[f], question=q, evidence=json.loads(ev))
        for f, q, ev in rows
    ]


def _history(build: Build, cik: str, metric: str | None = None) -> dict[str, list[HistoryPoint]]:
    """FY points, then TTM points, each oldest first."""
    sql = "SELECT metric_id, basis, period_end, value FROM metric_history WHERE cik = $cik"
    params: dict[str, Any] = {"cik": cik}
    if metric is not None:
        sql += " AND metric_id = $metric"
        params["metric"] = metric
    rows = build.cursor().execute(sql + " ORDER BY metric_id, basis, period_end", params)
    out: dict[str, list[HistoryPoint]] = {}
    for metric_id, basis, period_end, value in rows.fetchall():
        out.setdefault(metric_id, []).append(
            HistoryPoint(basis=basis, period_end=period_end, value=value)
        )
    return out


def _sources(build: Build, cik: str) -> list[SourceFiling]:
    """The filings the financials came from (distinct `financials.source_accn`), newest first.

    `form` is null: no build table records a filing's form, and it is never guessed."""
    rows = (
        build.cursor()
        .execute(
            "SELECT source_accn, max(filed) AS filed FROM financials "
            "WHERE cik = ? AND source_accn IS NOT NULL GROUP BY source_accn "
            "ORDER BY filed DESC NULLS LAST, source_accn",
            [cik],
        )
        .fetchall()
    )
    undated = [accn for accn, filed in rows if filed is None]
    if undated:
        # `filed` is required by the contract; say so instead of dropping them quietly.
        log_event(log, "sources_without_filed_date", cik=cik, accns=",".join(undated))
    return [
        SourceFiling(accn=accn, form=None, filed=filed, url=sec_filing_url(cik, accn))
        for accn, filed in rows
        if filed is not None
    ]


@router.get("/api/companies/{ticker}")
def company(
    ticker: str,
    build: CurrentBuild,
    screen: Annotated[str | None, Query(description="lz-string compressed Screen JSON")] = None,
) -> CompanyResponse:
    """Any kind of company is served (200), with `company.kind` saying what it is. Unknown
    tickers are 404 UNKNOWN_TICKER. With `screen`, `why_passed` lists every filter leaf."""
    parsed = decode_screen(screen) if screen is not None else None
    cik, _ = _cik_for(build, ticker)
    return CompanyResponse(
        build_id=build.build_id,
        company=_header(build, cik),
        as_of=as_of(build),
        metrics=_metrics(build, cik),
        flags=_flags(build, cik),
        history=_history(build, cik),
        sources=_sources(build, cik),
        why_passed=why_passed(build, parsed, cik) if parsed is not None else None,
    )


@router.get("/api/companies/{ticker}/history")
def history(ticker: str, metric: str, build: CurrentBuild) -> HistoryResponse:
    """One metric's FY and TTM series (empty if the build keeps no history for it)."""
    if metric not in build.registry:
        raise ApiError(404, ErrorCode.UNKNOWN_METRIC, f"No metric {metric!r}")
    cik, stored = _cik_for(build, ticker)
    points = _history(build, cik, metric).get(metric, [])
    return HistoryResponse(build_id=build.build_id, ticker=stored, metric=metric, points=points)
