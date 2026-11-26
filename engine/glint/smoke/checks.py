"""`glint smoke` checks (WT-09 step 4). They go through the HTTP API, so they see what the UI
sees, and parse every body with the contract models, so a shape drift fails too.

Three groups: every preset runs (no error, total in range, sieve counts never go up); every
Appendix D company answers with its expected kind and null reasons; the search cases resolve.
`--perf` adds the §5.10 API budgets, timed on this build.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from glint.contracts.api import (
    CompanyHeader,
    CompanyResponse,
    ErrorResponse,
    MetaResponse,
    PresetListResponse,
    PresetResponse,
    ScreenResponse,
    SearchResponse,
)
from glint.contracts.enums import ApplicabilityScope, Kind, NoteCode, Sector
from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import Screen

EXPECTATIONS_FILE = Path(__file__).with_name("expectations.yaml")
SEC_URL_PREFIX = "https://www.sec.gov/"

S = ApplicabilityScope
SECTOR_SCOPE = {
    Sector.BANKS: S.BANKS,
    Sector.INSURANCE: S.INSURANCE,
    Sector.CAPITAL_MARKETS: S.CAPITAL_MARKETS,
    Sector.UTILITIES: S.UTILITIES,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyExpect(_Strict):
    kind: Kind = Kind.OPERATING
    sector: Sector | None = None
    is_reit: bool | None = None
    is_foreign_filer: bool | None = None
    notes: dict[str, NoteCode] = {}


class SearchExpect(_Strict):
    q: str
    top: str


class PerfExpect(_Strict):
    runs: int
    screen_p95_ms: float
    company_p95_ms: float
    screen: Screen


class Expectations(_Strict):
    preset_total: tuple[int, int]
    companies: dict[str, CompanyExpect]
    search: list[SearchExpect]
    perf: PerfExpect | None = None


def load_expectations(path: Path = EXPECTATIONS_FILE) -> Expectations:
    return Expectations.model_validate(yaml.safe_load(path.read_text()))


class Response(Protocol):
    @property
    def status_code(self) -> int: ...
    def json(self) -> Any: ...


class Client(Protocol):
    """What smoke needs from a client: Starlette's TestClient fits."""

    def get(self, url: str, **kwargs: Any) -> Response: ...
    def post(self, url: str, **kwargs: Any) -> Response: ...


@dataclass
class Check:
    group: str
    name: str
    problems: list[str] = field(default_factory=list[str])
    detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems


class _FailedError(Exception):
    pass


def _fetch[M: BaseModel](resp: Response, model: type[M], what: str) -> M:
    """The body as `model`, or _FailedError naming the request and what went wrong."""
    if resp.status_code != 200:
        try:
            msg = ErrorResponse.model_validate(resp.json()).message
        except (ValueError, ValidationError):  # not JSON, or not our error shape
            msg = None
        raise _FailedError(f"{what} → {resp.status_code}" + (f": {msg}" if msg else ""))
    try:
        return model.model_validate(resp.json())
    except ValidationError as e:
        raise _FailedError(f"{what}: response doesn't match {model.__name__}: {e}") from e


def check_build(client: Client) -> Check:
    c = Check("build", "meta")
    try:
        meta = _fetch(client.get("/api/meta"), MetaResponse, "GET /api/meta")
    except _FailedError as e:
        c.problems.append(str(e))
        return c
    if meta.synthetic:
        c.problems.append("the current build is synthetic; smoke checks a real build")
    if meta.as_of.fundamentals is None:
        c.problems.append("no fundamentals as-of stamp")
    if meta.as_of.prices is None:
        c.problems.append("no prices as-of stamp")
    c.detail = (
        f"{meta.build_id} · fundamentals {meta.as_of.fundamentals:%Y-%m-%d} · "
        f"prices {meta.as_of.prices}"
        if meta.as_of.fundamentals
        else str(meta.build_id)
    )
    return c


def check_presets(client: Client, total_range: tuple[int, int]) -> list[Check]:
    try:
        listing = _fetch(client.get("/api/presets"), PresetListResponse, "GET /api/presets")
    except _FailedError as e:
        return [Check("presets", "list", [str(e)])]
    if not listing.presets:
        return [Check("presets", "list", ["no presets"])]
    return [check_preset(client, p.id, total_range) for p in listing.presets]


def check_preset(client: Client, preset_id: str, total_range: tuple[int, int]) -> Check:
    c = Check("presets", preset_id)
    try:
        preset = _fetch(
            client.get(f"/api/presets/{preset_id}"), PresetResponse, f"GET /api/presets/{preset_id}"
        ).preset
        out = _fetch(
            client.post("/api/screen", json=preset.screen.model_dump(mode="json")),
            ScreenResponse,
            "POST /api/screen",
        )
    except _FailedError as e:
        c.problems.append(str(e))
        return c
    lo, hi = total_range
    if not lo <= out.total <= hi:
        c.problems.append(f"total {out.total} outside [{lo}, {hi}]")
    remaining = [s.remaining for s in out.funnel]
    for before, after in pairwise(remaining):
        if after > before:
            c.problems.append(f"sieve count goes up: {before} → {after}")
    if remaining and remaining[-1] != out.total:
        c.problems.append(f"total {out.total} but the sieve ends at {remaining[-1]}")
    c.detail = f"{out.total} results · sieve " + " → ".join(f"{n:,}" for n in remaining)
    return c


