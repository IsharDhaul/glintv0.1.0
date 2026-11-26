"""`glint financials` (WT-03): one company's normalized series, or universe coverage."""

from collections import Counter
from datetime import date
from enum import StrEnum
from pathlib import Path

import duckdb
import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from glint.contracts.enums import Basis, LineItem, PeriodKind, Sector
from glint.core.paths import Paths
from glint.financials.build import (
    BuildReport,
    build_financials,
    company_facts,
    economic_counts,
    lease_declarations,
    read_facts,
)
from glint.financials.concepts import ConceptMap, UnitKind, load_concepts
from glint.financials.coverage import Group, gaps
from glint.financials.normalize import CompanyFinancials, normalize_company
from glint.financials.select import Value
from glint.financials.shares import apply_economic_count
from glint.universe.cli import load_companies
from glint.universe.predecessors import load_predecessors
from glint.universe.tickers import canonical_symbol

app = typer.Typer(
    help="Normalized FY / Q / TTM / MRQ series for a ticker, or --coverage.",
    context_settings={"allow_interspersed_args": True},  # `glint financials AAPL --basis ttm`
)
console = Console()


class BasisChoice(StrEnum):
    FY = "fy"
    Q = "q"
    TTM = "ttm"
    MRQ = "mrq"


def _fmt(v: Value, concepts: ConceptMap) -> str:
    match concepts[v.item].unit:
        case UnitKind.PER_SHARE:
            return f"{v.value:,.2f}"
        case UnitKind.CURRENCY | UnitKind.SHARES:
            return f"{v.value / 1e6:,.0f}"


def _source(v: Value) -> str:
    if v.source_tag is not None:
        return f"{v.source_tag} · {v.source_accn}"
    if v.derived or v.quarter_derived:
        return "derived: " + "; ".join(v.inputs)
    if v.inputs and v.inputs[0].startswith("FY "):
        return f"{' '.join(v.inputs)} · latest {v.source_accn}"
    return f"Σ quarters · latest {v.source_accn}"


def _instant_basis(basis: Basis) -> Basis:
    return Basis.FY if basis is Basis.FY else Basis.MRQ


def company_table(
    cf: CompanyFinancials,
    concepts: ConceptMap,
    basis: Basis,
    periods: int,
    *,
    sources: bool,
    title: str,
) -> Table:
    """Line items as rows, period ends as columns (oldest → newest)."""

    def series(item: LineItem) -> dict[date, Value]:
        if concepts[item].kind is PeriodKind.INSTANT:
            return cf.series(item, _instant_basis(basis))
        return {} if basis is Basis.MRQ else cf.series(item, basis)

    driving = [i for i in LineItem if concepts[i].kind is PeriodKind.DURATION]
    if basis is Basis.MRQ:
        driving = [i for i in LineItem if i is not LineItem.SHARES_OUTSTANDING]
    ends = sorted({e for i in driving for e in series(i)})[-periods:]
    table = Table(title=title, show_lines=sources)
    table.add_column("line item (M; per-share as is)")
    for e in ends:
        table.add_column(str(e), justify="right")
    for item in LineItem:
        s = series(item)
        if not any(e in s for e in ends) and not (item is LineItem.SHARES_OUTSTANDING and s):
            continue
        cells: list[str] = []
        for e in ends:
            v = s.get(e)
            if v is None:
                cells.append("—")
                continue
            flag = "ᵈ" if v.derived or (basis is Basis.Q and v.quarter_derived) else ""
            cells.append(
                _fmt(v, concepts) + flag + (f"\n[dim]{_source(v)}[/dim]" if sources else "")
            )
        table.add_row(item.value, *cells)
    return table


def _companies_and_facts_dir(facts_dir: Path | None) -> tuple[pl.DataFrame, Path]:
    companies, folder = load_companies(Paths.from_settings().sec_raw)
    return companies, facts_dir or folder / "facts_raw"


