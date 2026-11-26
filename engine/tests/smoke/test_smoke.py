# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""glint smoke over a synthetic build: the checks pass where they should and name the failure
where they shouldn't. The real-build run is the WT-09 acceptance evidence, not a test."""

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from glint.cli import app
from glint.contracts.enums import Kind, NoteCode
from glint.contracts.metrics import MetricRegistry
from glint.smoke.checks import (
    CompanyExpect,
    SearchExpect,
    check_build,
    check_company,
    check_perf,
    check_presets,
    check_search,
    load_expectations,
)
from tests.api.conftest import ClientFor, write_test_build

MANIFEST = Path(__file__).parents[1] / "fixtures" / "sec" / "manifest.json"
SECOND_CLASSES = {"BRK.A", "GOOG"}  # Appendix D's other share classes; one fixture per CIK


@dataclass
class _Edited:
    status_code: int
    body: Any

    def json(self) -> Any:
        return self.body


class TamperedClient:
    """The real API, with one response body edited: each check must catch its own defect."""

    def __init__(self, client: TestClient, path: str, edit: Callable[[Any], None]) -> None:
        self.client, self.path, self.edit = client, path, edit

    def _wrap(self, url: str, resp: Any) -> Any:
        if not url.startswith(self.path):
            return resp
        body = copy.deepcopy(resp.json())
        self.edit(body)
        return _Edited(resp.status_code, body)

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._wrap(url, self.client.get(url, **kwargs))

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._wrap(url, self.client.post(url, **kwargs))


@pytest.fixture
def synthetic(client: TestClient, small_data_dir: Path) -> dict[str, object]:
    """One synthetic company's header, read back through the API."""
    db = small_data_dir / "builds" / "syn-small.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        row = con.execute(
            "SELECT primary_ticker FROM companies WHERE has_facts AND primary_ticker IS NOT NULL"
            " ORDER BY cik LIMIT 1"
        ).fetchone()
    assert row is not None
    return client.get(f"/api/companies/{row[0]}").json()["company"]


def test_expectations_cover_appendix_d() -> None:
    fixtures = {f["ticker"] for f in json.loads(MANIFEST.read_text())["fixtures"]}
    assert set(load_expectations().companies) == fixtures | SECOND_CLASSES


def test_build_check_rejects_a_synthetic_build(client: TestClient) -> None:
    c = check_build(client)
    assert any("synthetic" in p for p in c.problems)


def test_presets_run_and_sieve_never_grows(client: TestClient) -> None:
    checks = check_presets(client, (0, 10**6))
    assert checks and all(c.ok for c in checks), [c.problems for c in checks]
    assert all("sieve" in c.detail for c in checks)


def test_preset_total_out_of_range_fails(client: TestClient) -> None:
    checks = check_presets(client, (10**6, 10**7))
    assert all(any("outside" in p for p in c.problems) for c in checks)


def test_company_matches_its_header(
    client: TestClient, synthetic: dict[str, object], live_registry: MetricRegistry
) -> None:
    want = CompanyExpect(kind=Kind.SYNTHETIC, sector=synthetic["sector"])  # type: ignore[arg-type]
    c = check_company(client, str(synthetic["primary_ticker"]), want, live_registry)
    assert c.ok, c.problems


def test_company_mismatch_names_the_field_and_metric(
    client: TestClient, synthetic: dict[str, object], live_registry: MetricRegistry
) -> None:
    want = CompanyExpect(notes={"pe_ttm": NoteCode.STALE_DATA})
    c = check_company(client, str(synthetic["primary_ticker"]), want, live_registry)
    assert any(p.startswith("kind: expected operating") for p in c.problems)
    assert any(p.startswith("pe_ttm: expected STALE_DATA") for p in c.problems)


def test_unknown_company_fails_with_the_status(
    client: TestClient, live_registry: MetricRegistry
) -> None:
    c = check_company(client, "NOPE", CompanyExpect(), live_registry)
    assert c.problems == ["GET /api/companies/NOPE → 404: No company with ticker 'NOPE'"]


