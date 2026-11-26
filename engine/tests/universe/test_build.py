"""End to end on fixtures: ticker file + submissions.zip + facts_raw → companies.parquet."""

import dataclasses
import shutil
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import polars as pl
import pytest

from glint.contracts.db import COMPANIES
from glint.fixtures.sec import FIXTURE_DIR
from glint.ingest.sec.covers import (
    ClassCount,
    Cover,
    InstanceFact,
    LeaseLine,
    NciPercent,
    cover_path,
)
from glint.ingest.sec.extract import extract_facts, load_whitelist
from glint.universe.build import CONTRACT_COLUMNS, build_companies, write_companies
from glint.universe.classify import Rules, load_rules
from glint.universe.facts_profile import facts_profiles, revenue_tags
from glint.universe.upc import UpCConfirm, UpCExclude

TICKERS = ["AAPL", "TSM", "AAC", "XOM", "JPM"]


@pytest.fixture(scope="module")
def folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("2026-10-29")
    manifest = orjson.loads((FIXTURE_DIR / "manifest.json").read_bytes())
    ciks = {f["ticker"]: f["cik"] for f in manifest["fixtures"]}
    with (
        zipfile.ZipFile(d / "submissions.zip", "w") as subs,
        zipfile.ZipFile(d / "companyfacts.zip", "w") as facts,
    ):
        for t in TICKERS:
            subs.writestr(
                f"CIK{ciks[t]}.json", (FIXTURE_DIR / f"{t}.submissions.json").read_bytes()
            )
            facts.writestr(
                f"CIK{ciks[t]}.json", (FIXTURE_DIR / f"{t}.companyfacts.json").read_bytes()
            )
    tick = orjson.loads((FIXTURE_DIR / "company_tickers_exchange.json").read_bytes())
    keep = {int(ciks[t]) for t in TICKERS}
    tick["data"] = [r for r in tick["data"] if int(r[0]) in keep]
    tick["data"].append([1999999999, "Ticker Only Co", "TOC", "OTC"])  # no submissions, no facts
    (d / "company_tickers_exchange.json").write_bytes(orjson.dumps(tick))
    extract_facts(
        d / "companyfacts.zip", d / "facts_raw", source_sha256="x", whitelist=load_whitelist()
    )
    return d


def test_facts_profile_taxonomy_and_currency(folder: Path) -> None:
    p = facts_profiles(folder / "facts_raw", revenue_tags())
    aapl, tsm = p["0000320193"], p["0001046179"]
    assert (aapl.taxonomy, aapl.reporting_currency, aapl.basis) == ("us-gaap", "USD", "revenue")
    assert (tsm.taxonomy, tsm.reporting_currency, tsm.basis) == ("ifrs-full", "TWD", "revenue")


def test_facts_profile_falls_back_to_all_facts_without_revenue(folder: Path) -> None:
    p = facts_profiles(folder / "facts_raw", [("us-gaap", "NoSuchRevenueTag")])
    assert (p["0000320193"].taxonomy, p["0000320193"].basis) == ("us-gaap", "all facts")
    assert p["0000320193"].reporting_currency == "USD"


def test_companies_table(folder: Path) -> None:
    df = build_companies(folder, date(2026, 10, 29))
    assert tuple(df.columns[: len(CONTRACT_COLUMNS)]) == CONTRACT_COLUMNS
    rows = {r["primary_ticker"]: r for r in df.iter_rows(named=True)}
    aapl = rows["AAPL"]
    assert aapl["sector"] == "Technology" and aapl["kind"] == "operating"
    assert aapl["exchange"] == "Nasdaq" and aapl["has_facts"] and aapl["last_annual_form"] == "10-K"
    tsm = rows["TSM"]
    assert tsm["is_foreign_filer"] and tsm["tickers"] == ["TSM", "TSMWF"]
    assert rows["AAC"]["kind"] == "spac"
    assert rows["JPM"]["sector"] == "Banks"
    assert rows["XOM"]["predecessor_cik"] == "0000034088"
    toc = rows["TOC"]
    assert not toc["has_facts"] and toc["exchange"] == "OTC"
    assert toc["classification_notes"] == ["no submissions member"]


