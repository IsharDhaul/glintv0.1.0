"""Universe build from a facts_raw dataset, predecessor merge, and the `glint financials` CLI.

Uses a temp facts_raw (bucketed like WT-01's) and companies.parquet built from the committed
fixtures; never the real data dirs.
"""

from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import pytest
from typer.testing import CliRunner

from glint.cli import app
from glint.contracts.enums import Basis, LineItem, NoteCode, Taxonomy
from glint.financials import cli as financials_cli
from glint.financials.build import (
    _facts_of,  # pyright: ignore[reportPrivateUsage]
    build_financials,
    company_meta,
    read_facts,
)
from glint.financials.coverage import Group
from glint.financials.facts import Fact
from glint.financials.normalize import normalize_company
from glint.financials.predecessors import merge_predecessor
from glint.ingest.sec.extract import BUCKETS, SCHEMA
from glint.universe.predecessors import PredecessorLink
from tests.financials.conftest import concepts, fixture_facts

D = date.fromisoformat
FOLDER = "2026-10-29"

# ticker → (cik, sector, exchange, kind, foreign)
COMPANIES = {
    "AAPL": ("0000320193", "Technology", "Nasdaq", "operating", False),
    "JPM": ("0000019617", "Banks", "NYSE", "operating", False),
    "TSM": ("0001046179", "Technology", "NYSE", "operating", True),
    "XOM": ("0002115436", "Energy", "NYSE", "operating", False),
}
OLD_XOM = "0000034088"
LINK = PredecessorLink(
    successor_cik="0002115436",
    predecessor_cik=OLD_XOM,
    name="test",
    reason="test",
    evidence="test",
    added=D("2026-10-29"),
)


def _fact(**kw: object) -> Fact:
    base = Fact(Taxonomy.US_GAAP, "Revenues", "USD", D("2025-01-01"), D("2025-12-31"), 1.0,
                "a", None, None, "10-K", D("2026-02-01"))  # fmt: skip
    return base._replace(**kw)  # pyright: ignore[reportArgumentType]


def _frame(cik: str, facts: tuple[Fact, ...] | list[Fact]) -> pl.DataFrame:
    rows = [
        (cik, f.taxonomy.value, f.tag, f.unit, f.start, f.end, f.val, f.accn, f.fy, f.fp,
         f.form, f.filed, None)
        for f in facts
    ]  # fmt: skip
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


def _old_exxon() -> list[Fact]:
    """A stand-in for CIK 34088's history: FY2024 revenue, plus an FY2025 value the successor
    also reports (the successor must win)."""
    return [
        _fact(start=D("2024-01-01"), end=D("2024-12-31"), val=349_585e6, accn="old-2024"),
        _fact(start=D("2025-01-01"), end=D("2025-12-31"), val=1.0, accn="old-2025"),
        _fact(tag="SalesRevenueNet", start=D("2025-01-01"), end=D("2025-12-31"), val=2.0),
    ]


def _write_dataset(root: Path) -> Path:
    folder = root / "sec" / FOLDER
    facts_dir = folder / "facts_raw"
    frames = [_frame(cik, fixture_facts(t)) for t, (cik, *_) in COMPANIES.items()]
    frames.append(_frame(OLD_XOM, _old_exxon()))
    all_facts = pl.concat(frames)
    for (bucket,), part in all_facts.group_by(pl.col("cik").cast(pl.Int64) % BUCKETS):
        out = facts_dir / f"bucket={bucket:02d}" / "part-0.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        part.write_parquet(out)
    companies = pl.DataFrame(
        [
            {
                "cik": cik,
                "name": t,
                "tickers": [t],
                "primary_ticker": t,
                "sector": sector,
                "exchange": exch,
                "kind": kind,
                "is_foreign_filer": foreign,
                "has_facts": True,
            }
            for t, (cik, sector, exch, kind, foreign) in COMPANIES.items()
        ]
    )
    companies.write_parquet(folder / "companies.parquet")
    return facts_dir


def test_merge_predecessor_successor_wins_by_period() -> None:
    cm = concepts()
    own = [_fact(tag="RevenueFromContractWithCustomerExcludingAssessedTax", val=332_238e6)]
    merged = merge_predecessor(own, _old_exxon(), cm)
    # FY2025 is the successor's (both predecessor tags for that period dropped); FY2024 inherited.
    assert sorted((f.end, f.val) for f in merged) == [
        (D("2024-12-31"), 349_585e6),
        (D("2025-12-31"), 332_238e6),
    ]
    assert merge_predecessor(own, [_fact(tag="NotMapped")], cm) == own


def test_company_meta_groups() -> None:
    companies = pl.DataFrame(
        {
            "cik": ["1", "2", "3", "4", "5"],
            "primary_ticker": ["A", "B", "C", "D", "E"],
            "sector": ["Technology", "Banks", "Banks", "Energy", "Unknown"],
            "exchange": ["NYSE", "NYSE", "NYSE", "OTC", "Nasdaq"],
            "kind": ["operating", "operating", "operating", "operating", "spac"],
            "is_foreign_filer": [False, False, True, False, False],
            "has_facts": [True, True, True, True, True],
        }
    )
    meta = company_meta(companies)
    assert [meta[c].group for c in "123"] == [Group.DOMESTIC, Group.FINANCIAL, Group.FOREIGN]
    assert not meta["4"].in_default_universe and not meta["5"].in_default_universe
    assert meta["5"].sector is None