def test_search_top_hit(client: TestClient, synthetic: dict[str, object]) -> None:
    ticker = str(synthetic["primary_ticker"])
    assert check_search(client, SearchExpect(q=ticker.lower(), top=ticker)).ok
    miss = check_search(client, SearchExpect(q=ticker, top="ZZZZ"))
    assert miss.problems == [f"top hit {ticker}, expected ZZZZ"]


def test_cli_exits_1_on_failure(
    db_dir: Path, client_for: ClientFor, live_registry: MetricRegistry, tmp_path: Path
) -> None:
    write_test_build(db_dir, "syn-smoke", live_registry, 120)
    want = tmp_path / "want.yaml"
    want.write_text("preset_total: [0, 1000000]\ncompanies: {}\nsearch: []\n")
    result = CliRunner().invoke(app, ["smoke", "--expectations", str(want)])
    assert result.exit_code == 1, result.output
    assert "synthetic" in result.output


def test_perf_times_both_endpoints(client: TestClient, synthetic: dict[str, object]) -> None:
    want = load_expectations().perf
    assert want is not None
    fast = want.model_copy(update={"runs": 3, "screen_p95_ms": 1e9, "company_p95_ms": 1e9})
    tickers = [str(synthetic["primary_ticker"])]
    checks = check_perf(client, fast, tickers)
    assert [c.ok for c in checks] == [True, True], [c.problems for c in checks]
    assert all("p95" in c.detail for c in checks)
    slow = fast.model_copy(update={"screen_p95_ms": 0.0})
    assert not check_perf(client, slow, tickers)[0].ok
    assert check_perf(client, None, tickers)[0].problems


def _grow_sieve(body: Any) -> None:
    grown = {**body["funnel"][-1], "remaining": body["funnel"][-1]["remaining"] + 1}
    body["funnel"].append(grown)
    body["total"] = grown["remaining"]


def _total_off_sieve(body: Any) -> None:
    body["total"] += 1


@pytest.mark.parametrize(
    ("edit", "problem"),
    [(_grow_sieve, "sieve count goes up"), (_total_off_sieve, "but the sieve ends at")],
)
def test_preset_defects_fail(client: TestClient, edit: Callable[[Any], None], problem: str) -> None:
    checks = check_presets(TamperedClient(client, "/api/screen", edit), (0, 10**6))
    assert checks and all(any(problem in p for p in c.problems) for c in checks)


def _null_without_reason(body: Any) -> None:
    metric = next(k for k, v in body["metrics"].items() if v["value"] is not None)
    body["metrics"][metric] = {"value": None, "note": None}


def _off_sec_source(body: Any) -> None:
    body["sources"].append(
        {"accn": "0000000000-26-000001", "form": "10-K", "filed": "2026-01-02",
         "url": "https://example.com/filing"}
    )  # fmt: skip


def _now_a_bank(body: Any) -> None:
    body["company"]["sector"] = "Banks"


def _drop_a_metric(body: Any) -> None:
    del body["metrics"]["roic"]


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (_null_without_reason, "null without a reason"),
        (_off_sec_source, "source links off sec.gov"),
        (_now_a_bank, "n/m for Banks but got"),
        (_drop_a_metric, "live metrics missing from the response: roic"),
    ],
)
def test_company_defects_fail(
    client: TestClient,
    synthetic: dict[str, object],
    live_registry: MetricRegistry,
    edit: Callable[[Any], None],
    problem: str,
) -> None:
    ticker = str(synthetic["primary_ticker"])
    tampered = TamperedClient(client, f"/api/companies/{ticker}", edit)
    want = CompanyExpect(kind=Kind.SYNTHETIC)
    c = check_company(tampered, ticker, want, live_registry)
    assert any(problem in p for p in c.problems), c.problems
