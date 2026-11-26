"""`glint fixtures sec`: real, trimmed SEC fixtures for the Appendix D tickers.

Everything goes through the SEC gateway. Output (committed): engine/tests/fixtures/sec/
  <TICKER>.companyfacts.json   trimmed to concepts.yaml tags + dei cover tags
  <TICKER>.submissions.json    metadata + recent filings (selected columns)
  company_tickers_exchange.json  rows for the fixture CIKs only
  manifest.json                which ticker plays which role, and the runtime picks
"""

import asyncio
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import orjson
import yaml

from glint.core.errors import SourceError
from glint.core.http import SecGateway
from glint.core.log import get_logger, log_event
from glint.core.settings import REPO_ROOT

log = get_logger(__name__)

FIXTURE_DIR = REPO_ROOT / "engine" / "tests" / "fixtures" / "sec"
CONCEPTS_PATH = REPO_ROOT / "config" / "concepts.yaml"
MAX_TOTAL_BYTES = 25_000_000

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FORM_INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/form.idx"

# Appendix D. Share classes of one CIK share a fixture, named after the first ticker.
FIXED_TICKERS: list[tuple[str, str]] = [
    ("AAPL", "Clean US-GAAP, September FY, large buybacks"),
    ("MSFT", "June FY"),
    ("NVDA", "52/53-week FY ending late January, fast growth"),
    ("KO", "December FY, consumer staples, dividends"),
    ("MU", "Cyclical, recent losses, August/September FY"),
    ("KHC", "Large goodwill and impairments"),
    ("RIVN", "Loss-maker: negative EBIT, NI and FCF"),
    ("SBUX", "Negative equity"),
    ("XOM", "Energy, large capex"),
    ("F", "Captive finance arm: debt and EV look extreme"),
    ("JPM", "Bank: n/m rules"),
    ("O", "REIT"),
    ("BRK.B", "Two share classes at very different prices (with BRK.A)"),
    ("GOOGL", "Two share classes at similar prices, one CIK (with GOOG)"),
    ("TSM", "20-F, IFRS, TWD, ADR"),
    ("ASML", "20-F, EUR"),
]
LISTED_EXCHANGES = frozenset({"NYSE", "Nasdaq", "NYSE American"})
ANNUAL_QUARTERLY_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})
SUBMISSION_COLUMNS = (
    "accessionNumber",
    "filingDate",
    "reportDate",
    "acceptanceDateTime",
    "form",
    "primaryDocument",
    "isXBRL",
    "isInlineXBRL",
)


def sec_symbol(ticker: str) -> str:
    """Glint's canonical `BRK.B` → SEC's `BRK-B`."""
    return ticker.replace(".", "-")


def fixture_name(ticker: str) -> str:
    return ticker.replace("/", "-")


# --- Pure helpers (unit-tested) -----------------------------------------------------------------


def kept_tags(concepts: dict[str, Any]) -> dict[str, set[str]]:
    """taxonomy -> tags to keep, from concepts.yaml: line-item tags, the dei cover tags, and the
    `evidence_tags` groups (taxonomy -> group name -> tags, read by rules that cite them)."""
    keep: dict[str, set[str]] = {"dei": set(concepts.get("dei_cover_tags", []))}
    line_items: dict[str, dict[str, Any]] = concepts["line_items"]
    for spec in line_items.values():
        tags_by_taxonomy: dict[str, list[str]] = spec.get("tags") or {}
        for taxonomy, tags in tags_by_taxonomy.items():
            keep.setdefault(taxonomy, set()).update(tags)
    evidence: dict[str, dict[str, list[str]]] = concepts.get("evidence_tags") or {}
    for taxonomy, groups in evidence.items():
        for tags in groups.values():
            keep.setdefault(taxonomy, set()).update(tags)
    return keep


def trim_companyfacts(facts: dict[str, Any], keep: dict[str, set[str]]) -> dict[str, Any]:
    """Keep only whitelisted tags; drop labels and descriptions. Fact rows are untouched."""
    out: dict[str, Any] = {}
    for taxonomy, tags in facts.get("facts", {}).items():
        wanted = keep.get(taxonomy, set())
        kept = {
            tag: {"units": body["units"]}
            for tag, body in sorted(tags.items())
            if tag in wanted and "units" in body
        }
        if kept:
            out[taxonomy] = kept
    return {"cik": facts.get("cik"), "entityName": facts.get("entityName"), "facts": out}


def trim_submissions(sub: dict[str, Any]) -> dict[str, Any]:
    """Keep company metadata and the recent-filings columns WT-01 needs; drop older pages."""
    out = {k: v for k, v in sub.items() if k != "filings"}
    recent = sub.get("filings", {}).get("recent", {})
    out["filings"] = {"recent": {c: recent[c] for c in SUBMISSION_COLUMNS if c in recent}}
    return out


@dataclass(frozen=True)
class TickerRow:
    cik: int
    name: str
    ticker: str
    exchange: str | None