def _sector_scopes(company: CompanyHeader) -> set[ApplicabilityScope]:
    """The §4.5 scopes (other than foreign filers) a company falls in, from its header."""
    scopes: set[ApplicabilityScope] = set()
    if company.sector in SECTOR_SCOPE:
        scopes.add(SECTOR_SCOPE[company.sector])
    if company.is_reit:
        scopes.add(S.REITS)
    return scopes


def check_company(
    client: Client, ticker: str, want: CompanyExpect, registry: MetricRegistry
) -> Check:
    c = Check("companies", ticker)
    try:
        body = _fetch(
            client.get(f"/api/companies/{ticker}"), CompanyResponse, f"GET /api/companies/{ticker}"
        )
    except _FailedError as e:
        c.problems.append(str(e))
        return c
    co = body.company
    for attr in ("kind", "sector", "is_reit", "is_foreign_filer"):
        expected = getattr(want, attr)
        if expected is not None and getattr(co, attr) != expected:
            c.problems.append(f"{attr}: expected {expected}, got {getattr(co, attr)}")

    def code(metric_id: str) -> str | None:
        mv = body.metrics.get(metric_id)
        return mv.note.code if mv is not None and mv.note is not None else None

    for metric_id, expected in want.notes.items():
        if metric_id not in body.metrics:
            c.problems.append(f"{metric_id}: missing from the response")
        elif code(metric_id) != expected:
            got = code(metric_id) or f"value {body.metrics[metric_id].value!r}"
            c.problems.append(f"{metric_id}: expected {expected}, got {got}")

    # Every live metric is served, and the registry's applicability matrix holds. The foreign
    # scope also depends on `foreign_price_ok`, which the header doesn't carry, so foreign filers
    # are pinned in `notes` instead.
    missing = [m.id for m in registry.live() if m.id not in body.metrics]
    if missing:
        c.problems.append(f"live metrics missing from the response: {', '.join(missing)}")
    scopes = _sector_scopes(co)
    for m in registry.live():
        nm = scopes & set(m.applicability.not_meaningful)
        if nm and m.id in body.metrics and code(m.id) != NoteCode.NOT_APPLICABLE_SECTOR:
            c.problems.append(f"{m.id}: n/m for {co.sector} but got {code(m.id)}")

    # Principle 3: a null always carries a reason.
    unexplained = [k for k, mv in body.metrics.items() if mv.value is None and mv.note is None]
    if unexplained:
        c.problems.append(f"null without a reason: {', '.join(unexplained)}")
    if co.has_facts and co.kind is not Kind.SYNTHETIC and not body.sources:
        c.problems.append("no source filings")
    off_sec = [s.url for s in body.sources if not s.url.startswith(SEC_URL_PREFIX)]
    if off_sec:
        c.problems.append(f"source links off sec.gov: {off_sec[:3]}")

    nulls = sum(mv.value is None for mv in body.metrics.values())
    nm = sum(code(k) == NoteCode.NOT_APPLICABLE_SECTOR for k in body.metrics)
    c.detail = (
        f"{co.kind} · {co.sector} · {nulls}/{len(body.metrics)} null ({nm} n/m) · "
        f"{len(body.sources)} sources"
    )
    return c


def check_search(client: Client, case: SearchExpect) -> Check:
    c = Check("search", repr(case.q))
    try:
        hits = _fetch(
            client.get("/api/search", params={"q": case.q}), SearchResponse, "GET /api/search"
        ).results
    except _FailedError as e:
        c.problems.append(str(e))
        return c
    top = hits[0].ticker if hits else None
    if top != case.top:
        c.problems.append(f"top hit {top}, expected {case.top}")
    c.detail = ", ".join(f"{h.ticker} ({h.match})" for h in hits[:3]) or "no hits"
    return c


def run_smoke(client: Client, want: Expectations, registry: MetricRegistry) -> list[Check]:
    checks = [check_build(client)]
    checks += check_presets(client, want.preset_total)
    checks += [check_company(client, t, e, registry) for t, e in want.companies.items()]
    checks += [check_search(client, case) for case in want.search]
    return checks


def _p50_p95(call: Callable[[int], None], runs: int) -> tuple[float, float]:
    """Timings in ms after one warm-up call (caches, DuckDB's first-run work)."""
    call(0)
    timings: list[float] = []
    for i in range(runs):
        start = time.perf_counter()
        call(i)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return timings[runs // 2], timings[max(int(runs * 0.95) - 1, 0)]


def check_perf(client: Client, want: PerfExpect | None, tickers: list[str]) -> list[Check]:
    if want is None or not tickers:
        return [Check("perf", "budgets", ["--perf needs a perf section and at least one company"])]
    body = want.screen.model_dump(mode="json")

    def screen(_: int) -> None:
        _fetch(client.post("/api/screen", json=body), ScreenResponse, "POST /api/screen")

    def company(i: int) -> None:
        t = tickers[i % len(tickers)]
        _fetch(client.get(f"/api/companies/{t}"), CompanyResponse, f"GET /api/companies/{t}")

    out: list[Check] = []
    for name, call, budget in [
        ("POST /api/screen (10 filters, near misses)", screen, want.screen_p95_ms),
        ("GET /api/companies/{t}", company, want.company_p95_ms),
    ]:
        c = Check("perf", name)
        try:
            p50, p95 = _p50_p95(call, want.runs)
        except _FailedError as e:
            c.problems.append(str(e))
        else:
            c.detail = (
                f"p50 {p50:.1f} ms · p95 {p95:.1f} ms (budget {budget:.0f}) · {want.runs} runs"
            )
            if p95 >= budget:
                c.problems.append(c.detail)
        out.append(c)
    return out
