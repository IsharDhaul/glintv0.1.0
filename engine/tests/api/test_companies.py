# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""search, company drawer, why-passed, history, and the lz-string decoder."""

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from glint.api.lzstring import LzStringError, decompress_from_encoded_uri_component
from glint.api.routers.companies import sec_filing_url
from glint.api.search import Entry, SearchIndex, ticker_key
from glint.contracts.enums import Kind, Sector
from glint.contracts.metrics import MetricRegistry
from tests.api.conftest import ClientFor, write_test_build

VECTORS: list[dict[str, str]] = json.loads((Path(__file__).parent / "lz_vectors.json").read_text())[
    "vectors"
]

# Synthetic stand-ins for the brief's real-name cases (repeated on the real build in WT-09):
#   "appel" → AAPL   ≈ a misspelt name      "orchad"  → SYNOR
#   "brk b" → BRK.B  ≈ a share class         "synh b"  → SYNH.B
#   "googl" → GOOGL  ≈ one ticker a prefix of the other, "syngl" → SYNGL (not SYNG)
EXTRA_COMPANIES = [
    ("9000100001", "Synthetic Orchard Inc.", ["SYNOR"], 2.0e12),
    ("9000100002", "Synthetic Holdings Class Co", ["SYNH.A", "SYNH.B"], 9.0e11),
    ("9000100003", "Synthetic Search Holdings", ["SYNGL", "SYNG"], 2.1e12),
    ("9000100004", "Orchards & Vines Synthetic", ["SYNOV"], 1.0e8),
]


@pytest.fixture(scope="module")
def search_data_dir(
    tmp_path_factory: pytest.TempPathFactory, live_registry: MetricRegistry
) -> Path:
    data = tmp_path_factory.mktemp("api-search") / "data"
    db = write_test_build(data, "syn-search", live_registry, 120)
    with duckdb.connect(str(db)) as con:
        template = con.execute("SELECT * FROM companies LIMIT 1").fetchone()
        cols = [d[0] for d in con.description]
        snap = con.execute("SELECT * FROM metrics_snapshot LIMIT 1").fetchone()
        snap_cols = [d[0] for d in con.description]
        assert template is not None and snap is not None
        for cik, name, tickers, mcap in EXTRA_COMPANIES:
            row = dict(zip(cols, template, strict=True))
            row |= {"cik": cik, "name": name, "tickers": tickers, "primary_ticker": tickers[0]}
            con.execute(
                f"INSERT INTO companies ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                list(row.values()),
            )
            s = dict(zip(snap_cols, snap, strict=True))
            s |= {"cik": cik, "name": name, "ticker": tickers[0], "market_cap": mcap}
            con.execute(
                f"INSERT INTO metrics_snapshot ({', '.join(snap_cols)}) "
                f"VALUES ({', '.join('?' * len(snap_cols))})",
                list(s.values()),
            )
    return data


@pytest.fixture
def search_client(client_for: ClientFor, search_data_dir: Path) -> TestClient:
    return client_for(search_data_dir)