def parse_tickers_exchange(doc: dict[str, Any]) -> list[TickerRow]:
    idx = {f: i for i, f in enumerate(doc["fields"])}
    return [
        TickerRow(
            int(r[idx["cik"]]), str(r[idx["name"]]), str(r[idx["ticker"]]), r[idx["exchange"]]
        )
        for r in doc["data"]
    ]


_NON_COMMON_SUFFIX = re.compile(r"-(WS|WT|U|UN|R|RT|P[A-Z]?)$")


def primary_rows(rows: list[TickerRow]) -> dict[int, TickerRow]:
    """One row per CIK: the first common-stock ticker (not a warrant, unit or right)."""
    out: dict[int, TickerRow] = {}
    for r in rows:
        current = out.get(r.cik)
        if current is None or (
            _NON_COMMON_SUFFIX.search(current.ticker) and not _NON_COMMON_SUFFIX.search(r.ticker)
        ):
            out[r.cik] = r
    return out


def trim_tickers_exchange(doc: dict[str, Any], ciks: set[int]) -> dict[str, Any]:
    idx = doc["fields"].index("cik")
    return {"fields": doc["fields"], "data": [r for r in doc["data"] if int(r[idx]) in ciks]}


@dataclass(frozen=True)
class IndexEntry:
    form: str
    company: str
    cik: int
    filed: date


_IDX_LINE = re.compile(
    r"^(?P<form>\S.*?)\s{2,}(?P<company>.+?)\s{2,}(?P<cik>\d+)\s+(?P<date>\d{4}-\d{2}-\d{2})\s"
)


def parse_form_index(lines: Iterable[str], forms: set[str]) -> list[IndexEntry]:
    """Parse EDGAR full-index `form.idx` lines for the given form types."""
    out: list[IndexEntry] = []
    for line in lines:
        m = _IDX_LINE.match(line)
        if m and m["form"].strip() in forms:
            out.append(
                IndexEntry(
                    m["form"].strip(), m["company"].strip(), int(m["cik"]),
                    date.fromisoformat(m["date"]),
                )
            )  # fmt: skip
    return out


def quarterly_filing_count(facts: dict[str, Any]) -> int:
    """Distinct 10-K/10-Q accession numbers in companyfacts (a proxy for XBRL history)."""
    accns: set[str] = set()
    for tags in facts.get("facts", {}).values():
        for body in tags.values():
            for rows in body.get("units", {}).values():
                for r in rows:
                    if r.get("form") in ANNUAL_QUARTERLY_FORMS:
                        accns.add(r["accn"])
    return len(accns)


def recent_quarters(today: date, n: int) -> list[tuple[int, int]]:
    """The last n *complete* calendar quarters, newest first."""
    year, q = today.year, (today.month - 1) // 3 + 1
    out: list[tuple[int, int]] = []
    for _ in range(n):
        q -= 1
        if q == 0:
            year, q = year - 1, 4
        out.append((year, q))
    return out


# --- Fetching -----------------------------------------------------------------------------------


@dataclass
class Fixture:
    ticker: str
    role: str
    cik: int
    name: str
    facts: dict[str, Any]
    submissions: dict[str, Any]


async def _fetch_company(sec: SecGateway, cik: int) -> tuple[dict[str, Any], dict[str, Any]]:
    facts, subs = await asyncio.gather(
        sec.get_json(FACTS_URL.format(cik=cik)), sec.get_json(SUBMISSIONS_URL.format(cik=cik))
    )
    return facts, subs


async def _form_index(sec: SecGateway, year: int, q: int, work: Path) -> list[str]:
    dest = work / f"form-{year}-Q{q}.idx"
    await sec.download(FORM_INDEX_URL.format(year=year, q=q), dest)
    return dest.read_text(encoding="latin-1").splitlines()


async def _pick_spac(
    sec: SecGateway, rows: list[TickerRow], taken: set[int]
) -> tuple[Fixture, str] | None:
    candidates = sorted(
        (
            r
            for r in primary_rows(rows).values()
            if r.exchange in LISTED_EXCHANGES
            and "acquisition" in r.name.lower()
            and r.cik not in taken
        ),
        key=lambda r: r.ticker,
    )
    for r in candidates[:25]:
        sub = await sec.get_json(SUBMISSIONS_URL.format(cik=r.cik))
        if str(sub.get("sic")) != "6770":
            continue
        try:
            facts = await sec.get_json(FACTS_URL.format(cik=r.cik))
        except SourceError:
            continue  # no XBRL facts yet
        why = f"first listed 'Acquisition' name (by ticker) with SIC 6770: {r.ticker}"
        return Fixture(r.ticker, "SPAC (SIC 6770)", r.cik, r.name, facts, sub), why
    return None


