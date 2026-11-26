"""`glint fixtures synthetic`: a fake but plausible build for WT-04/05/08 to develop against.

Synthetic data must be impossible to mistake for real data: tickers are `SYN0001…`, names are
"Synthetic Co 0001", every row has `kind="synthetic"`, CIKs start at 9000000001 (beyond any real
CIK), and the build pointer and `/api/meta` say `synthetic: true`.

Values come from a small per-company model (revenue, margins, capital structure, price) so that
metrics relate to each other plausibly, with sector-shaped distributions. Nulls carry valid reason
codes: n/m per the applicability matrix, NEGATIVE_DENOMINATOR where a formula breaks, and ~2%
random MISSING_INPUT / INSUFFICIENT_HISTORY.
"""

import json
import math
import random
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import yaml

from glint.contracts.api import (
    CellNote,
    CellValue,
    CompanyHeader,
    FlagOut,
    MetricsResponse,
    ResultRow,
)
from glint.contracts.db import (
    BUILD_TABLES,
    DB_SCHEMA_VERSION,
    CurrentPointer,
    metrics_snapshot_ddl,
)
from glint.contracts.enums import (
    ApplicabilityScope,
    Exchange,
    FlagId,
    FlagSeverity,
    Kind,
    NoteCode,
    Sector,
    Unit,
)
from glint.contracts.metrics import MetricDefinition, MetricRegistry, load_registry
from glint.contracts.screen import Screen
from glint.core.log import get_logger, log_event
from glint.core.paths import Paths
from glint.core.settings import REPO_ROOT
from glint.flags.engine import load_rules
from glint.screen.config import load_screen_config

log = get_logger(__name__)

BUILD_ID = "synthetic"
AS_OF = date(2026, 1, 2)  # fixed, so the build and mocks are reproducible
TTM_END = date(2025, 9, 30)  # the latest quarter end before AS_OF, for note wording
CIK_BASE = 9_000_000_000
MOCKS_DIR = REPO_ROOT / "web" / "mocks"
MOCK_COMPANIES = 300
RANDOM_NULL_RATE = 0.02
THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"
SECTORS_PATH = REPO_ROOT / "config" / "sectors.yaml"
HISTORY_METRICS = ("revenue_ttm", "operating_margin", "fcf_margin", "share_count_change_yoy")

# Rough share of US listings per sector, and sector shapes:
# (gross margin, operating margin, EV/sales, leverage = net debt / revenue)
SECTOR_PROFILE: dict[Sector, tuple[float, float, float, float, float]] = {
    Sector.TECHNOLOGY: (0.16, 0.58, 0.08, 5.0, -0.2),
    Sector.HEALTH_CARE: (0.17, 0.55, -0.05, 4.0, 0.0),
    Sector.INDUSTRIALS: (0.14, 0.30, 0.09, 1.6, 0.4),
    Sector.CONSUMER_DISCRETIONARY: (0.10, 0.38, 0.07, 1.2, 0.5),
    Sector.BANKS: (0.08, 0.0, 0.25, 3.0, 0.0),
    Sector.CAPITAL_MARKETS: (0.04, 0.0, 0.22, 4.0, 0.0),
    Sector.INSURANCE: (0.03, 0.0, 0.10, 1.2, 0.0),
    Sector.ENERGY: (0.05, 0.32, 0.12, 1.5, 0.8),
    Sector.MATERIALS: (0.04, 0.27, 0.10, 1.4, 0.6),
    Sector.REAL_ESTATE: (0.04, 0.60, 0.30, 9.0, 4.0),
    Sector.COMMUNICATION: (0.04, 0.50, 0.12, 2.5, 1.0),
    Sector.CONSUMER_STAPLES: (0.03, 0.35, 0.10, 1.8, 0.6),
    Sector.UTILITIES: (0.02, 0.42, 0.18, 3.5, 3.0),
    Sector.UNCLASSIFIED: (0.06, 0.35, 0.02, 2.0, 0.3),
}
SECTOR_SCOPE = {
    Sector.BANKS: ApplicabilityScope.BANKS,
    Sector.INSURANCE: ApplicabilityScope.INSURANCE,
    Sector.CAPITAL_MARKETS: ApplicabilityScope.CAPITAL_MARKETS,
    Sector.UTILITIES: ApplicabilityScope.UTILITIES,
}
EXCHANGES = ((Exchange.NASDAQ, 0.58), (Exchange.NYSE, 0.37), (Exchange.NYSE_AMERICAN, 0.05))
FYE = (("1231", 0.7), ("0930", 0.1), ("0630", 0.1), ("0331", 0.1))
HISTORY_METRIC_IDS = {"revenue_growth_yoy", "revenue_cagr_3y", "revenue_cagr_5y",
                      "eps_growth_yoy", "ebit_growth_yoy", "fcf_growth_yoy", "dps_no_cut_5y",
                      "momentum_12_1", "volatility_1y", "return_12m"}  # fmt: skip


