"""Balance sheet and health (§2.4). Balances at MRQ; flows at the common TTM end."""

from dataclasses import replace

import polars as pl

from glint.contracts.enums import LineItem as L
from glint.contracts.enums import NoteCode
from glint.metrics.core import (
    Guard,
    MetricExprs,
    den_le_zero,
    item,
    metric,
    metric_in,
    optional,
    over,
    ratio,
    result,
)
from glint.metrics.inputs import MRQ, TTM
from glint.metrics.params import Params

C = NoteCode


@metric("current_ratio")
def current_ratio(p: Params) -> MetricExprs:
    return ratio(item(L.CURRENT_ASSETS, MRQ), item(L.CURRENT_LIABILITIES, MRQ))


@metric("interest_coverage")
def interest_coverage(p: Params) -> MetricExprs:
    """EBIT / interest expense. NO_INTEREST_EXPENSE (n/m) only on positive evidence: interest
    expense tagged as zero at the TTM end, or not tagged while total debt at MRQ is tagged as zero.
    An untagged interest expense with debt (or unknown debt) is MISSING_INPUT: most such filers
    report interest under tags Glint doesn't map (InterestPaidNet, InterestExpenseOperating)."""
    ebit, ie = item(L.OPERATING_INCOME, TTM), item(L.INTEREST_EXPENSE, TTM)
    debt = item(L.TOTAL_DEBT, MRQ)
    no_ie = pl.format(
        "interest_coverage: interest expense is zero for the TTM to {}",
        pl.col(TTM.end_col).cast(pl.String),
    )
    no_debt = pl.format(
        "interest_coverage: no debt at {} and no interest expense reported for the TTM to {}",
        pl.col(MRQ.end_col).cast(pl.String),
        pl.col(TTM.end_col).cast(pl.String),
    )
    debt_free = (ie.code == C.MISSING_INPUT.value) & (debt.value == 0)
    ie = replace(
        ie,
        code=pl.when(debt_free).then(pl.lit(C.NO_INTEREST_EXPENSE.value)).otherwise(ie.code),
        message=pl.when(debt_free).then(no_debt).otherwise(ie.message),
    )
    return result(
        ebit.value / ie.value, [ebit, ie], [Guard(ie.value <= 0, C.NO_INTEREST_EXPENSE, no_ie)]
    )


@metric("net_debt")
def net_debt(p: Params) -> MetricExprs:
    """total_debt − cash − st_investments (untagged short-term investments count as none)."""
    debt, cash, sti = item(L.TOTAL_DEBT, MRQ), item(L.CASH, MRQ), optional(L.ST_INVESTMENTS, MRQ)
    return result(debt.value - cash.value - sti.value, [debt, cash, sti])


@metric("net_debt_to_ebitda")
def net_debt_to_ebitda(p: Params) -> MetricExprs:
    """Built from net debt's inputs, not the `net_debt` metric: the ratio is currency-free, while
    `net_debt` itself is a USD amount that the currency rule nulls for non-USD reporters."""
    debt, cash, sti = item(L.TOTAL_DEBT, MRQ), item(L.CASH, MRQ), optional(L.ST_INVESTMENTS, MRQ)
    return over(debt.value - cash.value - sti.value, [debt, cash, sti], item(L.EBITDA, TTM))


@metric("debt_to_equity")
def debt_to_equity(p: Params) -> MetricExprs:
    return ratio(item(L.TOTAL_DEBT, MRQ), item(L.EQUITY, MRQ))


@metric("quick_ratio")
def quick_ratio(p: Params) -> MetricExprs:
    cash, sti = item(L.CASH, MRQ), optional(L.ST_INVESTMENTS, MRQ)
    rec, cl = item(L.RECEIVABLES, MRQ), item(L.CURRENT_LIABILITIES, MRQ)
    return over(cash.value + sti.value + rec.value, [cash, sti, rec], cl)


@metric("goodwill_to_assets")
def goodwill_to_assets(p: Params) -> MetricExprs:
    gw, ia, ta = item(L.GOODWILL, MRQ), item(L.INTANGIBLES, MRQ), item(L.TOTAL_ASSETS, MRQ)
    return over(gw.value + ia.value, [gw, ia], ta)


@metric("altman_z")
def altman_z(p: Params) -> MetricExprs:
    """Altman (1968): 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MktCap/TL + 1.0·Sales/TA.
    Balances at MRQ, EBIT and sales TTM. n/m when TA or TL ≤ 0."""
    ca, cl = item(L.CURRENT_ASSETS, MRQ), item(L.CURRENT_LIABILITIES, MRQ)
    ta, tl = item(L.TOTAL_ASSETS, MRQ), item(L.TOTAL_LIABILITIES, MRQ)
    re, ebit = item(L.RETAINED_EARNINGS, MRQ), item(L.OPERATING_INCOME, TTM)
    sales, mc = item(L.REVENUE, TTM), metric_in("market_cap")
    z = (
        1.2 * (ca.value - cl.value) / ta.value
        + 1.4 * re.value / ta.value
        + 3.3 * ebit.value / ta.value
        + 0.6 * mc.value / tl.value
        + 1.0 * sales.value / ta.value
    )
    return result(z, [ca, cl, ta, tl, re, ebit, sales, mc], [den_le_zero(ta), den_le_zero(tl)])
