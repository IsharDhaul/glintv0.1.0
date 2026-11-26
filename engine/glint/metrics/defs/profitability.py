"""Profitability and returns (§2.4). Flows at the company's common TTM end; balances at MRQ, and
averages are (MRQ + a year earlier) / 2. Every denominator ≤ 0 is n/m (NEGATIVE_DENOMINATOR)."""

from dataclasses import replace

import polars as pl

from glint.contracts.enums import LineItem as L
from glint.contracts.enums import NoteCode
from glint.metrics.core import (
    Guard,
    In,
    Info,
    MetricExprs,
    average,
    den_le_zero,
    item,
    metric,
    optional,
    ratio,
    result,
)
from glint.metrics.inputs import MRQ, MRQ_1Y, TTM, Slot
from glint.metrics.params import Params


def _margin(num: L) -> MetricExprs:
    return ratio(item(num, TTM), item(L.REVENUE, TTM))


@metric("gross_margin")
def gross_margin(p: Params) -> MetricExprs:
    return _margin(L.GROSS_PROFIT)


@metric("operating_margin")
def operating_margin(p: Params) -> MetricExprs:
    return _margin(L.OPERATING_INCOME)


@metric("ebitda_margin")
def ebitda_margin(p: Params) -> MetricExprs:
    return _margin(L.EBITDA)


@metric("net_margin")
def net_margin(p: Params) -> MetricExprs:
    return _margin(L.NET_INCOME)


@metric("fcf_margin")
def fcf_margin(p: Params) -> MetricExprs:
    return _margin(L.FCF)


@metric("roe")
def roe(p: Params) -> MetricExprs:
    return ratio(item(L.NET_INCOME, TTM), average(L.EQUITY))


@metric("roa")
def roa(p: Params) -> MetricExprs:
    return ratio(item(L.NET_INCOME, TTM), average(L.TOTAL_ASSETS))


@metric("cash_conversion")
def cash_conversion(p: Params) -> MetricExprs:
    return ratio(item(L.CFO, TTM), item(L.NET_INCOME, TTM))


@metric("sbc_to_revenue")
def sbc_to_revenue(p: Params) -> MetricExprs:
    return _margin(L.SBC)


@metric("fcf_after_sbc_margin")
def fcf_after_sbc_margin(p: Params) -> MetricExprs:
    fcf, sbc, rev = item(L.FCF, TTM), item(L.SBC, TTM), item(L.REVENUE, TTM)
    return result((fcf.value - sbc.value) / rev.value, [fcf, sbc, rev], [den_le_zero(rev)])


def invested_capital(slot: Slot) -> tuple[pl.Expr, list[In]]:
    """total_debt + equity + minority_interest − cash − st_investments at `slot` (untagged minority
    interest and short-term investments count as none)."""
    debt, eq, cash = item(L.TOTAL_DEBT, slot), item(L.EQUITY, slot), item(L.CASH, slot)
    mi, sti = optional(L.MINORITY_INTEREST, slot), optional(L.ST_INVESTMENTS, slot)
    return debt.value + eq.value + mi.value - cash.value - sti.value, [debt, eq, mi, cash, sti]


@metric("roic")
def roic(p: Params) -> MetricExprs:
    """NOPAT / average invested capital. NOPAT = EBIT × (1 − t), t = income_tax / pretax_income
    clamped to `roic_tax_rate_clamp`; pretax ≤ 0 → the statutory rate (ASSUMED_TAX_RATE)."""
    ebit, pretax = item(L.OPERATING_INCOME, TTM), item(L.PRETAX_INCOME, TTM)
    loss = pretax.value <= 0
    tax = item(L.INCOME_TAX, TTM)
    tax = replace(tax, value=pl.when(loss).then(0.0).otherwise(tax.value))  # unused on a loss
    lo, hi = p.tax_rate_clamp
    t = pl.when(loss).then(p.statutory_tax_rate).otherwise((tax.value / pretax.value).clip(lo, hi))
    ic_now, now_inputs = invested_capital(MRQ)
    ic_ago, ago_inputs = invested_capital(MRQ_1Y)
    avg_ic = (ic_now + ic_ago) / 2
    rate = f"{p.statutory_tax_rate:.0%}"
    return result(
        ebit.value * (1 - t) / avg_ic,
        [ebit, pretax, tax, *now_inputs, *ago_inputs],
        [Guard(avg_ic <= 0, NoteCode.NEGATIVE_DENOMINATOR, "average invested capital ≤ 0")],
        [
            Info(
                loss,
                NoteCode.ASSUMED_TAX_RATE,
                f"pretax income ≤ 0, so NOPAT uses the {rate} statutory rate",
            )
        ],
    )


@metric("greenblatt_roc")
def greenblatt_roc(p: Params) -> MetricExprs:
    """EBIT / (NWC + net PP&E), NWC = (current_assets − cash − st_investments)
    − (current_liabilities − debt_current). Untagged short-term investments and current debt count
    as none."""
    ebit = item(L.OPERATING_INCOME, TTM)
    ca, cash, sti = item(L.CURRENT_ASSETS, MRQ), item(L.CASH, MRQ), optional(L.ST_INVESTMENTS, MRQ)
    cl, dc = item(L.CURRENT_LIABILITIES, MRQ), optional(L.DEBT_CURRENT, MRQ)
    ppe = item(L.PPE_NET, MRQ)
    capital = (ca.value - cash.value - sti.value) - (cl.value - dc.value) + ppe.value
    return result(
        ebit.value / capital,
        [ebit, ca, cash, sti, cl, dc, ppe],
        [Guard(capital <= 0, NoteCode.NEGATIVE_DENOMINATOR, "net working capital + net PP&E ≤ 0")],
    )
