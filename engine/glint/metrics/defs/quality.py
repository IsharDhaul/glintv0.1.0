"""Quality and accounting (§2.4): accruals, payout, the dividend record. Piotroski lives in
`composites`."""

import polars as pl

from glint.contracts.enums import LineItem as L
from glint.metrics.core import (
    MetricExprs,
    average,
    item,
    metric,
    over,
    ratio,
    result,
    shareholder_flow,
)
from glint.metrics.inputs import FY, TTM
from glint.metrics.params import Params


@metric("accruals_ratio")
def accruals_ratio(p: Params) -> MetricExprs:
    ni, cfo, ta = item(L.NET_INCOME, TTM), item(L.CFO, TTM), average(L.TOTAL_ASSETS)
    return over(ni.value - cfo.value, [ni, cfo], ta)


@metric("payout_ratio")
def payout_ratio(p: Params) -> MetricExprs:
    return ratio(shareholder_flow(L.DIVIDENDS_PAID, TTM), item(L.NET_INCOME, TTM))


@metric("fcf_payout_ratio")
def fcf_payout_ratio(p: Params) -> MetricExprs:
    return ratio(shareholder_flow(L.DIVIDENDS_PAID, TTM), item(L.FCF, TTM))


@metric("dps_no_cut_5y")
def dps_no_cut_5y(p: Params) -> MetricExprs:
    """True if declared DPS never fell more than `dps_cut_tolerance` year on year over the last
    `dps_years` fiscal years (fy0 newest)."""
    ds = [item(L.DPS_DECLARED, FY[k]) for k in range(p.dps_years)]
    kept = [
        ds[k].value >= ds[k + 1].value * (1 - p.dps_cut_tolerance) for k in range(p.dps_years - 1)
    ]
    return result(pl.all_horizontal(*kept), ds)
