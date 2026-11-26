import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import orjson
import pytest

from glint.contracts.db import FACTS_RAW_COLUMNS
from glint.core.errors import SourceError
from glint.ingest.sec.extract import (
    bucket_of,
    extract_facts,
    load_whitelist,
    member_cik,
    whitelist_hash,
)

WHITELIST = {
    "us-gaap": frozenset({"Revenues", "Assets"}),
    "dei": frozenset({"EntityCommonStockSharesOutstanding"}),
    "ifrs-full": frozenset({"Revenue"}),
}


def fact(end: str, val: float | None, *, start: str | None = None, fy: int = 2025, fp: str = "FY",
         form: str = "10-K", frame: str | None = None) -> dict[str, Any]:  # fmt: skip
    f: dict[str, Any] = {"end": end, "val": val, "accn": "0000320193-25-000079", "fy": fy,
                         "fp": fp, "form": form, "filed": "2025-10-31"}  # fmt: skip
    if start:
        f["start"] = start
    if frame:
        f["frame"] = frame
    return f


AAPL: dict[str, Any] = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {"shares": [fact("2025-10-17", 1.5e10)]}
            }
        },
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        fact("2025-09-27", 416e9, start="2024-09-29", frame="CY2025"),
                        # comparative inside the FY2025 10-K: fy/fp describe the filing, kept raw
                        fact("2024-09-28", 391e9, start="2023-10-01", fy=2025, fp="FY"),
                        fact("2025-06-28", None, start="2025-03-30"),  # no value -> dropped
                    ]
                },
            },
            "Assets": {"units": {"USD": [fact("2025-09-27", 360e9)]}},
            "SomethingElse": {"units": {"USD": [fact("2025-09-27", 1.0)]}},
        },
        "srt": {"Revenues": {"units": {"USD": [fact("2025-09-27", 1.0)]}}},
    },
}
EMPTY_CO: dict[str, Any] = {"cik": 1750, "entityName": "No Kept Facts", "facts": {
    "us-gaap": {"SomethingElse": {"units": {"USD": [fact("2025-05-31", 1.0)]}}}}}  # fmt: skip
TSM: dict[str, Any] = {"cik": 1046179, "entityName": "TSMC", "facts": {"ifrs-full": {
    "Revenue": {"units": {"TWD": [fact("2024-12-31", 2.89e12, start="2024-01-01", form="20-F")]}}}}}  # fmt: skip