def test_preferred_only_issuer_is_no_common_equity(folder: Path, tmp_path: Path) -> None:
    d = shutil.copytree(folder, tmp_path / "2026-10-29")
    tick = orjson.loads((d / "company_tickers_exchange.json").read_bytes())
    tick["data"].append([1999999998, "Preferred Only Co", "PFX-PA", "NYSE"])  # no submissions
    (d / "company_tickers_exchange.json").write_bytes(orjson.dumps(tick))
    rows = {r["cik"]: r for r in build_companies(d, date(2026, 10, 29)).iter_rows(named=True)}
    pfx = rows["1999999998"]
    assert pfx["kind"] == "no_common_equity" and pfx["primary_ticker"] == "PFX.PA"
    assert pfx["classification_notes"][0] == "no submissions member"
    assert "no ticker is common stock" in pfx["classification_notes"][1]
    kept = {"AAPL", "TSM", "JPM", "XOM"}
    assert {r["kind"] for r in rows.values() if r["primary_ticker"] in kept} == {"operating"}


def test_contract_columns_load_into_the_ddl(folder: Path) -> None:
    import duckdb  # noqa: PLC0415

    path = write_companies(folder, date(2026, 10, 29)).path
    con = duckdb.connect()
    con.execute(COMPANIES)
    cols = ", ".join(CONTRACT_COLUMNS)
    con.execute(f"INSERT INTO companies ({cols}) SELECT {cols} FROM read_parquet(?)", [str(path)])
    assert con.execute("SELECT count(*) FROM companies").fetchone() == (len(TICKERS) + 1,)
    assert pl.read_parquet(path).height == len(TICKERS) + 1


def test_report_lists_ciks_without_submissions(folder: Path) -> None:
    assert write_companies(folder, date(2026, 10, 29)).missing_submissions == ["1999999999"]


def test_successor_without_annual_report_uses_predecessors(folder: Path, tmp_path: Path) -> None:
    """XOM (2115436) has only a 10-Q; config/cik_predecessors.yaml links it to Exxon (34088)."""
    d = shutil.copytree(folder, tmp_path / "2026-10-29")
    succ = orjson.loads((FIXTURE_DIR / "XOM.submissions.json").read_bytes())
    pred: dict[str, Any] = {
        **succ,
        "cik": "0000034088",
        "name": "EXXON MOBIL CORP",
        "tickers": [],
        "exchanges": [],
    }
    pred["filings"] = {"recent": {
        "acceptanceDateTime": ["2026-02-18T16:05:00.000Z"], "accessionNumber": ["0000034088-26-000010"],
        "filingDate": ["2026-02-18"], "form": ["10-K"], "isInlineXBRL": [1], "isXBRL": [1],
        "primaryDocument": ["xom-20251231.htm"], "reportDate": ["2025-12-31"],
    }, "files": []}  # fmt: skip
    with zipfile.ZipFile(d / "submissions.zip", "a") as zf:
        zf.writestr("CIK0000034088.json", orjson.dumps(pred))
    xom = (
        build_companies(d, date(2026, 10, 29))
        .filter(pl.col("primary_ticker") == "XOM")
        .row(0, named=True)
    )
    assert xom["cik"] == "0002115436" and xom["predecessor_cik"] == "0000034088"
    assert (xom["last_annual_form"], xom["last_annual_accn"]) == ("10-K", "0000034088-26-000010")
    assert "last annual report from predecessor CIK 0000034088" in xom["classification_notes"]


def test_empty_facts_dir_means_no_facts(tmp_path: Path) -> None:
    (tmp_path / "facts_raw").mkdir()
    assert facts_profiles(tmp_path / "facts_raw", revenue_tags()) == {}


def by_ticker(d: Path) -> dict[str, dict[str, Any]]:
    return {
        r["primary_ticker"]: r for r in build_companies(d, date(2026, 10, 29)).iter_rows(named=True)
    }


