"""Normalize the whole universe from `facts_raw` into the `financials` table (WT-03 step 9).

Reads the bucketed facts_raw dataset (WT-01) one bucket at a time, merges predecessor CIKs'
history (config/cik_predecessors.yaml), normalizes each company and appends its rows. Coverage is
collected for the default universe (listed on a default exchange, operating, has facts).
"""

import gc
import time
from collections import Counter, defaultdict
from collections.abc import Generator, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from glint.contracts.enums import (
    DEFAULT_EXCHANGES,
    FINANCIAL_SECTORS,
    Basis,
    Kind,
    NoteCode,
    Sector,
    Taxonomy,
)
from glint.core.log import get_logger, log_event
from glint.financials.concepts import ConceptMap
from glint.financials.coverage import CoverageReport, Gap, Group, add_company, gaps
from glint.financials.facts import Fact
from glint.financials.leases import LeaseDeclaration
from glint.financials.normalize import FinancialRow, keep_from, normalize_company
from glint.financials.predecessors import merge_predecessor
from glint.financials.shares import EconomicCount, apply_economic_count
from glint.financials.store import write_financials
from glint.ingest.sec.extract import bucket_of
from glint.universe.predecessors import PredecessorLink

log = get_logger(__name__)

_TAXONOMY = {t.value: t for t in Taxonomy}


@dataclass(frozen=True, slots=True)
class CompanyMeta:
    cik: str
    ticker: str | None
    sector: Sector | None
    is_foreign: bool
    in_default_universe: bool

    @property
    def group(self) -> Group:
        """Foreign first (a foreign bank is foreign), then financial, else domestic."""
        if self.is_foreign:
            return Group.FOREIGN
        if self.sector in FINANCIAL_SECTORS:
            return Group.FINANCIAL
        return Group.DOMESTIC


def company_meta(companies: pl.DataFrame) -> dict[str, CompanyMeta]:
    """CIK → metadata, for companies that have XBRL facts."""
    sectors = {s.value: s for s in Sector}
    default_exchanges = {e.value for e in DEFAULT_EXCHANGES}
    out: dict[str, CompanyMeta] = {}
    for r in companies.filter(pl.col("has_facts")).iter_rows(named=True):
        out[r["cik"]] = CompanyMeta(
            cik=r["cik"],
            ticker=r["primary_ticker"],
            sector=sectors.get(r["sector"]),
            is_foreign=bool(r["is_foreign_filer"]),
            in_default_universe=(
                r["exchange"] in default_exchanges and r["kind"] == Kind.OPERATING.value
            ),
        )
    return out


def lease_declarations(companies: pl.DataFrame) -> dict[str, LeaseDeclaration]:
    """CIK → where the filing presents its finance-lease liability (companies.parquet, WT-01's
    cover facts; only `finance_lease_status = 'stated'`). Folders built before the columns
    existed give none."""
    parts = {
        "current": "finance_lease_lines_current",
        "noncurrent": "finance_lease_lines_noncurrent",
        "total": "finance_lease_lines_total",
    }
    needed = {"finance_lease_status", "finance_lease_since", "finance_lease_accn", *parts.values()}
    if not needed <= set(companies.columns):
        return {}
    out: dict[str, LeaseDeclaration] = {}
    for r in companies.filter(pl.col("finance_lease_status") == "stated").iter_rows(named=True):
        lines = {p: tuple(r[c]) for p, c in parts.items() if r[c]}
        if lines and r["finance_lease_since"] is not None:
            out[r["cik"]] = LeaseDeclaration(
                lines, r["finance_lease_since"], r["finance_lease_accn"]
            )
    return out


def economic_counts(companies: pl.DataFrame) -> dict[str, EconomicCount]:
    """CIK → Up-C economic share count (companies.parquet, WT-01's cover-page facts). Folders
    built before the columns existed give none."""
    needed = {"is_up_c", "economic_shares", "economic_shares_as_of", "economic_shares_accn",
              "economic_shares_filed", "up_c_evidence"}  # fmt: skip
    if not needed <= set(companies.columns):
        return {}
    rows = companies.filter(pl.col("is_up_c") & pl.col("economic_shares").is_not_null())
    return {
        r["cik"]: EconomicCount(
            shares=r["economic_shares"],
            as_of=r["economic_shares_as_of"],
            accn=r["economic_shares_accn"],
            filed=r["economic_shares_filed"],
            evidence=r["up_c_evidence"],
        )
        for r in rows.iter_rows(named=True)
    }


def _bucket_files(facts_dir: Path) -> list[Path]:
    return sorted(facts_dir.glob("bucket=*/*.parquet"))


_FACT_COLUMNS = (
    "taxonomy",
    "tag",
    "unit",
    "start",
    "end",
    "val",
    "accn",
    "fy",
    "fp",
    "form",
    "filed",
)


def _shared(column: pl.Series) -> list[Any]:
    """The column's values, equal ones sharing one Python object. A bucket repeats a few
    thousand tags, units, accessions and dates across ~600k rows: sharing them cuts the facts'
    memory to about a third, and each string's hash is computed once. Values are looked up by
    dense rank among the sorted distinct values (null → None). Not for floats: 0.0 == -0.0."""
    distinct = [None, *column.drop_nulls().unique().sort().to_list()]
    return [distinct[i] for i in column.rank("dense").fill_null(0).to_list()]