def _search(c: TestClient, q: str) -> list[dict[str, Any]]:
    r = c.get("/api/search", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()["results"]


# --- search ------------------------------------------------------------------------------------


def test_misspelt_name_finds_the_company(search_client: TestClient) -> None:
    hits = _search(search_client, "orchad")
    assert "SYNOR" in [h["ticker"] for h in hits]
    assert next(h for h in hits if h["ticker"] == "SYNOR")["match"] == "fuzzy"


@pytest.mark.parametrize("q", ["synh b", "SYNH.B", "synh-b", "SYNHB", "synh/b"])
def test_share_class_spellings_find_the_class(search_client: TestClient, q: str) -> None:
    first = _search(search_client, q)[0]
    assert (first["ticker"], first["match"]) == ("SYNH.B", "exact")


def test_longer_ticker_wins_over_its_prefix(search_client: TestClient) -> None:
    hits = _search(search_client, "syngl")
    assert (hits[0]["ticker"], hits[0]["match"]) == ("SYNGL", "exact")
    assert [h["cik"] for h in hits].count("9000100003") == 1  # one hit per company


def test_tiers_come_in_order(search_client: TestClient) -> None:
    order = ["exact", "ticker_prefix", "name_prefix", "fuzzy"]
    for q in ["syn0042", "syn00", "synthetic co 004", "sinthetic co 0042", "orch"]:
        hits = _search(search_client, q)
        ranks = [order.index(h["match"]) for h in hits]
        assert ranks == sorted(ranks), q
        assert len(hits) <= 10


def test_exact_ticker_and_prefixes(search_client: TestClient) -> None:
    assert _search(search_client, "syn0042")[0]["ticker"] == "SYN0042"
    prefixed = _search(search_client, "syn004")
    assert {h["ticker"] for h in prefixed} == {f"SYN{i:04d}" for i in range(40, 50)}
    assert all(h["match"] == "ticker_prefix" for h in prefixed)


def test_name_prefix_orders_bigger_companies_first(search_client: TestClient) -> None:
    hits = [h for h in _search(search_client, "orchard") if h["match"] == "name_prefix"]
    assert [h["ticker"] for h in hits] == ["SYNOV"]
    hits = [h for h in _search(search_client, "synthetic") if h["match"] == "name_prefix"]
    assert hits[0]["ticker"] == "SYNGL"  # 2.1T beats 2.0T beats the rest


def test_fuzzy_misspelling_ranks_the_closest_first(search_client: TestClient) -> None:
    assert _search(search_client, "sinthetic co 0042")[0]["ticker"] == "SYN0042"


def test_no_match_is_empty(search_client: TestClient) -> None:
    assert _search(search_client, "qqqqzzzz") == []


def test_blank_query_is_invalid(search_client: TestClient) -> None:
    r = search_client.get("/api/search", params={"q": "   "})
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_REQUEST"


def test_exact_stored_ticker_beats_a_punctuation_match() -> None:
    def entry(cik: str, ticker: str, mcap: float) -> Entry:
        return Entry(cik=cik, name=f"Co {cik}", name_key=f"co {cik}", tickers=(ticker,),
                     ticker_keys=(ticker_key(ticker),), primary_ticker=ticker, exchange=None,
                     sector=Sector.UNCLASSIFIED, kind=Kind.SYNTHETIC, market_cap=mcap)  # fmt: skip

    index = SearchIndex([entry("1", "SYNH.B", 9e11), entry("2", "SYNHB", 1e6)])
    assert [h.ticker for h in index.search("synhb")] == ["SYNHB", "SYNH.B"]
    assert [h.ticker for h in index.search("synh.b")] == ["SYNH.B", "SYNHB"]
    exact = index.lookup("synhb")
    assert exact is not None and exact[1] == "SYNHB"
    loose = index.lookup("synh b")  # no exact spelling: the bigger company
    assert loose is not None and loose[1] == "SYNH.B"


def test_ticker_key() -> None:
    assert ticker_key(" brk.b ") == ticker_key("BRK-B") == ticker_key("brk b") == "BRKB"


# --- lz-string ---------------------------------------------------------------------------------


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["text"][:24] or "empty")
def test_lz_string_matches_the_js_library(vector: dict[str, str]) -> None:
    assert decompress_from_encoded_uri_component(vector["encoded"]) == vector["text"]


@pytest.mark.parametrize("bad", ["", "!!!", "BIUw"])
def test_lz_string_rejects_garbage(bad: str) -> None:
    with pytest.raises(LzStringError):
        decompress_from_encoded_uri_component(bad)


# --- company -----------------------------------------------------------------------------------


def test_company_drawer(client: TestClient, live_registry: MetricRegistry) -> None:
    r = client.get("/api/companies/syn0007")  # lower case works
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["build_id"] == "syn-small"
    assert b["company"]["tickers"] == ["SYN0007"]
    assert b["company"]["kind"] == "synthetic"
    assert b["as_of"] == {"fundamentals": "2026-01-02T08:00:00Z", "prices": "2026-01-01"}
    assert list(b["metrics"]) == [m.id for m in live_registry]
    for mid, m in b["metrics"].items():
        assert m["value"] is not None or m["note"] is not None, f"{mid} null without a reason"
    assert set(b["history"]) == {"revenue_ttm", "operating_margin", "fcf_margin",
                                 "share_count_change_yoy"} & set(b["history"])  # fmt: skip
    for points in b["history"].values():
        fy = [p for p in points if p["basis"] == "fy"]
        assert fy == sorted(fy, key=lambda p: p["period_end"])
    assert b["why_passed"] is None


