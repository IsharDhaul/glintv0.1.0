"""`glint universe` (WT-01): universe counts (`--summary`) or one company's record."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from glint.api.build import build_db_path, connect_read_only, read_pointer
from glint.contracts.enums import DEFAULT_EXCHANGES, Kind
from glint.core.errors import ContractError
from glint.core.paths import Paths
from glint.ingest.sec.covers import load_cover
from glint.ingest.sec.download import latest_folder
from glint.universe.build import COMPANIES_FILE
from glint.universe.classify import load_rules
from glint.universe.tickers import canonical_symbol
from glint.universe.upc import common_classes, review_candidate

app = typer.Typer(help="Universe counts (--summary) or one company's record.")
console = Console()


def load_companies(sec_raw: Path) -> tuple[pl.DataFrame, Path]:
    folder = latest_folder(sec_raw, marker=COMPANIES_FILE)
    if folder is None:
        raise FileNotFoundError(f"no {COMPANIES_FILE} under {sec_raw}; run `glint ingest sec`")
    return pl.read_parquet(folder / COMPANIES_FILE), folder


DEFAULT_EXCHANGES_LABEL = "/".join(e.value for e in DEFAULT_EXCHANGES)


def default_universe(df: pl.DataFrame) -> pl.DataFrame:
    """Default universe (SPEC §2.3): listed on a default exchange, operating, has facts."""
    return df.filter(
        pl.col("exchange").is_in([e.value for e in DEFAULT_EXCHANGES])
        & (pl.col("kind") == Kind.OPERATING.value)
        & pl.col("has_facts")
    )


def _counts(df: pl.DataFrame, col: str, title: str) -> Table:
    table = Table(title=title)
    table.add_column(col)
    table.add_column("CIKs", justify="right")
    table.add_column("default universe", justify="right")
    uni = default_universe(df)
    in_uni = dict(uni.group_by(col).len().iter_rows())
    for key, n in df.group_by(col).len().sort("len", descending=True).iter_rows():
        table.add_row(str(key) if key is not None else "—", f"{n:,}", f"{in_uni.get(key, 0):,}")
    return table


def summary(df: pl.DataFrame, folder: Path) -> None:
    uni = default_universe(df)
    console.print(f"Universe from {folder} — {df.height:,} CIKs with tickers")
    console.print(
        f"Default universe ({DEFAULT_EXCHANGES_LABEL}, operating, has facts): {uni.height:,}"
    )
    console.print(f"CIKs with no XBRL financial facts: {df.filter(~pl.col('has_facts')).height:,}")
    df = df.with_columns(
        pl.when(pl.col("is_foreign_filer")).then(pl.lit("foreign")).otherwise(pl.lit("domestic"))
        .alias("filer"),
        pl.coalesce(pl.col("exchange"), pl.lit("unknown: ") + pl.col("sec_exchange").fill_null("—"))
        .alias("exchange_label"),
    )  # fmt: skip
    for col, title in [
        ("exchange_label", "By exchange"),
        ("kind", "By kind"),
        ("sector", "By sector (SIC-based)"),
        ("filer", "Foreign / domestic"),
    ]:
        console.print(_counts(df, col, title))


_LATEST_SHARES = """
SELECT cik, value FROM financials WHERE line_item = 'shares_outstanding'
QUALIFY row_number() OVER (PARTITION BY cik ORDER BY period_end DESC, filed DESC NULLS LAST) = 1
"""


def glint_share_counts(paths: Paths) -> dict[str, float] | None:
    """CIK → Glint's latest `shares_outstanding` (latest period_end, then latest filed) from the
    published build, opened read-only. None when there is no usable build."""
    try:
        pointer = read_pointer(paths)
    except ContractError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return None
    if pointer is None:
        return None
    with connect_read_only(build_db_path(pointer, paths)) as con:
        rows: list[tuple[str, float]] = con.execute(_LATEST_SHARES).fetchall()
    return dict(rows)


@dataclass(frozen=True)
class Candidate:
    ticker: str
    note: str  # what the cover shows (upc.review_candidate)
    cover_total: float
    glint_shares: float | None


def up_c_candidates(
    df: pl.DataFrame, sec_raw: Path, glint_shares: dict[str, float] | None
) -> list[Candidate]:
    """Default-universe domestic filers whose latest 10-K/10-Q cover is multi-class and that the
    Up-C logic leaves alone (upc.review_candidate), filtered on Glint's share counts
    (`glint_shares`; None = no build, unfiltered)."""
    rule = load_rules().up_c
    out: list[Candidate] = []
    uni = default_universe(df).filter(~pl.col("is_foreign_filer") & ~pl.col("is_up_c"))
    for row in uni.sort("primary_ticker").iter_rows(named=True):
        filings = [
            (d, a) for d, a in [
                (row["last_annual_date"], row["last_annual_accn"]),
                (row["last_quarterly_date"], row["last_quarterly_accn"]),
            ] if d is not None and a is not None
        ]  # fmt: skip
        if not filings:
            continue
        cover = load_cover(sec_raw, row["cik"], max(filings)[1])
        if cover is None:
            continue
        glint = (glint_shares or {}).get(row["cik"])
        note = review_candidate(cover, rule, glint)
        if note is not None:
            total = sum(common_classes(cover).values())
            out.append(Candidate(row["primary_ticker"], note, total, glint))
    return out


def _glint_counts_or_say_so(paths: Paths) -> dict[str, float] | None:
    counts = glint_share_counts(paths)
    if counts is None:
        console.print(
            "No published build (data/current.json): candidates are not filtered on Glint's "
            "share counts."
        )
    return counts


def show_candidates_table(found: list[Candidate], filtered: bool) -> None:
    ratio = load_rules().up_c.candidate_min_ratio
    scope = f"cover total ≥ {ratio:g}× Glint's shares or no count" if filtered else "unfiltered"
    title = f"Up-C review candidates: {len(found)} (default universe, domestic; {scope})"
    table = Table(title=title)
    table.add_column("ticker")
    table.add_column("latest cover")
    table.add_column("Glint shares", justify="right")
    table.add_column("cover / Glint", justify="right")
    for c in found:
        if c.glint_shares is None:
            glint, ratio_s = "—", "—"
        else:
            glint = f"{c.glint_shares:,.0f}"
            ratio_s = f"{c.cover_total / c.glint_shares:.2f}x" if c.glint_shares > 0 else "n/m"
        table.add_row(c.ticker, c.note, glint, ratio_s)
    console.print(table)


def show_company(row: dict[str, Any]) -> None:
    table = Table(title=f"{row['name']} ({row['primary_ticker']})", show_header=False)
    table.add_column("field", style="bold")
    table.add_column("value")
    for key, value in row.items():
        if isinstance(value, list):
            items: list[Any] = value  # pyright: ignore[reportUnknownVariableType]
            shown = ", ".join(str(v) for v in items) or "—"
        else:
            shown = "—" if value is None else str(value)
        table.add_row(key, shown)
    console.print(table)


@app.callback(invoke_without_command=True)
def universe(
    ticker: str | None = typer.Argument(None, help="Show one company, e.g. AAPL or BRK.B."),
    show_summary: bool = typer.Option(False, "--summary", help="Counts by exchange, sector, kind."),
    show_candidates: bool = typer.Option(
        False,
        "--up-c-candidates",
        help="Multi-class covers the Up-C logic leaves alone (review for up_c.confirmed/excluded).",
    ),
) -> None:
    """Universe counts (--summary) or one company's record."""
    paths = Paths.from_settings()
    try:
        df, folder = load_companies(paths.sec_raw)
    except FileNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    if ticker is None:
        if show_candidates:
            counts = _glint_counts_or_say_so(paths)
            show_candidates_table(up_c_candidates(df, folder.parent, counts), counts is not None)
            return
        if not show_summary:
            console.print("Pass a ticker, --summary or --up-c-candidates.")
            raise typer.Exit(2)
        summary(df, folder)
        n_up_c = default_universe(df).filter(pl.col("is_up_c")).height
        counts = _glint_counts_or_say_so(paths)
        console.print(
            f"Up-Cs in the default universe: {n_up_c:,}; review candidates: "
            f"{len(up_c_candidates(df, folder.parent, counts)):,} "
            "(glint universe --up-c-candidates)"
        )
        return
    wanted = canonical_symbol(ticker)
    hit = df.filter(pl.col("tickers").list.contains(wanted))
    if hit.is_empty():
        console.print(f"[yellow]{wanted} is not in the universe file (unknown ticker).[/yellow]")
        raise typer.Exit(1)
    show_company(hit.row(0, named=True))