def _pick[T](rng: random.Random, weighted: tuple[tuple[T, float], ...]) -> T:
    return rng.choices([v for v, _ in weighted], weights=[w for _, w in weighted])[0]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _ratio(num: float, den: float) -> float | None:
    return num / den if den > 0 else None


@dataclass
class Company:
    seq: int
    cik: str
    ticker: str
    name: str
    sector: Sector
    sic: int
    exchange: Exchange
    is_foreign: bool
    is_reit: bool
    is_stale: bool
    fye: str
    last_annual: date
    last_quarterly: date


def _sic_ranges() -> dict[str, list[tuple[int, int]]]:
    doc = yaml.safe_load(SECTORS_PATH.read_text())
    out: dict[str, list[tuple[int, int]]] = {}
    for r in doc["ranges"]:
        out.setdefault(r["sector"], []).extend((lo, hi) for lo, hi in r["sic"])
    return out


def _companies(n: int, rng: random.Random) -> list[Company]:
    sic_ranges = _sic_ranges()
    sectors = tuple((s, p[0]) for s, p in SECTOR_PROFILE.items())
    out: list[Company] = []
    for i in range(1, n + 1):
        sector = _pick(rng, sectors)
        lo, hi = rng.choice(sic_ranges.get(sector.value, [(9990, 9999)]))
        is_stale = rng.random() < 0.03
        last_annual = AS_OF - timedelta(
            days=rng.randint(480, 700) if is_stale else rng.randint(20, 360)
        )
        out.append(
            Company(
                seq=i,
                cik=f"{CIK_BASE + i:010d}",
                ticker=f"SYN{i:04d}",
                name=f"Synthetic Co {i:04d}",
                sector=sector,
                sic=rng.randint(lo, hi),
                exchange=_pick(rng, EXCHANGES),
                is_foreign=rng.random() < 0.05,
                is_reit=sector is Sector.REAL_ESTATE and rng.random() < 0.6,
                is_stale=is_stale,
                fye=_pick(rng, FYE),
                last_annual=last_annual,
                last_quarterly=min(AS_OF, last_annual + timedelta(days=rng.randint(80, 280))),
            )
        )
    return out