def make_zip(path: Path, docs: list[dict[str, Any]]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for d in docs:
            zf.writestr(f"CIK{d['cik']:010d}.json", orjson.dumps(d))
        zf.writestr("README.txt", b"not a company")
    return path


def read(out: Path) -> duckdb.DuckDBPyRelation:
    con = duckdb.connect()
    return con.sql(
        f"SELECT * FROM read_parquet('{out}/*/*.parquet', hive_partitioning = true) ORDER BY tag, \"end\""
    )


def test_helpers() -> None:
    assert member_cik("CIK0000320193.json") == "0000320193"
    assert member_cik("README.txt") is None
    assert bucket_of("0000320193") == 320193 % 64
    full = load_whitelist()
    assert "Revenues" in full["us-gaap"] and "EntityCommonStockSharesOutstanding" in full["dei"]
    assert set(full) <= {"us-gaap", "ifrs-full", "dei"}


def test_extracts_whitelisted_rows_with_contract_schema(tmp_path: Path) -> None:
    z = make_zip(tmp_path / "companyfacts.zip", [AAPL, EMPTY_CO, TSM])
    out = tmp_path / "facts_raw"
    stats = extract_facts(z, out, source_sha256="abc", whitelist=WHITELIST)
    assert (stats.companies, stats.companies_without_kept_facts, stats.facts_kept) == (3, 1, 5)

    rel = read(out)
    assert [c for c in rel.columns if c != "bucket"] == list(FACTS_RAW_COLUMNS)
    types = dict(zip(rel.columns, (str(t) for t in rel.types), strict=True))
    assert types["start"] == "DATE" and types["val"] == "DOUBLE" and types["fy"] == "INTEGER"
    rows = rel.fetchall()
    assert {r[2] for r in rows} == {
        "Revenues",
        "Assets",
        "EntityCommonStockSharesOutstanding",
        "Revenue",
    }
    assert all(r[1] != "srt" for r in rows)

    cols = rel.columns
    revs = [dict(zip(cols, r, strict=True)) for r in rows if r[2] == "Revenues"]
    assert [r["end"] for r in revs] == [date(2024, 9, 28), date(2025, 9, 27)]
    assert revs[0]["fy"] == 2025 and revs[0]["fp"] == "FY"  # raw filing fy/fp
    assert revs[1]["frame"] == "CY2025" and revs[0]["frame"] is None
    assert revs[1]["cik"] == "0000320193"
    instant = next(dict(zip(cols, r, strict=True)) for r in rows if r[2] == "Assets")
    assert instant["start"] is None
    tsm = next(dict(zip(cols, r, strict=True)) for r in rows if r[2] == "Revenue")
    assert (tsm["taxonomy"], tsm["unit"], tsm["form"]) == ("ifrs-full", "TWD", "20-F")


def test_partitions_by_cik_mod_64(tmp_path: Path) -> None:
    z = make_zip(tmp_path / "companyfacts.zip", [AAPL, TSM])
    out = tmp_path / "facts_raw"
    extract_facts(z, out, source_sha256="abc", whitelist=WHITELIST)
    dirs = sorted(p.name for p in out.iterdir() if p.is_dir())
    assert dirs == sorted({f"bucket={320193 % 64:02d}", f"bucket={1046179 % 64:02d}"})
    rows = (
        duckdb.connect()
        .sql(
            f"SELECT DISTINCT cik, bucket FROM read_parquet('{out}/*/*.parquet', hive_partitioning=true)"
        )
        .fetchall()
    )
    assert all(int(cik) % 64 == int(b) for cik, b in rows)


def test_small_flush_writes_several_parts(tmp_path: Path) -> None:
    same_bucket = {**AAPL, "cik": 65}  # 65 % 64 == 320193 % 64 == 1
    z = make_zip(tmp_path / "companyfacts.zip", [AAPL, same_bucket])
    out = tmp_path / "facts_raw"
    stats = extract_facts(z, out, source_sha256="abc", whitelist=WHITELIST, flush_rows=1)
    assert stats.files_written == 2  # flushes happen between companies, never mid-company
    assert sorted(p.name for p in (out / "bucket=01").iterdir()) == [
        "part-0.parquet",
        "part-1.parquet",
    ]
    assert len(read(out).fetchall()) == 8


def test_skips_when_stamp_matches_and_reextracts_when_whitelist_changes(tmp_path: Path) -> None:
    z = make_zip(tmp_path / "companyfacts.zip", [AAPL])
    out = tmp_path / "facts_raw"
    extract_facts(z, out, source_sha256="abc", whitelist=WHITELIST)
    again = extract_facts(z, out, source_sha256="abc", whitelist=WHITELIST)
    assert again.skipped and again.facts_kept == 4

    wider = {**WHITELIST, "us-gaap": WHITELIST["us-gaap"] | {"SomethingElse"}}
    assert whitelist_hash(wider) != whitelist_hash(WHITELIST)
    redo = extract_facts(z, out, source_sha256="abc", whitelist=wider)
    assert not redo.skipped and redo.facts_kept == 5


def test_reuses_previous_day_by_hard_link(tmp_path: Path) -> None:
    z = make_zip(tmp_path / "companyfacts.zip", [AAPL])
    day1, day2 = tmp_path / "d1" / "facts_raw", tmp_path / "d2" / "facts_raw"
    extract_facts(z, day1, source_sha256="abc", whitelist=WHITELIST)
    stats = extract_facts(z, day2, source_sha256="abc", whitelist=WHITELIST, previous_out=[day1])
    assert stats.reused_from == str(day1)
    a = next(day1.rglob("*.parquet"))
    b = day2 / a.relative_to(day1)
    assert a.stat().st_ino == b.stat().st_ino

    changed = extract_facts(z, tmp_path / "d3" / "facts_raw", source_sha256="new",
                            whitelist=WHITELIST, previous_out=[day1])  # fmt: skip
    assert changed.reused_from is None and not changed.skipped


def test_interrupted_reuse_leaves_no_stamped_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import glint.ingest.sec.extract as ex  # noqa: PLC0415

    z = make_zip(tmp_path / "companyfacts.zip", [AAPL])
    day1, day2 = tmp_path / "d1" / "facts_raw", tmp_path / "d2" / "facts_raw"
    extract_facts(z, day1, source_sha256="abc", whitelist=WHITELIST)

    def link_stamp_then_die(src: Path, dst: Path) -> None:
        dst.mkdir(parents=True)
        (dst / ex.STAMP).hardlink_to(src / ex.STAMP)
        raise OSError("interrupted")

    with monkeypatch.context() as m:
        m.setattr(ex, "_link_tree", link_stamp_then_die)
        with pytest.raises(OSError, match="interrupted"):
            extract_facts(z, day2, source_sha256="abc", whitelist=WHITELIST, previous_out=[day1])
    assert not day2.exists()
    stats = extract_facts(z, day2, source_sha256="abc", whitelist=WHITELIST, previous_out=[day1])
    assert stats.reused_from == str(day1) and any(day2.rglob("*.parquet"))


def test_bad_member_leaves_no_partial_output(tmp_path: Path) -> None:
    z = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CIK0000320193.json", b"{not json")
    out = tmp_path / "facts_raw"
    with pytest.raises(SourceError, match="cannot extract"):
        extract_facts(z, out, source_sha256="abc", whitelist=WHITELIST)
    assert not out.exists()
    assert not (tmp_path / "facts_raw.tmp").exists()