def test_up_c_columns_come_from_the_cached_cover(folder: Path, tmp_path: Path) -> None:
    """A cover cached for AAPL's latest filing, shaped like an Up-C, flows into the row; without
    one (every other fixture company), is_up_c is false and the economic columns are null."""
    d = shutil.copytree(folder, tmp_path / "sec" / "2026-10-29")
    aapl = by_ticker(d)["AAPL"]
    filed, accn, form = max(
        [(aapl["last_annual_date"], aapl["last_annual_accn"], "10-K"),
         (aapl["last_quarterly_date"], aapl["last_quarterly_accn"], "10-Q")],
    )  # fmt: skip
    as_of = date(2026, 7, 18)
    cover = Cover(
        aapl["cik"], accn, form, filed, "x_htm.xml",
        [ClassCount("us-gaap:CommonClassAMember", 6e9, as_of),
         ClassCount("us-gaap:CommonClassBMember", 4e9, as_of)], {},
        [NciPercent(date(2026, 6, 27), 0.40)],
    )  # fmt: skip
    path = cover_path(d.parent, aapl["cik"], accn)
    path.parent.mkdir(parents=True)
    path.write_bytes(cover.to_json())

    rows = by_ticker(d)
    up = rows["AAPL"]
    assert up["is_up_c"] and up["economic_shares"] == 1e10
    assert (up["economic_shares_as_of"], up["economic_shares_accn"]) == (as_of, accn)
    assert up["up_c_evidence"].startswith(f"{form} {accn}: cover page")
    assert any(n.startswith("Up-C: ") for n in up["classification_notes"])
    others = [r for t, r in rows.items() if t != "AAPL"]
    assert not any(r["is_up_c"] for r in others)
    assert all(r["economic_shares"] is None for r in others)
    assert {"is_up_c", "up_c_evidence"} <= set(CONTRACT_COLUMNS)


def test_finance_lease_columns_come_from_the_cached_covers(folder: Path, tmp_path: Path) -> None:
    """AAPL's latest filing tags a finance lease without naming its line; its latest 10-K (cached
    separately) names it. Every other fixture company has no cover: the columns stay null."""
    d = shutil.copytree(folder, tmp_path / "sec" / "2026-10-29")
    aapl = by_ticker(d)["AAPL"]
    k_accn, q_accn = aapl["last_annual_accn"], aapl["last_quarterly_accn"]
    assert aapl["last_annual_date"] < aapl["last_quarterly_date"]  # the fixture's 10-K is older
    bs, fy = date(2026, 6, 27), date(2025, 9, 27)
    lease = InstanceFact("us-gaap:FinanceLeaseLiabilityNoncurrent", 7.5e8, bs, "USD")
    q = Cover(aapl["cik"], q_accn, "10-Q", aapl["last_quarterly_date"], "q_htm.xml", [], {}, [],
              [lease])  # fmt: skip
    k = Cover(aapl["cik"], k_accn, "10-K", aapl["last_annual_date"], "k_htm.xml", [], {}, [], [],
              [LeaseLine("FinanceLeaseLiabilityNoncurrentStatementOfFinancialPositionExtensibleList",
                         ["us-gaap:OtherLiabilitiesNoncurrent"], fy)])  # fmt: skip
    for c in (q, k):
        path = cover_path(d.parent, aapl["cik"], c.accn)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(c.to_json())

    rows = by_ticker(d)
    r = rows["AAPL"]
    assert r["finance_lease_status"] == "stated"
    assert r["finance_lease_lines_noncurrent"] == ["us-gaap:OtherLiabilitiesNoncurrent"]
    assert r["finance_lease_lines_current"] is None
    assert (r["finance_lease_accn"], r["finance_lease_as_of"]) == (k_accn, fy)
    assert r["finance_lease_since"] == fy
    assert r["finance_lease_evidence"].startswith(f"10-K {k_accn} (2025-09-27): finance lease")
    others = [x for t, x in rows.items() if t != "AAPL"]
    assert all(x["finance_lease_status"] is None for x in others)
    assert {"finance_lease_status", "finance_lease_evidence"} <= set(CONTRACT_COLUMNS)


