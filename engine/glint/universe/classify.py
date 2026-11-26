"""Sector, kind and filer flags (WT-01 step 5). Rules come from config, never from code.

- sector: SIC → Glint sector via config/sectors.yaml (narrowest matching range wins), then
  config/sector_overrides.yaml by ticker.
- kind: `spac` / `fund` by SIC (sectors.yaml `kinds`); a blank-SIC registrant is a `fund` if its
  entityType or recent forms say so (`fund_entity_types` / `fund_forms`); `shell` only by override
  (bulk SEC data has no shell signal); `no_common_equity` when no listed ticker is common stock
  (see `no_common_equity_reason`); `operating` otherwise.
- is_reit: the matching sectors.yaml range says `is_reit: true` (SIC 6798).
- is_foreign_filer: the latest annual report is a 20-F or 40-F.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from glint.contracts.enums import Kind, Sector
from glint.core.errors import ContractError
from glint.core.settings import REPO_ROOT
from glint.universe.facts_profile import EquityEvidence
from glint.universe.submissions import FOREIGN_ANNUAL_FORMS, SubmissionRecord
from glint.universe.upc import UpCRule

SECTORS_PATH = REPO_ROOT / "config" / "sectors.yaml"
OVERRIDES_PATH = REPO_ROOT / "config" / "sector_overrides.yaml"


@dataclass(frozen=True)
class SicRange:
    lo: int
    hi: int
    sector: Sector
    is_reit: bool

    @property
    def width(self) -> int:
        return self.hi - self.lo


class Override(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    sector: Sector | None = None
    kind: Kind | None = None
    reason: str = Field(min_length=1)
    # Temporary overrides: after this date the build notes that the override needs a look.
    review_by: date | None = None

    @model_validator(mode="after")
    def _something(self) -> "Override":
        if self.sector is None and self.kind is None:
            raise ValueError(f"override for {self.ticker} sets neither sector nor kind")
        return self


class NoCommonEquityRule(BaseModel):
    """sectors.yaml `no_common_equity`: thresholds for rule B of `no_common_equity_reason`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_cover_shares: float = Field(ge=0)
    per_share_lookback_months: int = Field(gt=0)


@dataclass(frozen=True)
class Rules:
    ranges: list[SicRange]
    default_sector: Sector
    kind_by_sic: dict[int, Kind]
    fund_entity_types: frozenset[str]
    fund_forms: frozenset[str]
    overrides: dict[str, Override]
    no_common_equity: NoCommonEquityRule
    up_c: UpCRule


def _no_common_rule(doc: dict[str, Any], path: Path) -> NoCommonEquityRule:
    if "no_common_equity" not in doc:
        raise ContractError(f"{path.name}: no `no_common_equity` thresholds")
    return NoCommonEquityRule.model_validate(doc["no_common_equity"])


def _up_c_rule(doc: dict[str, Any], path: Path) -> UpCRule:
    if "up_c" not in doc:
        raise ContractError(f"{path.name}: no `up_c` thresholds")
    return UpCRule.model_validate(doc["up_c"])


def load_rules(sectors_path: Path = SECTORS_PATH, overrides_path: Path = OVERRIDES_PATH) -> Rules:
    doc: dict[str, Any] = yaml.safe_load(sectors_path.read_text())
    ranges = [
        SicRange(int(lo), int(hi), Sector(r["sector"]), bool(r.get("is_reit", False)))
        for r in doc["ranges"]
        for lo, hi in r["sic"]
    ]
    kind_by_sic = {int(sic): Kind(k["kind"]) for k in doc.get("kinds", []) for sic in k["sic"]}
    overrides_doc: dict[str, Any] = yaml.safe_load(overrides_path.read_text()) or {}
    raw_overrides: list[dict[str, Any]] = overrides_doc.get("overrides") or []
    overrides: dict[str, Override] = {}
    for item in raw_overrides:
        o = Override.model_validate(item)
        if o.ticker in overrides:
            raise ContractError(f"{overrides_path.name}: {o.ticker} overridden twice")
        overrides[o.ticker] = o
    return Rules(
        ranges=ranges,
        default_sector=Sector(doc.get("default", Sector.UNCLASSIFIED.value)),
        kind_by_sic=kind_by_sic,
        fund_entity_types=frozenset(doc.get("fund_entity_types", [])),
        fund_forms=frozenset(doc.get("fund_forms", [])),
        overrides=overrides,
        no_common_equity=_no_common_rule(doc, sectors_path),
        up_c=_up_c_rule(doc, sectors_path),
    )


