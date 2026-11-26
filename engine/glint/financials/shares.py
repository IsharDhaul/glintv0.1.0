"""Share count for market cap (§4.3 rule 11). Pure.

Priority per date: dei:EntityCommonStockSharesOutstanding (cover page), then
us-gaap:CommonStockSharesOutstanding; the latest date wins. If there's none, or it's older than
the latest diluted weighted-average count by more than `stale_days`, the diluted count is used,
flagged `derived`. Multi-class totals are WT-01/WT-06's (config/share_classes.yaml).

Up-C (companies.parquet `is_up_c`, detected by WT-01 from the filing's own XBRL): the economic
count is every cover-page common class (listed Class A plus the classes paired with exchangeable
units), not Class A alone. `apply_economic_count` puts it in the share series at its cover date,
flagged `derived` (a sum Glint computes from filed counts), with the filing evidence as its input.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from glint.contracts.enums import LineItem
from glint.financials.instants import latest
from glint.financials.periods import Period
from glint.financials.select import Value

if TYPE_CHECKING:
    from glint.financials.normalize import CompanyFinancials

ECONOMIC_LINEAGE = "EntityCommonStockSharesOutstanding (sum of cover-page classes, Up-C)"


def share_count(
    shares: Mapping[date, Value],
    diluted: Mapping[date, Value],
    stale_days: int,
) -> Value | None:
    """The share count to use, dated by `period.end` (`shares_as_of`)."""
    current = latest(shares)
    dil = latest(diluted)
    if dil is None or (
        current is not None and (dil.period.end - current.period.end).days <= stale_days
    ):
        return current
    return Value(
        item=LineItem.SHARES_OUTSTANDING,
        period=Period(end=dil.period.end),
        value=dil.value,
        unit=dil.unit,
        source_tag=None,
        source_accn=dil.source_accn,
        filed=dil.filed,
        first_filed_value=dil.first_filed_value,
        first_filed_date=dil.first_filed_date,
        derived=True,
        inputs=(f"diluted_shares ({dil.source_tag or 'derived'}) {dil.period.label()}",),
    )


@dataclass(frozen=True)
class EconomicCount:
    """An Up-C's economic share count, from companies.parquet (WT-01's cover facts)."""

    shares: float
    as_of: date  # cover-page date
    accn: str
    filed: date
    evidence: str


def economic_value(e: EconomicCount) -> Value:
    return Value(
        item=LineItem.SHARES_OUTSTANDING,
        period=Period(end=e.as_of),
        value=e.shares,
        unit="shares",
        source_tag="EntityCommonStockSharesOutstanding",
        source_accn=e.accn,
        filed=e.filed,
        first_filed_value=e.shares,
        first_filed_date=e.filed,
        derived=True,
        inputs=(f"Up-C economic shares: {e.evidence}",),
        lineage=ECONOMIC_LINEAGE,
    )


def apply_economic_count(cf: "CompanyFinancials", e: EconomicCount | None, stale_days: int) -> None:
    """Use an Up-C's economic count for market cap: it becomes the latest share count (a later
    count can only be the listed class alone, so those are dropped) and the staleness check is
    redone against it. No-op without one."""
    if e is None:
        return
    item = LineItem.SHARES_OUTSTANDING
    kept = {d: v for d, v in cf.instants.get(item, {}).items() if d < e.as_of}
    dropped = len(cf.instants.get(item, {})) - len(kept)
    cf.instants[item] = {**kept, e.as_of: economic_value(e)}
    if dropped:
        cf.warnings.append(
            f"shares_outstanding: Up-C economic count at {e.as_of} replaces {dropped} "
            "listed-class count(s) on or after that date"
        )
    last_balance = cf.balance_sheet_date
    cf.shares_stale = last_balance is not None and (last_balance - e.as_of).days > stale_days