def _model(c: Company, rng: random.Random) -> dict[str, float | bool | None]:
    """One company's raw values. None here means NEGATIVE_DENOMINATOR (a formula break)."""
    _, gm_mu, om_mu, ev_sales_mu, lev_mu = SECTOR_PROFILE[c.sector]
    g = rng.gauss
    revenue = math.exp(g(math.log(8e8), 1.8))
    growth = _clamp(g(0.08, 0.18), -0.6, 1.5)
    gross_margin = _clamp(g(gm_mu, 0.12), -0.3, 0.95)
    op_margin = _clamp(g(om_mu, 0.12), -1.5, 0.6)
    if c.sector in {Sector.BANKS, Sector.INSURANCE, Sector.CAPITAL_MARKETS}:
        gross_margin = 1.0
    net_margin = op_margin * 0.78 + g(0, 0.03)
    fcf_margin = op_margin * 0.8 + g(0, 0.06)
    dna_rate = _clamp(g(0.05, 0.03), 0.0, 0.3)
    sbc_rate = _clamp(abs(g(0.03, 0.05)), 0.0, 0.6)
    ebit, ni, fcf = revenue * op_margin, revenue * net_margin, revenue * fcf_margin
    ebitda = ebit + revenue * dna_rate
    ev = revenue * math.exp(g(math.log(ev_sales_mu), 0.6))
    net_debt = revenue * g(lev_mu, 0.5)
    market_cap = max(ev - net_debt, revenue * 0.05)
    price = math.exp(g(math.log(40), 1.0))
    total_assets = revenue / _clamp(g(0.8, 0.4), 0.05, 3.0)
    equity = total_assets * g(0.42, 0.2)
    cash = max(0.0, revenue * g(0.18, 0.15))
    current_liab = total_assets * _clamp(g(0.2, 0.08), 0.02, 0.8)
    current_assets = current_liab * _clamp(g(1.6, 0.6), 0.2, 6.0)
    total_debt = max(0.0, net_debt + cash)
    interest = total_debt * _clamp(g(0.05, 0.015), 0.0, 0.15)
    dividends = max(0.0, ni * _clamp(g(0.3, 0.3), 0.0, 1.2)) if rng.random() < 0.45 else 0.0
    buybacks = max(0.0, market_cap * g(0.015, 0.02))
    issued = max(0.0, market_cap * g(0.005, 0.01))
    share_change = _clamp(g(0.01, 0.06), -0.15, 0.8)
    ret_12m = _clamp(g(0.09, 0.4), -0.9, 4.0)
    invested = total_debt + equity - cash
    nwc_ppe = current_assets - cash - current_liab + total_assets * 0.25
    tax = 0.21 if ni <= 0 else _clamp(g(0.2, 0.06), 0.0, 0.35)
    dso = _clamp(g(50, 20), 2, 200)
    dio = _clamp(g(70, 40), 0, 400)
    dpo = _clamp(g(45, 15), 2, 200)

    v: dict[str, float | bool | None] = {
        "price": price,
        "market_cap": market_cap,
        "enterprise_value": ev,
        "revenue_ttm": revenue,
        "avg_dollar_volume_3m": market_cap * math.exp(g(math.log(0.004), 0.9)),
        "pe_ttm": _ratio(market_cap, ni),
        "earnings_yield": ni / market_cap,
        "ev_ebit": _ratio(ev, ebit),
        "ebit_ev": _ratio(ebit, ev),
        "ev_ebitda": _ratio(ev, ebitda),
        "ev_sales": ev / revenue,
        "p_fcf": _ratio(market_cap, fcf),
        "fcf_yield": fcf / market_cap,
        "pb": _ratio(market_cap, equity),
        "dividend_yield": dividends / market_cap,
        "buyback_yield": (buybacks - issued) / market_cap,
        "shareholder_yield": (dividends + buybacks - issued) / market_cap,
        "ncav_to_mcap": (current_assets - (total_assets - equity)) / market_cap,
        "gross_margin": gross_margin,
        "operating_margin": op_margin,
        "ebitda_margin": ebitda / revenue,
        "net_margin": net_margin,
        "fcf_margin": fcf_margin,
        "roe": _ratio(ni, equity),
        "roa": ni / total_assets,
        "roic": None if invested <= 0 else ebit * (1 - tax) / invested,
        "greenblatt_roc": _ratio(ebit, nwc_ppe),
        "cash_conversion": _ratio(fcf / 0.8 + revenue * dna_rate * 0.2, ni),
        "sbc_to_revenue": sbc_rate,
        "fcf_after_sbc_margin": fcf_margin - sbc_rate,
        "revenue_growth_yoy": growth,
        "revenue_cagr_3y": _clamp(growth * 0.8 + g(0, 0.05), -0.5, 1.0),
        "revenue_cagr_5y": _clamp(growth * 0.7 + g(0, 0.05), -0.5, 0.8),
        "eps_growth_yoy": _clamp(g(growth * 1.3, 0.35), -0.95, 5.0) if ni > 0 else None,
        "ebit_growth_yoy": _clamp(g(growth * 1.2, 0.3), -0.95, 5.0) if ebit > 0 else None,
        "fcf_growth_yoy": _clamp(g(growth, 0.45), -0.95, 5.0) if fcf > 0 else None,
        "gross_margin_change_yoy": g(0.0, 0.025),
        "operating_margin_change_yoy": g(0.0, 0.035),
        "share_count_change_yoy": share_change,
        "rule_of_40": growth + fcf_margin,
        "net_debt": net_debt,
        "net_debt_to_ebitda": _ratio(net_debt, ebitda) if ebitda > 0 else None,
        "debt_to_equity": _ratio(total_debt, equity),
        "current_ratio": current_assets / current_liab,
        "quick_ratio": (cash + revenue * dso / 365) / current_liab,
        "interest_coverage": ebit / interest if interest > 0 else None,
        "altman_z": _clamp(g(3.0, 1.8), -5, 15),
        "cash_to_mcap": cash / market_cap,
        "goodwill_to_assets": _clamp(abs(g(0.18, 0.18)), 0.0, 0.9),
        "asset_turnover": revenue / total_assets,
        "dso": dso,
        "dio": dio,
        "dpo": dpo,
        "cash_conversion_cycle": dso + dio - dpo,
        "capex_to_revenue": _clamp(abs(g(0.06, 0.06)), 0.0, 0.8),
        "capex_to_dna": _clamp(abs(g(1.3, 0.6)), 0.0, 8.0),
        "piotroski_f": float(max(0, min(9, round(g(5, 1.8))))),
        "accruals_ratio": (ni - fcf / 0.8) / total_assets,
        "payout_ratio": _ratio(dividends, ni),
        "fcf_payout_ratio": _ratio(dividends, fcf),
        "dps_no_cut_5y": dividends > 0 and rng.random() < 0.7,
        "return_1m": g(ret_12m / 12, 0.08),
        "return_3m": g(ret_12m / 4, 0.14),
        "return_6m": g(ret_12m / 2, 0.22),
        "return_12m": ret_12m,
        "momentum_12_1": ret_12m - g(ret_12m / 12, 0.05),
        "pct_from_52w_high": -_clamp(abs(g(0.15, 0.15)), 0.0, 0.95),
        "volatility_1y": _clamp(g(0.38, 0.18), 0.08, 2.0),
        "days_since_filing": float((AS_OF - c.last_quarterly).days),
    }
    v["_equity"] = equity
    v["_no_interest"] = interest <= 0
    v["_assumed_tax"] = ni <= 0
    v["_interest"] = interest
    return v