def test_flags_are_questions_with_evidence(client: TestClient) -> None:
    for i in range(1, 60):
        flags = client.get(f"/api/companies/SYN{i:04d}").json()["flags"]
        if flags:
            assert all(f["question"].endswith("?") and f["evidence"] for f in flags)
            assert all(f["severity"] in ("caution", "info") for f in flags)
            return
    pytest.fail("no flagged company in the first 60")


def test_unknown_ticker_is_404(client: TestClient) -> None:
    r = client.get("/api/companies/NOPE")
    assert r.status_code == 404
    assert r.json()["error"] == "UNKNOWN_TICKER"
    assert r.json()["build_id"] == "syn-small"


def test_company_without_build_is_503(client_for: ClientFor, tmp_path: Path) -> None:
    assert client_for(tmp_path / "none").get("/api/companies/SYN0001").status_code == 503


def test_sec_filing_url() -> None:
    assert (
        sec_filing_url("0000320193", "0000320193-25-000079")
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
    )


def test_sources_list_the_filings_used(client_for: ClientFor, tmp_path: Path,
                                       live_registry: MetricRegistry) -> None:  # fmt: skip
    """One entry per accession, newest first, form null (never guessed), derived rows skipped."""
    data = tmp_path / "data"
    db = write_test_build(data, "src", live_registry, 10)
    rows = [
        # line_item, period_end, accn, filed
        ("revenue", "2025-09-27", "0009000001-25-000079", "2025-10-31"),
        ("net_income", "2025-09-27", "0009000001-25-000079", "2025-10-31"),  # same filing
        ("revenue", "2024-09-28", "0009000001-24-000123", "2024-11-01"),
        ("fcf", "2025-09-27", None, None),  # derived: no source filing
    ]
    with duckdb.connect(str(db)) as con:
        for item, end, accn, filed in rows:
            con.execute(
                "INSERT INTO financials VALUES ('9000000001', ?, 'fy', ?, NULL, 1.0, 'USD', "
                "NULL, ?, ?, 1.0, ?, ?)",
                [item, end, accn, filed, filed, accn is None],
            )
    sources = client_for(data).get("/api/companies/SYN0001").json()["sources"]
    assert sources == [
        {
            "accn": "0009000001-25-000079",
            "form": None,
            "filed": "2025-10-31",
            "url": "https://www.sec.gov/Archives/edgar/data/9000000001/000900000125000079/",
        },
        {
            "accn": "0009000001-24-000123",
            "form": None,
            "filed": "2024-11-01",
            "url": "https://www.sec.gov/Archives/edgar/data/9000000001/000900000124000123/",
        },
    ]


def test_synthetic_company_has_no_sources(client: TestClient) -> None:
    """Synthetic builds have no financials, so no filings to cite (and none invented)."""
    assert client.get("/api/companies/SYN0001").json()["sources"] == []


# --- why passed --------------------------------------------------------------------------------


def _encoded(name: str) -> str:
    return next(v["encoded"] for v in VECTORS if f'"name":"{name}"' in v["text"])


def test_why_passed_agrees_with_the_screen(client: TestClient) -> None:
    encoded = _encoded("Quality compounders")
    screen = json.loads(decompress_from_encoded_uri_component(encoded))
    screened = client.post("/api/screen", json=screen).json()
    leaf_count = len(screen["filters"]["children"])

    passing = screened["results"][0]["ticker"]
    why = client.get(f"/api/companies/{passing}", params={"screen": encoded}).json()["why_passed"]
    assert why[0] == {"filter_path": ["universe"], "label": "Universe", "passed": True,
                      "value": None, "sector_percentile": None}  # fmt: skip
    assert len(why) == 1 + leaf_count
    assert all(o["passed"] for o in why)
    assert [o["filter_path"] for o in why[1:]] == [
        ["filters", "children", i] for i in range(leaf_count)
    ]
    for o in why[1:]:
        assert o["value"] is not None
        assert o["sector_percentile"] is None or 0 <= o["sector_percentile"] <= 1

    miss = screened["near_misses"][0]
    why = client.get(f"/api/companies/{miss['ticker']}", params={"screen": encoded}).json()
    failed = [o for o in why["why_passed"] if not o["passed"]]
    assert [o["filter_path"] for o in failed] == [miss["failed_filter_path"]]