def sic_range(sic: int | None, rules: Rules) -> SicRange | None:
    """The narrowest configured range containing `sic` (ties: first listed)."""
    if sic is None:
        return None
    hits = [r for r in rules.ranges if r.lo <= sic <= r.hi]
    return min(hits, key=lambda r: r.width) if hits else None


def months_before(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def no_common_equity_reason(
    *,
    has_common_ticker: bool,
    rec: SubmissionRecord | None,
    evidence: EquityEvidence | None,
    as_of: date,
    rules: Rules,
) -> str | None:
    """Why a CIK has no listed common stock, or None. Two rules, either is enough:

    A. No ticker is common stock: every one is a preferred, warrant, unit or right by symbol.
    B. Tickers look common, but the latest periodic filing's undimensioned cover-page share count
       is ≤ `max_cover_shares` (0 for TVA, NRUC and CHS; 1 for Qwest, owned by Lumen) and no
       diluted EPS or diluted share count has a period end in the last `per_share_lookback_months`.
       Only the latest filing counts: SPG, TAP and FOXA last tagged an undimensioned 0 or 1 years
       ago and now tag by class. A company that reports EPS keeps its kind whatever its count.
    """
    if not has_common_ticker:
        return "kind no_common_equity: no ticker is common stock (preferreds, warrants, units)"
    if rec is None or evidence is None:
        return None
    filings = [f for f in (rec.last_annual, rec.last_quarterly) if f is not None]
    if not filings:
        return None
    latest = max(filings, key=lambda f: (f.filed, f.accn))
    cover = evidence.cover_by_accn.get(latest.accn)
    rule = rules.no_common_equity
    if cover is None or cover > rule.max_cover_shares:
        return None
    since = months_before(as_of, rule.per_share_lookback_months)
    if evidence.last_per_share_end is not None and evidence.last_per_share_end >= since:
        return None
    return (
        f"kind no_common_equity: {latest.form} {latest.accn} cover page reports {cover:,.0f} "
        f"common shares and no diluted EPS or share count since {since}"
    )


@dataclass(frozen=True)
class Classification:
    sector: Sector
    kind: Kind
    is_reit: bool
    is_foreign_filer: bool
    reasons: list[str]


def classify(
    rec: SubmissionRecord,
    tickers: list[str],
    rules: Rules,
    *,
    no_common: str | None = None,
    as_of: date | None = None,
) -> Classification:
    """`no_common` is `no_common_equity_reason`'s result; it applies only to an otherwise
    operating company (a SPAC with only units stays a SPAC)."""
    reasons: list[str] = []
    rng = sic_range(rec.sic, rules)
    sector = rng.sector if rng else rules.default_sector
    is_reit = bool(rng and rng.is_reit)

    if rec.sic is not None and rec.sic in rules.kind_by_sic:
        kind = rules.kind_by_sic[rec.sic]
        reasons.append(f"kind {kind.value}: SIC {rec.sic}")
    elif rec.sic is None and (
        (rec.entity_type or "") in rules.fund_entity_types or rec.recent_forms & rules.fund_forms
    ):
        kind = Kind.FUND
        reasons.append("kind fund: blank SIC with investment-company entity type or forms")
    elif no_common is not None:
        kind = Kind.NO_COMMON_EQUITY
        reasons.append(no_common)
    else:
        kind = Kind.OPERATING

    override = next((rules.overrides[t] for t in tickers if t in rules.overrides), None)
    if override is not None:
        if override.sector is not None:
            sector = override.sector
            reasons.append(f"sector override: {override.reason}")
        if override.kind is not None:
            kind = override.kind
            reasons.append(f"kind override: {override.reason}")
        if override.review_by is not None and as_of is not None and as_of > override.review_by:
            reasons.append(
                f"override for {override.ticker} was due for review by {override.review_by}: "
                "check whether it is still needed"
            )

    is_foreign = rec.last_annual is not None and rec.last_annual.form in FOREIGN_ANNUAL_FORMS
    return Classification(sector, kind, is_reit, is_foreign, reasons)