def _null_code(metric_id: str, rng: random.Random) -> tuple[NoteCode, str]:
    if metric_id in HISTORY_METRIC_IDS and rng.random() < 0.5:
        return NoteCode.INSUFFICIENT_HISTORY, "Synthetic: not enough history for this metric."
    return NoteCode.MISSING_INPUT, f"Synthetic: a required input for {metric_id} is missing."


def _applicable(m: MetricDefinition, c: Company) -> tuple[NoteCode, str] | None:
    """Returns the n/m note if the metric doesn't apply to this company (§4.5)."""
    scopes: set[ApplicabilityScope] = set()
    if c.sector in SECTOR_SCOPE:
        scopes.add(SECTOR_SCOPE[c.sector])
    if c.is_reit:
        scopes.add(ApplicabilityScope.REITS)
    if c.is_foreign:
        scopes.add(ApplicabilityScope.FOREIGN_FILERS)
    hit = scopes & set(m.applicability.not_meaningful)
    if not hit:
        return None
    if hit == {ApplicabilityScope.FOREIGN_FILERS}:
        return NoteCode.FOREIGN_PRICE_BASIS, "Foreign filer: price basis not comparable until F20."
    return NoteCode.NOT_APPLICABLE_SECTOR, f"Not meaningful for {c.sector.value}."


@dataclass
class SyntheticBuild:
    companies: list[Company]
    values: list[dict[str, float | bool | None]]
    notes: list[dict[str, tuple[NoteCode, str]]]
    flags: list[list[tuple[str, str, dict[str, Any]]]]


def _flag_thresholds() -> dict[str, Any]:
    """The flag rules with their questions rendered, as the real flag engine uses them."""
    return load_rules()


def _flags(v: dict[str, float | bool | None], c: Company) -> list[tuple[str, str, dict[str, Any]]]:
    t = _flag_thresholds()
    out: list[tuple[str, str, dict[str, Any]]] = []

    def num(key: str) -> float | None:
        x = v.get(key)
        return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None

    sc = num("share_count_change_yoy")
    if sc is not None and sc >= t["dilution"]["share_count_change_yoy_gte"]:
        out.append(("dilution", t["dilution"]["question"].replace("{x}", f"{sc:.1%}"),
                    {"share_count_change_yoy": sc}))  # fmt: skip
    gw = num("goodwill_to_assets")
    if gw is not None and gw >= t["goodwill_heavy"]["goodwill_to_assets_gte"]:
        out.append(
            (
                "goodwill_heavy",
                t["goodwill_heavy"]["question"],
                {"goodwill_to_assets": gw},
            )
        )
    ic = num("interest_coverage")
    if ic is not None and ic < t["thin_coverage"]["interest_coverage_lt"]:
        out.append(("thin_coverage", t["thin_coverage"]["question"], {"interest_coverage": ic}))
    eq = num("_equity")
    if eq is not None and eq <= t["negative_equity"]["equity_lte"]:
        out.append(("negative_equity", t["negative_equity"]["question"], {"equity": round(eq)}))
    sbc = num("sbc_to_revenue")
    if sbc is not None and sbc >= t["heavy_sbc"]["sbc_to_revenue_gte"]:
        out.append(("heavy_sbc", t["heavy_sbc"]["question"], {"sbc_to_revenue": sbc}))
    if c.is_stale:
        out.append(("stale_filing", t["stale_filing"]["question"],
                    {"last_annual_date": c.last_annual.isoformat()}))  # fmt: skip
    return out


