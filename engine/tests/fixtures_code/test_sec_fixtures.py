from datetime import date
from pathlib import Path
from typing import Any

import orjson
import pytest
import yaml

from glint.core.errors import SourceError
from glint.fixtures import sec as sec_module
from glint.fixtures.sec import (
    CONCEPTS_PATH,
    Fixture,
    kept_tags,
    parse_form_index,
    parse_tickers_exchange,
    primary_rows,
    quarterly_filing_count,
    recent_quarters,
    sec_symbol,
    trim_companyfacts,
    trim_submissions,
    trim_tickers_exchange,
    write_fixtures,
)

FACTS: dict[str, Any] = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "label": "x",
                "units": {"shares": [{"end": "2025-10-17", "val": 1, "accn": "a1", "form": "10-K"}]},
            },
            "AmendmentFlag": {"units": {"pure": []}},
        },
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "description": "long text",
                "units": {"USD": [{"start": "2024-09-29", "end": "2025-09-27", "val": 5,
                                   "accn": "a1", "form": "10-K"},
                                  {"start": "2025-06-29", "end": "2025-09-27", "val": 2,
                                   "accn": "a2", "form": "10-Q"}]},
            },
            "SomethingElse": {"units": {"USD": []}},
        },
    },
}  # fmt: skip


def keep() -> dict[str, set[str]]:
    return kept_tags(yaml.safe_load(CONCEPTS_PATH.read_text()))


def test_kept_tags_include_concepts_and_dei() -> None:
    k = keep()
    assert "Revenues" in k["us-gaap"]
    assert "EntityCommonStockSharesOutstanding" in k["dei"]
    assert "Revenue" in k["ifrs-full"]


def test_kept_tags_include_evidence_tags() -> None:
    k = kept_tags({
        "line_items": {"revenue": {"tags": {"us-gaap": ["Revenues"]}}},
        "evidence_tags": {"us-gaap": {"lines": ["AccruedLiabilitiesCurrent"], "debt": ["NotesPayable"]}},
    })  # fmt: skip
    assert k["us-gaap"] == {"Revenues", "AccruedLiabilitiesCurrent", "NotesPayable"}
    assert {"OperatingLeaseLiabilityCurrent", "NotesPayable", "InterestPaidNet"} <= keep()[
        "us-gaap"
    ]


def test_trim_companyfacts_keeps_whitelist_drops_labels() -> None:
    out = trim_companyfacts(FACTS, keep())
    assert set(out["facts"]["us-gaap"]) == {"Revenues"}
    assert set(out["facts"]["dei"]) == {"EntityCommonStockSharesOutstanding"}
    assert "label" not in out["facts"]["us-gaap"]["Revenues"]
    assert (
        out["facts"]["us-gaap"]["Revenues"]["units"]
        == FACTS["facts"]["us-gaap"]["Revenues"]["units"]
    )


def test_trim_submissions_selects_columns() -> None:
    sub = {
        "cik": "320193",
        "sic": "3571",
        "filings": {
            "recent": {"accessionNumber": ["a"], "form": ["10-K"], "size": [1], "items": [""]},
            "files": [{"name": "older.json"}],
        },
    }
    out = trim_submissions(sub)
    assert out["sic"] == "3571"
    assert out["filings"] == {"recent": {"accessionNumber": ["a"], "form": ["10-K"]}}


def test_tickers_exchange_parse_and_trim() -> None:
    doc = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[1067983, "Berkshire", "BRK-B", "NYSE"], [1, "Other", "OTH", None]],
    }
    rows = parse_tickers_exchange(doc)
    assert rows[0].ticker == sec_symbol("BRK.B")
    assert rows[1].exchange is None
    assert trim_tickers_exchange(doc, {1067983})["data"] == [doc["data"][0]]


def test_parse_form_index() -> None:
    lines = [
        "Form Type   Company Name                                                  CIK         Date Filed  File Name",
        "-" * 100,
        "10-K        BIG CO INC                                                    123         2025-01-02  edgar/data/123/x.txt",
        "10-KT       FY CHANGER CORP                                               456         2025-02-03  edgar/data/456/y.txt",
        "NT 10-K     LATE INC                                                      789         2025-03-04  edgar/data/789/z.txt",
    ]  # fmt: skip
    entries = parse_form_index(lines, {"10-KT", "NT 10-K"})
    assert [(e.form, e.company, e.cik, e.filed) for e in entries] == [
        ("10-KT", "FY CHANGER CORP", 456, date(2025, 2, 3)),
        ("NT 10-K", "LATE INC", 789, date(2025, 3, 4)),
    ]


def test_quarterly_filing_count() -> None:
    assert quarterly_filing_count(FACTS) == 2


def test_recent_quarters_are_complete_quarters() -> None:
    assert recent_quarters(date(2026, 10, 28), 3) == [(2026, 3), (2026, 2), (2026, 1)]
    assert recent_quarters(date(2026, 2, 1), 2) == [(2025, 4), (2025, 3)]


def test_write_fixtures(tmp_path: Path) -> None:
    sub = {"cik": "320193", "filings": {"recent": {"form": ["10-K"]}}}
    fx = [Fixture("BRK.B", "role", 1067983, "Berkshire", FACTS, sub)]
    doc = {"fields": ["cik"], "data": [[1067983]]}
    total = write_fixtures(fx, doc, ["SPAC: none found"], tmp_path)
    assert total > 0
    assert (tmp_path / "BRK.B.companyfacts.json").exists()
    manifest = orjson.loads((tmp_path / "manifest.json").read_bytes())
    assert manifest["fixtures"][0]["cik"] == "0001067983"
    assert manifest["picks"] == ["SPAC: none found"]


def test_primary_rows_prefer_common_stock() -> None:
    doc = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[5, "Spac Acquisition", "AAC-WT", "NYSE"], [5, "Spac Acquisition", "AAC", "NYSE"],
                 [5, "Spac Acquisition", "AAC-U", "NYSE"]],
    }  # fmt: skip
    assert primary_rows(parse_tickers_exchange(doc))[5].ticker == "AAC"


def test_over_budget_run_keeps_the_previous_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "sec"
    out.mkdir()
    (out / "OLD.companyfacts.json").write_text("{}")
    monkeypatch.setattr(sec_module, "MAX_TOTAL_BYTES", 10)
    sub: dict[str, Any] = {"filings": {"recent": {}}}
    with pytest.raises(SourceError, match="budget"):
        write_fixtures([Fixture("AAPL", "r", 1, "n", FACTS, sub)], {"data": []}, [], out)
    assert [p.name for p in out.iterdir()] == ["OLD.companyfacts.json"]
    assert not (tmp_path / "sec.tmp").exists()