def _facts_of(frame: pl.DataFrame) -> dict[str, list[Fact]]:
    """CIK → its facts, in frame order. Column-wise: a bucket is ~600k rows, and converting
    whole columns then building tuples is far cheaper than a dataclass per `iter_rows` row.
    A stable sort by CIK keeps each company's facts in frame order, so a company is a slice."""
    frame = frame.sort("cik", maintain_order=True)
    cols = [
        frame.get_column(c).to_list() if c == "val" else _shared(frame.get_column(c))
        for c in _FACT_COLUMNS
    ]
    cols[0] = [_TAXONOMY[t] for t in cols[0]]
    if frame.get_column("form").null_count():
        cols[9] = [form or "" for form in cols[9]]
    facts = list(map(Fact._make, zip(*cols, strict=True)))
    runs = frame.get_column("cik").rle()
    out: dict[str, list[Fact]] = {}
    at = 0
    lengths, ciks = runs.struct.field("len").to_list(), runs.struct.field("value").to_list()
    for n, cik in zip(lengths, ciks, strict=True):
        out[cik] = facts[at : at + n]
        at += n
    return out


@contextmanager
def _gc_paused() -> Generator[None]:
    """No cyclic GC while a bucket's facts are built: they're ~600k acyclic tuples, and the
    collector would rescan the growing heap many times over (about half of `_facts_of`)."""
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


def read_facts(facts_dir: Path, ciks: Iterable[str]) -> dict[str, list[Fact]]:
    """Facts for a few CIKs (scans only their buckets)."""
    wanted = set(ciks)
    buckets = {bucket_of(c) for c in wanted}
    files = [p for p in _bucket_files(facts_dir) if int(p.parent.name.split("=")[1]) in buckets]
    if not files:
        return {}
    frame = pl.scan_parquet(files).filter(pl.col("cik").is_in(list(wanted))).collect()
    with _gc_paused():
        return _facts_of(frame)


def iter_company_facts(facts_dir: Path, ciks: Iterable[str]) -> Iterator[tuple[str, list[Fact]]]:
    """(cik, facts) for every wanted CIK, one bucket in memory at a time, in CIK order.

    While a bucket is being normalized its facts are frozen out of the cyclic GC (`gc.freeze`):
    they hold no cycles and are freed by reference counting, so rescanning them on every full
    collection is pure overhead."""
    wanted = set(ciks)
    by_bucket: dict[str, list[Path]] = defaultdict(list)
    for p in _bucket_files(facts_dir):
        by_bucket[p.parent.name].append(p)
    for name in sorted(by_bucket):
        frame = pl.read_parquet(by_bucket[name]).filter(pl.col("cik").is_in(list(wanted)))
        with _gc_paused():
            grouped = _facts_of(frame)
        del frame
        gc.freeze()
        try:
            for cik in sorted(grouped):
                yield cik, grouped[cik]
        finally:
            del grouped
            gc.unfreeze()


def company_facts(
    facts: list[Fact],
    cik: str,
    links: Mapping[str, PredecessorLink],
    predecessor_facts: Mapping[str, list[Fact]],
    concepts: ConceptMap,
) -> list[Fact]:
    link = links.get(cik)
    if link is None:
        return facts
    return merge_predecessor(facts, predecessor_facts.get(link.predecessor_cik, []), concepts)


@dataclass
class BuildReport:
    companies: int = 0
    rows: int = 0
    seconds: float = 0.0
    warnings: int = 0
    coverage_ttm: CoverageReport = field(default_factory=lambda: CoverageReport(Basis.TTM))
    coverage_fy: CoverageReport = field(default_factory=lambda: CoverageReport(Basis.FY))
    gap_codes: Counter[NoteCode] = field(default_factory=Counter[NoteCode])
    gaps: dict[str, dict[str, Gap]] = field(default_factory=dict[str, dict[str, Gap]])


def build_financials(
    facts_dir: Path,
    companies: pl.DataFrame,
    links: Mapping[str, PredecessorLink],
    concepts: ConceptMap,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    batch_rows: int = 500_000,
) -> BuildReport:
    """Normalize every company with facts; write rows to `con` (if given) and report coverage."""
    started = time.monotonic()
    meta = company_meta(companies)
    economic = economic_counts(companies)
    leases = lease_declarations(companies)
    report = BuildReport()
    keep = keep_from(concepts)
    linked = {cik: link for cik, link in links.items() if cik in meta}
    predecessor_facts = read_facts(facts_dir, (lk.predecessor_cik for lk in linked.values()))
    pending: list[FinancialRow] = []
    seen: set[str] = set()

    def normalize(cik: str, facts: list[Fact]) -> None:
        nonlocal pending
        seen.add(cik)
        m = meta[cik]
        merged = company_facts(facts, cik, linked, predecessor_facts, concepts)
        cf = normalize_company(cik, merged, concepts, leases.get(cik))
        apply_economic_count(cf, economic.get(cik), concepts.params.shares_stale_days)
        report.companies += 1
        report.warnings += len(cf.warnings)
        pending += cf.rows(keep)
        if m.in_default_universe:
            add_company(report.coverage_ttm, m.group, cf, concepts)
            add_company(report.coverage_fy, m.group, cf, concepts)
            g = gaps(cf, concepts, concepts.core, Basis.TTM, m.sector)
            report.gap_codes.update(x.code for x in g.values())
            if g:
                report.gaps[cik] = {x.item.value: x for x in g.values()}
        if con is not None and len(pending) >= batch_rows:
            report.rows += write_financials(con, pending)
            pending = []

    for cik, facts in iter_company_facts(facts_dir, meta):
        normalize(cik, facts)
    # A successor whose own CIK has no facts yet still gets its predecessor's history.
    for cik in sorted(set(linked) - seen):
        normalize(cik, [])
    if con is not None and pending:
        report.rows += write_financials(con, pending)
    report.seconds = time.monotonic() - started
    log_event(
        log,
        "financials_built",
        companies=report.companies,
        rows=report.rows,
        warnings=report.warnings,
        seconds=round(report.seconds, 1),
    )
    return report