def generate(n: int, seed: int, registry: MetricRegistry) -> SyntheticBuild:
    rng = random.Random(seed)
    companies = _companies(n, rng)
    all_values: list[dict[str, float | bool | None]] = []
    all_notes: list[dict[str, tuple[NoteCode, str]]] = []
    all_flags: list[list[tuple[str, str, dict[str, Any]]]] = []
    for c in companies:
        raw = _model(c, rng)
        values: dict[str, float | bool | None] = {}
        notes: dict[str, tuple[NoteCode, str]] = {}
        for m in registry:
            if m.id in {"data_coverage", "flag_count"}:
                continue
            nm = _applicable(m, c)
            x = raw.get(m.id)
            if nm is not None:
                values[m.id], notes[m.id] = None, nm
            elif x is None and m.id == "interest_coverage" and raw["_no_interest"]:
                values[m.id] = None
                notes[m.id] = (
                    NoteCode.NO_INTEREST_EXPENSE,
                    f"interest_coverage: interest expense is zero for the TTM to {TTM_END}",
                )
            elif x is None:
                values[m.id] = None
                notes[m.id] = (NoteCode.NEGATIVE_DENOMINATOR, "Denominator ≤ 0: not meaningful.")
            elif rng.random() < RANDOM_NULL_RATE:
                values[m.id], notes[m.id] = None, _null_code(m.id, rng)
            else:
                values[m.id] = _round(x) if isinstance(x, float) else x
        if values.get("roic") is not None and raw["_assumed_tax"]:
            notes["roic"] = (NoteCode.ASSUMED_TAX_RATE, "Pre-tax income ≤ 0: used the 21% rate.")
        if values.get("gross_margin") is not None and rng.random() < 0.15:
            notes["gross_margin"] = (
                NoteCode.DERIVED_INPUT,
                "Gross profit = revenue − cost of revenue.",
            )
        missing_core = sum(1 for code, _ in notes.values() if code is NoteCode.MISSING_INPUT)
        values["data_coverage"] = round(max(0.5, 1.0 - 0.05 * missing_core - rng.random() * 0.1), 2)
        flags = _flags({**raw, **values}, c)
        values["flag_count"] = float(len(flags))
        all_values.append(values)
        all_notes.append(notes)
        all_flags.append(flags)
    return SyntheticBuild(companies, all_values, all_notes, all_flags)


# --- Writing ------------------------------------------------------------------------------------


def _write_table(con: duckdb.DuckDBPyConnection, table: str, df: pl.DataFrame, work: Path) -> None:
    if df.is_empty():
        return
    path = work / f"{table}.parquet"
    df.write_parquet(path)
    con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM read_parquet(?)", [str(path)])


def _company_record(c: Company) -> dict[str, Any]:
    """One `companies` row. The API's company header and the web mocks both read from this."""
    return {
        "cik": c.cik,
        "name": c.name,
        "tickers": [c.ticker],
        "primary_ticker": c.ticker,
        "exchange": c.exchange.value,
        "sic": c.sic,
        "sic_description": f"Synthetic SIC {c.sic}",
        "sector": c.sector.value,
        "state_of_inc": "XX",
        "fiscal_year_end": c.fye,
        "filer_category": "synthetic",
        "kind": Kind.SYNTHETIC.value,
        "is_foreign_filer": c.is_foreign,
        "is_reit": c.is_reit,
        "has_facts": True,
        "taxonomy": "us-gaap",
        # Foreign filers report in non-USD, so FOREIGN_PRICE_BASIS applies (§4.3 rule 13).
        "reporting_currency": ("EUR", "TWD", "JPY")[c.seq % 3] if c.is_foreign else "USD",
        "last_annual_date": c.last_annual,
        "last_quarterly_date": c.last_quarterly,
        "nt_filing_12m": False,
        "fy_end_changed": False,
    }


