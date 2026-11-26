"""Efficiency and reinvestment (§2.4). Day counts use the MRQ balance over the TTM flow × 365."""

from glint.contracts.enums import LineItem as L
from glint.metrics.core import (
    MetricExprs,
    average,
    den_le_zero,
    item,
    metric,
    metric_in,
    ratio,
    result,
)
from glint.metrics.inputs import MRQ, TTM
from glint.metrics.params import Params

DAYS = 365


def _days(balance: L, flow: L) -> MetricExprs:
    b, f = item(balance, MRQ), item(flow, TTM)
    return result(b.value / f.value * DAYS, [b, f], [den_le_zero(f)])


@metric("asset_turnover")
def asset_turnover(p: Params) -> MetricExprs:
    return ratio(item(L.REVENUE, TTM), average(L.TOTAL_ASSETS))


@metric("dso")
def dso(p: Params) -> MetricExprs:
    return _days(L.RECEIVABLES, L.REVENUE)


@metric("dio")
def dio(p: Params) -> MetricExprs:
    return _days(L.INVENTORY, L.COST_OF_REVENUE)


@metric("dpo")
def dpo(p: Params) -> MetricExprs:
    return _days(L.ACCOUNTS_PAYABLE, L.COST_OF_REVENUE)


@metric("cash_conversion_cycle")
def cash_conversion_cycle(p: Params) -> MetricExprs:
    s, i, d = metric_in("dso"), metric_in("dio"), metric_in("dpo")
    return result(s.value + i.value - d.value, [s, i, d])


@metric("capex_to_revenue")
def capex_to_revenue(p: Params) -> MetricExprs:
    return ratio(item(L.CAPEX, TTM), item(L.REVENUE, TTM))


@metric("capex_to_dna")
def capex_to_dna(p: Params) -> MetricExprs:
    return ratio(item(L.CAPEX, TTM), item(L.DNA, TTM))