def show_company(
    ticker: str, basis: Basis, periods: int, sources: bool, facts_dir: Path | None
) -> None:
    concepts = load_concepts()
    companies, fdir = _companies_and_facts_dir(facts_dir)
    hit = companies.filter(pl.col("tickers").list.contains(canonical_symbol(ticker)))
    if hit.is_empty():
        console.print(f"[yellow]{canonical_symbol(ticker)} is not in the universe file.[/yellow]")
        raise typer.Exit(1)
    row = hit.row(0, named=True)
    cik: str = row["cik"]
    links = load_predecessors()
    pred = links[cik].predecessor_cik if cik in links else None
    facts = read_facts(fdir, [cik, *([pred] if pred else [])])
    merged = company_facts(facts.get(cik, []), cik, links, facts, concepts)
    cf = normalize_company(cik, merged, concepts, lease_declarations(hit).get(cik))
    apply_economic_count(cf, economic_counts(hit).get(cik), concepts.params.shares_stale_days)
    title = (
        f"{row['name']} ({row['primary_ticker']}, CIK {cik}) · {basis.value.upper()} · "
        f"{cf.taxonomy.value} · {cf.currency or 'no currency'}"
    )
    console.print(company_table(cf, concepts, basis, periods, sources=sources, title=title))
    notes = ["ᵈ derived (§4.3 rules 5/9)"]
    if pred:
        notes.append(f"history before the successor's own filings is from predecessor CIK {pred}")
    if cf.shares_as_of:
        notes.append(f"shares as of {cf.shares_as_of}")
    for ch in cf.fy_changes:
        notes.append(f"fiscal-year change: transition {ch.transition.label()}")
    console.print("[dim]" + " · ".join(notes) + "[/dim]")
    sectors = {s.value: s for s in Sector}
    gap_basis = Basis.TTM if basis is Basis.MRQ else basis
    g = gaps(cf, concepts, concepts.core, gap_basis, sectors.get(row["sector"]))
    for gap in g.values():
        console.print(f"[yellow]{gap.code}[/yellow] {gap.message}")
    for w in cf.warnings:
        console.print(f"[dim]warning: {w}[/dim]")


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.1%}"


def show_coverage(report: BuildReport, concepts: ConceptMap) -> None:
    groups = list(Group)
    for rep, label in (
        (report.coverage_ttm, "latest TTM / MRQ"),
        (report.coverage_fy, "latest FY"),
    ):
        table = Table(title=f"Coverage, default universe — {label}")
        table.add_column("line item")
        for g in groups:
            table.add_column(f"{g.value} (n={rep.companies[g]:,})", justify="right")
        table.add_column("top tags (count)")
        core = set(concepts.core)
        for item in LineItem:
            top = ", ".join(
                f"{t} {n:,}" for t, n in rep.tags.get(item, Counter[str]()).most_common(3)
            )
            name = f"[bold]{item.value}[/bold]" if item in core else item.value
            table.add_row(name, *(_pct(rep.share(item, g)) for g in groups), top)
        table.add_row(
            "[bold]core mean (20 items)[/bold]",
            *(f"[bold]{_pct(rep.core_share(concepts.core, g))}[/bold]" for g in groups),
            "",
        )
        console.print(table)
    console.print(
        f"{report.companies:,} companies normalized, {report.rows:,} rows written, "
        f"{report.warnings:,} warnings, {report.seconds:,.0f}s"
    )
    console.print(
        "core gaps by reason (default universe, TTM/MRQ): "
        + ", ".join(f"{c} {n:,}" for c, n in report.gap_codes.most_common())
    )


def run_coverage(facts_dir: Path | None, write: Path | None) -> None:
    concepts = load_concepts()
    companies, fdir = _companies_and_facts_dir(facts_dir)
    links = load_predecessors()
    if write is not None:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.unlink(missing_ok=True)
        with duckdb.connect(str(write)) as con:
            report = build_financials(fdir, companies, links, concepts, con=con)
        console.print(f"financials table written to {write}")
    else:
        report = build_financials(fdir, companies, links, concepts)
    show_coverage(report, concepts)


@app.callback(invoke_without_command=True)
def financials(
    ticker: str | None = typer.Argument(None, help="e.g. AAPL or BRK.B"),
    *,
    basis: BasisChoice = typer.Option(BasisChoice.FY, "--basis", help="fy | q | ttm | mrq"),
    periods: int = typer.Option(8, "--periods", min=1, help="How many period columns."),
    sources: bool = typer.Option(False, "--sources", help="Show tag and accession per cell."),
    show_cov: bool = typer.Option(False, "--coverage", help="Coverage over the universe."),
    write: Path | None = typer.Option(
        None, "--write", help="With --coverage: also write the financials table to this DuckDB."
    ),
    facts_dir: Path | None = typer.Option(
        None, "--facts-dir", help="facts_raw dataset (default: the latest SEC folder's)."
    ),
) -> None:
    """Normalized series for a ticker, or --coverage for the whole universe."""
    try:
        if show_cov:
            run_coverage(facts_dir, write)
        elif ticker is not None:
            show_company(ticker, Basis(basis.value), periods, sources, facts_dir)
        else:
            console.print("Pass a ticker or --coverage.")
            raise typer.Exit(2)
    except FileNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