def write_build(build: SyntheticBuild, registry: MetricRegistry, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    cs = build.companies
    with duckdb.connect(str(db_path)) as con, tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for ddl in BUILD_TABLES.values():
            con.execute(ddl)
        con.execute(metrics_snapshot_ddl(registry))
        con.executemany(
            "INSERT INTO build_meta VALUES (?, ?)",
            [
                ["db_schema_version", str(DB_SCHEMA_VERSION)],
                ["build_id", BUILD_ID],
                ["synthetic", "true"],
                ["created_at", f"{AS_OF.isoformat()}T00:00:00+00:00"],
                ["as_of_fundamentals", f"{AS_OF.isoformat()}T08:00:00+00:00"],
                ["as_of_prices", (AS_OF - timedelta(days=1)).isoformat()],
            ],
        )
        _write_table(con, "companies", pl.DataFrame([_company_record(c) for c in cs]), work)

        snapshot: dict[str, list[Any]] = {
            "cik": [c.cik for c in cs],
            "as_of_fundamentals": [AS_OF] * len(cs),
            "as_of_prices": [AS_OF - timedelta(days=1)] * len(cs),
            "ticker": [c.ticker for c in cs],
            "name": [c.name for c in cs],
            "sector": [c.sector.value for c in cs],
            "kind": [Kind.SYNTHETIC.value] * len(cs),
            "exchange": [c.exchange.value for c in cs],
            "is_foreign_filer": [c.is_foreign for c in cs],
            "is_stale": [c.is_stale for c in cs],
            "has_facts": [True] * len(cs),
        }
        schema: dict[str, Any] = {}
        for m in registry:
            snapshot[m.id] = [v.get(m.id) for v in build.values]
            schema[m.id] = pl.Boolean if m.unit is Unit.BOOL else pl.Float64
        _write_table(con, "metrics_snapshot", pl.DataFrame(snapshot, schema_overrides=schema), work)

        note_rows = [
            (c.cik, mid, code.value, msg)
            for c, notes in zip(cs, build.notes, strict=True)
            for mid, (code, msg) in sorted(notes.items())
        ]
        _write_table(con, "metric_notes", pl.DataFrame(
            note_rows, schema=["cik", "metric_id", "code", "message"], orient="row"
        ), work)  # fmt: skip

        flag_rows = [
            (c.cik, fid, q, json.dumps(ev, sort_keys=True))
            for c, flags in zip(cs, build.flags, strict=True)
            for fid, q, ev in flags
        ]
        _write_table(con, "flags", pl.DataFrame(
            flag_rows, schema=["cik", "flag_id", "question", "evidence"], orient="row"
        ), work)  # fmt: skip

        _write_table(con, "metric_history", _history(build), work)


HISTORY_SHAPE = (("fy", 10, 365), ("ttm", 12, 91))  # basis, points, days between points


def _history_periods() -> dict[str, list[date]]:
    """Period ends per basis, oldest first; the newest is 30 days before AS_OF."""
    return {
        basis: [AS_OF - timedelta(days=30 + k * step) for k in reversed(range(points))]
        for basis, points, step in HISTORY_SHAPE
    }


def _history_series(
    c: Company, v: dict[str, float | bool | None]
) -> dict[str, dict[str, list[float]]]:
    """Per sparkline metric and basis, values oldest first, drifting back from today's value.

    The newest point of every series *is* the headline value (rounded like the mocks), so a
    sparkline's last point always equals the metric shown beside it."""
    rng = random.Random(c.seq)
    out: dict[str, dict[str, list[float]]] = {}
    for mid in HISTORY_METRICS:
        x = v.get(mid)
        if not isinstance(x, float):
            continue
        out[mid] = {}
        for basis, points, _ in HISTORY_SHAPE:
            cur = x
            newest_first: list[float] = []
            for _ in range(points):
                newest_first.append(_round(cur))
                cur = (
                    cur / (1.08 + rng.gauss(0, 0.05))
                    if mid == "revenue_ttm"
                    else cur + rng.gauss(0, 0.02)
                )
            out[mid][basis] = newest_first[::-1]
    return out


def _history(build: SyntheticBuild) -> pl.DataFrame:
    """10 FY points and 12 TTM points per sparkline metric (`_history_series`)."""
    periods = _history_periods()
    rows: list[tuple[str, str, str, date, float | None]] = []
    for c, v in zip(build.companies, build.values, strict=True):
        for mid, by_basis in _history_series(c, v).items():
            for basis, values in by_basis.items():
                rows.extend(
                    (c.cik, mid, basis, end, x)
                    for end, x in zip(periods[basis], values, strict=True)
                )
    return pl.DataFrame(
        rows, schema=["cik", "metric_id", "basis", "period_end", "value"], orient="row"
    )


def _round(x: float) -> float:
    """The precision the web mocks carry; the build stores the same rounded values."""
    return round(x, 6)


def write_pointer(paths: Paths, db_path: Path) -> CurrentPointer:
    pointer = CurrentPointer(
        build_id=BUILD_ID,
        path=str(db_path.relative_to(paths.db_dir)),
        db_schema_version=DB_SCHEMA_VERSION,
        synthetic=True,
        created_at=datetime(AS_OF.year, AS_OF.month, AS_OF.day, tzinfo=UTC),
    )
    tmp = paths.current_pointer.with_suffix(".json.tmp")
    tmp.write_text(pointer.model_dump_json(indent=2) + "\n")
    tmp.replace(paths.current_pointer)
    return pointer


def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2) + b"\n")