def _aapl_cover(
    d: Path, nci: list[NciPercent], symbols: dict[str, str] | None = None
) -> tuple[str, str]:
    aapl = by_ticker(d)["AAPL"]
    filed, accn, form = max(
        [(aapl["last_annual_date"], aapl["last_annual_accn"], "10-K"),
         (aapl["last_quarterly_date"], aapl["last_quarterly_accn"], "10-Q")],
    )  # fmt: skip
    as_of = date(2026, 7, 18)
    cover = Cover(
        aapl["cik"], accn, form, filed, "x_htm.xml",
        [ClassCount("us-gaap:CommonClassAMember", 6e9, as_of),
         ClassCount("us-gaap:CommonClassBMember", 4e9, as_of)], symbols or {}, nci,
    )  # fmt: skip
    path = cover_path(d.parent, aapl["cik"], accn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cover.to_json())
    return aapl["cik"], accn


def _rules_with(**update: Any) -> Rules:
    rules = load_rules()
    return dataclasses.replace(rules, up_c=rules.up_c.model_copy(update=update))


def test_confirmed_up_c_without_nci_flows_into_the_row(folder: Path, tmp_path: Path) -> None:
    d = shutil.copytree(folder, tmp_path / "sec" / "2026-10-29")
    cik, accn = _aapl_cover(d, nci=[])
    confirm = UpCConfirm(
        cik=cik, ticker="AAPL", source="10-K, accn x", quote="paired 1:1 with units",
        keyed_by="test",
    )  # fmt: skip
    rows = build_companies(d, date(2026, 10, 29), _rules_with(confirmed=(confirm,)))
    up = rows.filter(pl.col("cik") == cik).row(0, named=True)
    assert up["is_up_c"] and up["economic_shares"] == 1e10 and up["economic_shares_accn"] == accn
    assert "confirmed Up-C" in up["up_c_evidence"]


def test_excluded_beats_the_nci_rule(folder: Path, tmp_path: Path) -> None:
    d = shutil.copytree(folder, tmp_path / "sec" / "2026-10-29")
    cik, _ = _aapl_cover(d, nci=[NciPercent(date(2026, 6, 27), 0.40)])
    exclude = UpCExclude(cik=cik, ticker="AAPL", source="10-K, accn x", quote="no economics")
    rows = build_companies(d, date(2026, 10, 29), _rules_with(excluded=(exclude,)))
    row = rows.filter(pl.col("cik") == cik).row(0, named=True)
    assert not row["is_up_c"] and row["economic_shares"] is None


LISTED = {"us-gaap:CommonClassAMember": "AAPL", "us-gaap:CommonClassBMember": "AAPL-B"}


def test_listed_classes_flow_into_the_row(folder: Path, tmp_path: Path) -> None:
    """Both cover classes have a symbol and no NCI %: one record per class, parquet-only."""
    d = shutil.copytree(folder, tmp_path / "sec" / "2026-10-29")
    cik, accn = _aapl_cover(d, nci=[], symbols=LISTED)
    rows = build_companies(d, date(2026, 10, 29))
    row = rows.filter(pl.col("cik") == cik).row(0, named=True)
    assert not row["is_up_c"]
    assert [(c["ticker"], c["symbol"], c["shares"], c["accn"]) for c in row["listed_classes"]] == [
        ("AAPL", "AAPL", 6e9, accn),
        ("AAPL.B", "AAPL-B", 4e9, accn),
    ]
    assert rows.filter(pl.col("cik") != cik)["listed_classes"].null_count() == rows.height - 1
    assert "listed_classes" not in CONTRACT_COLUMNS and "listed_classes" not in COMPANIES


def test_up_c_and_excluded_get_no_listed_classes(
    folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = shutil.copytree(folder, tmp_path / "sec" / "2026-10-29")
    cik, _ = _aapl_cover(d, nci=[NciPercent(date(2026, 6, 27), 0.40)], symbols=LISTED)
    row = build_companies(d, date(2026, 10, 29)).filter(pl.col("cik") == cik).row(0, named=True)
    assert row["is_up_c"] and row["listed_classes"] is None

    _aapl_cover(d, nci=[], symbols=LISTED)
    monkeypatch.setattr("glint.universe.build.load_exclusions", lambda: {cik: None})
    row = build_companies(d, date(2026, 10, 29)).filter(pl.col("cik") == cik).row(0, named=True)
    assert row["listed_classes"] is None