def test_universe_build_writes_rows_and_coverage(tmp_path: Path) -> None:
    facts_dir = _write_dataset(tmp_path)
    companies = pl.read_parquet(tmp_path / "sec" / FOLDER / "companies.parquet")
    with duckdb.connect(str(tmp_path / "b.duckdb")) as con:
        rep = build_financials(
            facts_dir, companies, {LINK.successor_cik: LINK}, concepts(), con=con, batch_rows=500
        )
        n = con.execute("SELECT count(*) FROM financials").fetchone()
        assert n is not None and n[0] == rep.rows > 0
        ciks = {r[0] for r in con.execute("SELECT DISTINCT cik FROM financials").fetchall()}
        assert OLD_XOM not in ciks  # history lands under the successor's CIK
        xom = con.execute(
            "SELECT value, source_accn FROM financials WHERE cik='0002115436' "
            "AND line_item='revenue' AND basis='fy' AND period_end='2024-12-31'"
        ).fetchall()
        assert xom == [(349_585e6, "old-2024")]
    assert rep.companies == 4
    assert rep.coverage_ttm.companies == {Group.DOMESTIC: 2, Group.FINANCIAL: 1, Group.FOREIGN: 1}
    assert rep.coverage_ttm.share(LineItem.REVENUE, Group.DOMESTIC) == 1.0
    assert rep.gap_codes[NoteCode.NOT_APPLICABLE_SECTOR] >= 1  # JPM
    assert "0000019617" in rep.gaps


def test_read_facts_for_a_few_ciks(tmp_path: Path) -> None:
    facts_dir = _write_dataset(tmp_path)
    got = read_facts(facts_dir, ["0000320193"])
    assert set(got) == {"0000320193"} and len(got["0000320193"]) == len(fixture_facts("AAPL"))
    assert read_facts(tmp_path / "nowhere", ["0000320193"]) == {}
    cf = normalize_company("0000320193", got["0000320193"], concepts())
    assert cf.latest(LineItem.REVENUE, Basis.FY) is not None


def test_facts_of_keeps_each_companys_row_order_and_values() -> None:
    """Interleaved CIKs: each company's facts in frame order, values exact (-0.0 stays -0.0,
    a null form reads as ""), and equal strings share one object."""
    a, b = "0000000001", "0000000002"
    rows = [
        _fact(val=3.0, accn="x"), _fact(val=-0.0, accn="y"), _fact(val=0.0, accn="z"),
        _fact(val=1.0, accn="x", start=None), _fact(val=2.0, accn="w", fy=2025, fp="FY"),
    ]  # fmt: skip
    frame = pl.concat(
        [_frame(c, [f]) for c, f in zip((b, a, b, a, b), rows, strict=True)]
    ).with_columns(form=pl.when(pl.col("accn") == "w").then(None).otherwise(pl.col("form")))
    got = _facts_of(frame)
    assert list(got) == [a, b]
    assert got[a] == [rows[1], rows[3]]
    assert got[b] == [rows[0], rows[2], rows[4]._replace(form="")]
    assert str(got[a][0].val) == "-0.0" and str(got[b][1].val) == "0.0"
    assert got[a][0].tag is got[b][0].tag and got[a][1].start is None
    assert _facts_of(frame.clear()) == {}


runner = CliRunner()


@pytest.fixture
def raw(db_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(financials_cli.console, "width", 400)  # no wrapping of long tag names
    raw_dir = db_dir.parent / "raw"
    _write_dataset(raw_dir)
    return raw_dir


def test_cli_company_table(raw: Path) -> None:
    res = runner.invoke(
        app, ["financials", "AAPL", "--basis", "ttm", "--periods", "4", "--sources"]
    )
    assert res.exit_code == 0, res.output
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in res.output
    assert "Σ quarters" in res.output
    res = runner.invoke(app, ["financials", "JPM", "--basis", "fy"])
    assert res.exit_code == 0 and "NOT_APPLICABLE_SECTOR" in res.output
    res = runner.invoke(app, ["financials", "TSM", "--basis", "mrq"])
    assert res.exit_code == 0 and "ifrs-full" in res.output and "TWD" in res.output


def test_cli_coverage_and_write(raw: Path, tmp_path: Path) -> None:
    out = tmp_path / "fin.duckdb"
    res = runner.invoke(app, ["financials", "--coverage", "--write", str(out)])
    assert res.exit_code == 0, res.output
    assert "core mean" in res.output and "domestic non-financial" in res.output
    with duckdb.connect(str(out)) as con:
        n = con.execute("SELECT count(*) FROM financials").fetchone()
        assert n is not None and n[0] > 0
    assert runner.invoke(app, ["financials", "--coverage"]).exit_code == 0


def test_cli_errors(raw: Path) -> None:
    assert runner.invoke(app, ["financials"]).exit_code == 2
    assert runner.invoke(app, ["financials", "NOPE"]).exit_code == 1


def test_cli_without_data(db_dir: Path) -> None:
    res = runner.invoke(app, ["financials", "AAPL"])
    assert res.exit_code == 1 and "error" in res.output