def _mock_universe_counts(companies: list[Company]) -> dict[str, Any]:
    """`/api/meta` universe counts for the companies the mocks actually carry, so mock mode
    never reports a universe its screens can't see (principle 6)."""
    by_exchange: dict[str, int] = {}
    for c in companies:
        by_exchange[c.exchange.value] = by_exchange.get(c.exchange.value, 0) + 1
    return {
        "companies": len(companies),
        "by_kind": {Kind.SYNTHETIC.value: len(companies)},
        "by_exchange": by_exchange,
        "foreign_filers": sum(c.is_foreign for c in companies),
        "stale": sum(c.is_stale for c in companies),
    }


def export_mocks(
    build: SyntheticBuild, registry: MetricRegistry, meta: dict[str, Any], out: Path
) -> None:
    """web/mocks for mock mode, from the first MOCK_COMPANIES companies of the build.

    - meta.json, metrics.json: `/api/meta` (universe counts for these companies) and `/api/metrics`.
    - companies.json: one screen-result row per company (every metric, with its null reasons).
    - profiles.json: each company's header, stale flag and flags, exactly as the build has them,
      plus the screen settings the mock's filter logic needs (from config/thresholds.yaml).
    - history.json: sparkline series; period ends are shared, so they're stored once.
    The mock serves these as they are: it never invents a value, a flag or a history point."""
    picked = list(zip(build.companies, build.values, build.notes, build.flags, strict=True))[
        :MOCK_COMPANIES
    ]
    counts = _mock_universe_counts([p[0] for p in picked])
    _dump(out / "meta.json", {**meta, "universe_counts": counts})
    metrics = MetricsResponse(build_id=BUILD_ID, metrics=registry.live())
    _dump(out / "metrics.json", metrics.model_dump(mode="json"))
    rows: list[dict[str, Any]] = []
    profiles: dict[str, Any] = {}
    series: dict[str, Any] = {}
    for c, values, notes, flags in picked:
        row = ResultRow(
            cik=c.cik,
            ticker=c.ticker,
            name=c.name,
            sector=c.sector,
            rank=None,
            rank_score=None,
            factor_contributions={},
            values=dict[str, CellValue](values),
            notes={k: CellNote(code=code, message=msg) for k, (code, msg) in sorted(notes.items())},
        )
        rows.append(row.model_dump(mode="json"))
        record = _company_record(c)
        header = CompanyHeader.model_validate({k: record[k] for k in CompanyHeader.model_fields})
        profiles[c.cik] = {
            "header": header.model_dump(mode="json"),
            "is_stale": c.is_stale,
            "flags": [
                FlagOut(
                    flag_id=FlagId(fid),
                    severity=FlagSeverity(_flag_thresholds()[fid]["severity"]),
                    question=q,
                    evidence=ev,
                ).model_dump(mode="json")
                for fid, q, ev in sorted(flags)
            ],
        }
        series[c.cik] = _history_series(c, values)
    _dump(out / "companies.json", {"build_id": BUILD_ID, "synthetic": True, "rows": rows})
    config = load_screen_config()
    _dump(out / "profiles.json", {
        "build_id": BUILD_ID,
        "synthetic": True,
        "screen_config": {
            "float_tolerance": config.float_tolerance,
            "small_peer_group_min": config.small_peer_group_min,
        },
        "companies": profiles,
    })  # fmt: skip
    periods = {basis: [d.isoformat() for d in ends] for basis, ends in _history_periods().items()}
    # Compact: ~1,200 series, and the file ships in the mock-mode bundle.
    (out / "history.json").write_bytes(
        orjson.dumps({"build_id": BUILD_ID, "periods": periods, "series": series}) + b"\n"
    )