async def _pick_from_index(
    sec: SecGateway,
    rows: list[TickerRow],
    taken: set[int],
    work: Path,
    *,
    form: str,
    accept: Callable[[dict[str, Any], dict[str, Any]], bool],
    role: str,
    today: date,
    quarters: int,
    max_checks: int = 40,
) -> tuple[Fixture, str] | None:
    listed = {c: r for c, r in primary_rows(rows).items() if r.exchange in LISTED_EXCHANGES}
    checks = 0
    for year, q in recent_quarters(today, quarters):
        entries = parse_form_index(await _form_index(sec, year, q, work), {form})
        entries.sort(key=lambda e: (-e.filed.toordinal(), e.cik))
        seen: set[int] = set()
        for e in entries:
            if e.cik in seen or e.cik in taken or e.cik not in listed:
                continue
            seen.add(e.cik)
            checks += 1
            if checks > max_checks:
                return None
            try:
                facts, sub = await _fetch_company(sec, e.cik)
            except SourceError:
                continue
            if str(sub.get("sic")) in {"6770", "6722", "6726"} or not accept(facts, sub):
                continue
            r = listed[e.cik]
            why = (
                f"latest qualifying {form} filer in {year} Q{q} listed on {r.exchange}: "
                f"{r.ticker} (filed {e.filed})"
            )
            return Fixture(r.ticker, role, r.cik, r.name, facts, sub), why
    return None


def _is_recent_ipo(facts: dict[str, Any], _sub: dict[str, Any]) -> bool:
    return 2 <= quarterly_filing_count(facts) < 8


def _has_annual_facts(facts: dict[str, Any], _sub: dict[str, Any]) -> bool:
    return quarterly_filing_count(facts) >= 4


async def build_fixtures(
    sec: SecGateway, work: Path, *, today: date | None = None
) -> tuple[list[Fixture], dict[str, Any], list[str]]:
    today = today or datetime.now(UTC).date()
    tickers_doc = await sec.get_json(TICKERS_URL)
    rows = parse_tickers_exchange(tickers_doc)
    by_symbol = {r.ticker: r for r in rows}

    fixtures: list[Fixture] = []
    for ticker, role in FIXED_TICKERS:
        row = by_symbol.get(sec_symbol(ticker))
        if row is None:
            raise SourceError("sec", f"{ticker} not in company_tickers_exchange.json")
        facts, sub = await _fetch_company(sec, row.cik)
        fixtures.append(Fixture(ticker, role, row.cik, row.name, facts, sub))
        log_event(log, "fixture_fetched", ticker=ticker, cik=row.cik)

    taken = {f.cik for f in fixtures}
    picks: list[str] = []
    for label, pick in [
        ("SPAC", _pick_spac(sec, rows, taken)),
        (
            "recent IPO",
            _pick_from_index(
                sec, rows, taken, work, form="424B4", accept=_is_recent_ipo,
                role="Recent IPO (< 8 quarters of XBRL history)", today=today, quarters=2,
            ),
        ),
        (
            "FY change",
            _pick_from_index(
                sec, rows, taken, work, form="10-KT", accept=_has_annual_facts,
                role="Fiscal-year change (filed a 10-KT transition report)", today=today,
                quarters=8,
            ),
        ),
    ]:  # fmt: skip
        result = await pick
        if result is None:
            picks.append(f"{label}: none found")
            continue
        fixture, why = result
        fixtures.append(fixture)
        taken.add(fixture.cik)
        picks.append(f"{label}: {why}")
        log_event(log, "fixture_picked", role=label, ticker=fixture.ticker)
    return fixtures, trim_tickers_exchange(tickers_doc, taken), picks


def write_fixtures(
    fixtures: list[Fixture],
    tickers_doc: dict[str, Any],
    picks: list[str],
    out: Path,
    concepts_path: Path = CONCEPTS_PATH,
) -> int:
    """Trim and write everything; returns total bytes. Raises if over the 25 MB budget."""
    keep = kept_tags(yaml.safe_load(concepts_path.read_text()))
    final, out = out, out.with_name(out.name + ".tmp")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "picks": picks,
        "fixtures": [],
    }
    for f in fixtures:
        name = fixture_name(f.ticker)
        (out / f"{name}.companyfacts.json").write_bytes(
            orjson.dumps(trim_companyfacts(f.facts, keep), option=orjson.OPT_SORT_KEYS)
        )
        (out / f"{name}.submissions.json").write_bytes(
            orjson.dumps(trim_submissions(f.submissions), option=orjson.OPT_SORT_KEYS)
        )
        manifest["fixtures"].append(
            {"ticker": f.ticker, "cik": f"{f.cik:010d}", "name": f.name, "role": f.role}
        )
    (out / "company_tickers_exchange.json").write_bytes(orjson.dumps(tickers_doc))
    (out / "manifest.json").write_bytes(
        orjson.dumps(manifest, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n"
    )
    total = sum(p.stat().st_size for p in out.glob("*.json"))
    if total > MAX_TOTAL_BYTES:
        shutil.rmtree(out)
        raise SourceError("fixtures", f"fixtures total {total:,} bytes > 25 MB budget")
    shutil.rmtree(final, ignore_errors=True)
    out.replace(final)
    return total
