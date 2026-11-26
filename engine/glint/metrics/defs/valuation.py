"""Valuation (§2.4, price tier) and enterprise value. Yields keep negative numerators; multiples
are n/m when their denominator is ≤ 0."""

from glint.contracts.enums import LineItem as L
from glint.metrics.core import (
    MetricExprs,
    item,
    metric,
    metric_in,
    optional,
    over,
    ratio,
    result,
    shareholder_flow,
)
from glint.metrics.inputs import MRQ, TTM, Slot
from glint.metrics.params import Params


@metric("enterprise_value")
def enterprise_value(p: Params) -> MetricExprs:
    """market_cap + total_debt + preferred + minority_interest − cash − st_investments (MRQ).
    Untagged preferred / minority interest / short-term investments count as none (noted)."""
    mc, debt, cash = metric_in("market_cap"), item(L.TOTAL_DEBT, MRQ), item(L.CASH, MRQ)
    pref, mi = optional(L.PREFERRED, MRQ), optional(L.MINORITY_INTEREST, MRQ)
    sti = optional(L.ST_INVESTMENTS, MRQ)
    ev = mc.value + debt.value + pref.value + mi.value - cash.value - sti.value
    return result(ev, [mc, debt, pref, mi, cash, sti])


def _over_mcap(num: L) -> MetricExprs:
    return ratio(item(num, TTM), metric_in("market_cap"))


def _mcap_over(den: L, slot: Slot = TTM) -> MetricExprs:
    return ratio(metric_in("market_cap"), item(den, slot))


@metric("pe_ttm")
def pe_ttm(p: Params) -> MetricExprs:
    return _mcap_over(L.NET_INCOME)


@metric("earnings_yield")
def earnings_yield(p: Params) -> MetricExprs:
    return _over_mcap(L.NET_INCOME)


@metric("ev_ebit")
def ev_ebit(p: Params) -> MetricExprs:
    return ratio(metric_in("enterprise_value"), item(L.OPERATING_INCOME, TTM))


@metric("ebit_ev")
def ebit_ev(p: Params) -> MetricExprs:
    return ratio(item(L.OPERATING_INCOME, TTM), metric_in("enterprise_value"))


@metric("ev_ebitda")
def ev_ebitda(p: Params) -> MetricExprs:
    return ratio(metric_in("enterprise_value"), item(L.EBITDA, TTM))


@metric("ev_sales")
def ev_sales(p: Params) -> MetricExprs:
    return ratio(metric_in("enterprise_value"), item(L.REVENUE, TTM))


@metric("p_fcf")
def p_fcf(p: Params) -> MetricExprs:
    return _mcap_over(L.FCF)


@metric("fcf_yield")
def fcf_yield(p: Params) -> MetricExprs:
    return _over_mcap(L.FCF)


@metric("pb")
def pb(p: Params) -> MetricExprs:
    return _mcap_over(L.EQUITY, MRQ)


@metric("dividend_yield")
def dividend_yield(p: Params) -> MetricExprs:
    return ratio(shareholder_flow(L.DIVIDENDS_PAID, TTM), metric_in("market_cap"))


@metric("buyback_yield")
def buyback_yield(p: Params) -> MetricExprs:
    bb, si = shareholder_flow(L.BUYBACKS, TTM), shareholder_flow(L.STOCK_ISSUED, TTM)
    mc = metric_in("market_cap")
    return over(bb.value - si.value, [bb, si], mc)


@metric("shareholder_yield")
def shareholder_yield(p: Params) -> MetricExprs:
    d, b = metric_in("dividend_yield"), metric_in("buyback_yield")
    return result(d.value + b.value, [d, b])


@metric("ncav_to_mcap")
def ncav_to_mcap(p: Params) -> MetricExprs:
    ca, tl = item(L.CURRENT_ASSETS, MRQ), item(L.TOTAL_LIABILITIES, MRQ)
    return over(ca.value - tl.value, [ca, tl], metric_in("market_cap"))


@metric("cash_to_mcap")
def cash_to_mcap(p: Params) -> MetricExprs:
    cash, sti = item(L.CASH, MRQ), optional(L.ST_INVESTMENTS, MRQ)
    return over(cash.value + sti.value, [cash, sti], metric_in("market_cap"))