# Screens the browser's screen engine (web/src/lib/screen/engine.ts) must answer exactly as this
# engine does: every preset, plus shapes the presets don't cover.
PARITY_SCREENS: list[dict[str, Any]] = [
    {
        "name": "parity: OR group, between, missing pass, sector percentile",
        "filters": {
            "op": "and",
            "children": [
                {"metric": "roic", "cmp": "gte", "value": 0.1},
                {"metric": "net_debt_to_ebitda", "cmp": "lte", "value": 2, "missing": "pass"},
                {
                    "op": "or",
                    "children": [
                        {"metric": "revenue_growth_yoy", "cmp": "gte", "value": 0.05},
                        {"metric": "fcf_margin", "cmp": "between", "value": [0.05, 0.4]},
                    ],
                },
                {
                    "metric": "operating_margin",
                    "cmp": "pct_rank_gte",
                    "value": 0.5,
                    "within": "sector",
                },
            ],
        },
        "rank": {
            "factors": [{"metric": "roic", "weight": 1}, {"metric": "fcf_yield", "weight": 1}]
        },
    },
    {
        "name": "parity: vs sector median, universe rules, sort",
        "universe": {"market_cap_min": 5e8, "sectors_exclude": ["Banks"], "include_stale": True},
        "filters": {
            "op": "and",
            "children": [
                {"metric": "net_debt", "cmp": "vs_sector_median_lte", "value": 0.8},
                {"metric": "gross_margin", "cmp": "vs_sector_median_gte", "value": 0.02},
                {
                    "metric": "sector",
                    "cmp": "in",
                    "value": ["Technology", "Health Care", "Industrials"],
                },
            ],
        },
        "sort": {"by": "market_cap", "dir": "desc"},
    },
    {
        "name": "parity: rank sum, not_null",
        "filters": {
            "op": "and",
            "children": [
                {"metric": "dividend_yield", "cmp": "not_null"},
                {"metric": "pe_ttm", "cmp": "lt", "value": 25},
            ],
        },
        "rank": {
            "method": "rank_sum",
            "factors": [{"metric": "earnings_yield", "weight": 1}, {"metric": "roic", "weight": 1}],
        },
    },
]


def export_parity(
    build: SyntheticBuild, registry: MetricRegistry, out: Path, n: int = MOCK_COMPANIES
) -> None:
    """web/mocks/parity.json: this engine's answers for the mock's companies (the first `n`), so
    the browser engine is tested against the real one, not against itself."""
    from glint.screen.engine import run_screen  # noqa: PLC0415 (heavy import, export only)
    from glint.screen.presets import load_presets  # noqa: PLC0415

    sub = SyntheticBuild(build.companies[:n], build.values[:n], build.notes[:n], build.flags[:n])
    screens: list[dict[str, Any]] = [
        {**p.screen.model_dump(mode="json", exclude_none=True), "name": f"preset: {pid}"}
        for pid, p in load_presets(registry).items()
    ] + [{"dsl_version": 1, **s} for s in PARITY_SCREENS]
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "parity.duckdb"
        write_build(sub, registry, db)
        with duckdb.connect(str(db), read_only=True) as con:
            for raw in screens:
                screen = Screen.model_validate({**raw, "limit": 1000, "near_misses": True})
                res = run_screen(con, screen, registry).response
                cases.append({
                    "screen": screen.model_dump(mode="json", exclude_none=True),
                    "funnel": [s.model_dump(mode="json", exclude={"label"}) for s in res.funnel],
                    "results": [
                        {"ticker": r.ticker, "rank": r.rank, "rank_score": r.rank_score}
                        for r in res.results
                    ],
                    "near_misses": [
                        {
                            "ticker": m.ticker,
                            "failed_filter_path": m.failed_filter_path,
                            "metric": m.metric,
                            "cmp": m.cmp.value,
                            "value": m.value,
                            "threshold": m.threshold,
                            "distance": m.distance,
                            "note": m.note.code.value if m.note else None,
                        }
                        for m in res.near_misses
                    ],
                })  # fmt: skip
    _dump(out / "parity.json", {"build_id": BUILD_ID, "n": n, "cases": cases})


def run(
    n: int, seed: int, paths: Paths, mocks_dir: Path | None = MOCKS_DIR
) -> tuple[Path, SyntheticBuild]:
    """Build the synthetic DB, point current.json at it, and export the web mocks."""
    from glint.api.routers.meta import meta_from_build  # noqa: PLC0415 (api imports are heavy)

    registry = load_registry(treat_all_as_live=True)
    build = generate(n, seed, registry)
    db_path = paths.build_db(BUILD_ID)
    write_build(build, registry, db_path)
    pointer = write_pointer(paths, db_path)
    if mocks_dir is not None:
        meta = meta_from_build(pointer, db_path).model_dump(mode="json")
        export_mocks(build, registry, meta, mocks_dir)
        export_parity(build, registry, mocks_dir)
    log_event(log, "synthetic_build_done", rows=n, seed=seed, path=str(db_path))
    return db_path, build