def test_why_passed_nested_groups(client: TestClient) -> None:
    """Leaf paths and verdicts line up through AND/OR/AND nesting."""
    encoded = _encoded("Nested")
    screen = json.loads(decompress_from_encoded_uri_component(encoded))
    screened = client.post("/api/screen", json=screen).json()
    top0, top2 = ("filters", "children", 0), ("filters", "children", 2)
    or_a = ("filters", "children", 1, "children", 0)
    and_a = ("filters", "children", 1, "children", 1, "children", 0)
    and_b = ("filters", "children", 1, "children", 1, "children", 1)
    assert screened["results"] and screened["near_misses"]
    for row in screened["results"][:5]:
        why = client.get(f"/api/companies/{row['ticker']}", params={"screen": encoded}).json()
        outcomes = why["why_passed"][1:]
        assert [tuple(o["filter_path"]) for o in outcomes] == [top0, or_a, and_a, and_b, top2]
        ok = {tuple(o["filter_path"]): o["passed"] for o in outcomes}
        # It passed: both top-level ANDs hold, and the OR has a passing branch.
        assert ok[top0] and ok[top2] and (ok[or_a] or (ok[and_a] and ok[and_b]))
    for miss in screened["near_misses"][:5]:
        why = client.get(f"/api/companies/{miss['ticker']}", params={"screen": encoded}).json()
        failed_steps = {
            tuple(o["filter_path"][:3]) for o in why["why_passed"][1:] if not o["passed"]
        }
        assert tuple(miss["failed_filter_path"]) in failed_steps


def test_why_passed_outside_the_universe(client: TestClient, small_data_dir: Path) -> None:
    """A company the universe excludes (stale, by default) gets one outcome: universe, failed."""
    db = small_data_dir / "builds" / "syn-small.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        row = con.execute("SELECT ticker FROM metrics_snapshot WHERE is_stale LIMIT 1").fetchone()
    assert row is not None
    r = client.get(f"/api/companies/{row[0]}", params={"screen": _encoded("Quality compounders")})
    assert r.json()["why_passed"] == [
        {"filter_path": ["universe"], "label": "Universe", "passed": False, "value": None,
         "sector_percentile": None}
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("screen", "path"),
    [
        ("!!", ["screen"]),  # not lz-string
        (_encoded("Magic Formula")[:-6], ["screen"]),  # truncated
        (
            next(v["encoded"] for v in VECTORS if v["text"] == "Hello, world"),
            ["screen"],
        ),  # not JSON
        (_encoded("Bad limit"), ["screen", "limit"]),  # not a valid Screen
        (_encoded("Unknown metric"), ["screen", "filters", "children", 0, "metric"]),
    ],
)
def test_why_passed_bad_screen_is_422(client: TestClient, screen: str, path: list[Any]) -> None:
    r = client.get("/api/companies/SYN0001", params={"screen": screen})
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_SCREEN"
    assert r.json()["path"] == path


# --- history -----------------------------------------------------------------------------------


def test_history(client: TestClient) -> None:
    r = client.get("/api/companies/SYN0003/history", params={"metric": "operating_margin"})
    assert r.status_code == 200
    b = r.json()
    assert (b["ticker"], b["metric"]) == ("SYN0003", "operating_margin")
    assert {p["basis"] for p in b["points"]} == {"fy", "ttm"}
    drawer = client.get("/api/companies/SYN0003").json()["history"]["operating_margin"]
    assert b["points"] == drawer


def test_history_of_untracked_metric_is_empty(client: TestClient) -> None:
    r = client.get("/api/companies/SYN0003/history", params={"metric": "roic"})
    assert r.status_code == 200
    assert r.json()["points"] == []


def test_history_unknown_metric_is_404(client: TestClient) -> None:
    r = client.get("/api/companies/SYN0003/history", params={"metric": "nope"})
    assert r.status_code == 404
    assert r.json()["error"] == "UNKNOWN_METRIC"
