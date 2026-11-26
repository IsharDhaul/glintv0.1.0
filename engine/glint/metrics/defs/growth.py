"""Growth (§2.4). Year on year compares TTM at the company's TTM end with the TTM about a year
earlier; CAGRs use fiscal years K years apart (a skipped year is INSUFFICIENT_HISTORY)."""

import polars as pl

from glint.contracts.enums import Basis, NoteCode
from glint.contracts.enums import LineItem as L
from glint.metrics.core import Guard, In, MetricExprs, den_le_zero, item, metric, metric_in, result
from glint.metrics.inputs import FY, Q_1Y, TTM, TTM_1Y, Q, Slot
from glint.metrics.params import Params
from glint.metrics.prices import split_adjusted


def _yoy(i: L) -> MetricExprs:
    now, ago = item(i, TTM), item(i, TTM_1Y)
    return result(now.value / ago.value - 1, [now, ago], [den_le_zero(ago)])


def _cagr(years: int) -> MetricExprs:
    end, start = item(L.REVENUE, FY[0]), item(L.REVENUE, FY[years])
    end_ok = Guard(end.value <= 0, NoteCode.NEGATIVE_DENOMINATOR, f"{end.label} ≤ 0")
    return result(
        (end.value / start.value) ** (1 / years) - 1, [end, start], [den_le_zero(start), end_ok]
    )


def _margin_change(num: L) -> MetricExprs:
    n0, r0 = item(num, TTM), item(L.REVENUE, TTM)
    n1, r1 = item(num, TTM_1Y), item(L.REVENUE, TTM_1Y)
    return result(
        n0.value / r0.value - n1.value / r1.value,
        [n0, r0, n1, r1],
        [den_le_zero(r0), den_le_zero(r1)],
    )


@metric("revenue_growth_yoy")
def revenue_growth_yoy(p: Params) -> MetricExprs:
    return _yoy(L.REVENUE)


@metric("revenue_cagr_3y")
def revenue_cagr_3y(p: Params) -> MetricExprs:
    return _cagr(3)


@metric("revenue_cagr_5y")
def revenue_cagr_5y(p: Params) -> MetricExprs:
    return _cagr(5)


@metric("ebit_growth_yoy")
def ebit_growth_yoy(p: Params) -> MetricExprs:
    return _yoy(L.OPERATING_INCOME)


@metric("fcf_growth_yoy")
def fcf_growth_yoy(p: Params) -> MetricExprs:
    return _yoy(L.FCF)


@metric("gross_margin_change_yoy")
def gross_margin_change_yoy(p: Params) -> MetricExprs:
    return _margin_change(L.GROSS_PROFIT)


@metric("operating_margin_change_yoy")
def operating_margin_change_yoy(p: Params) -> MetricExprs:
    return _margin_change(L.OPERATING_INCOME)


@metric("share_count_change_yoy")
def share_count_change_yoy(p: Params) -> MetricExprs:
    """Split-adjusted: the year-ago count × splits between the two counts' filings, so a split
    or reverse split isn't read as issuance or a buyback (`prices.split_adjusted`)."""
    now = item(L.DILUTED_SHARES, Q)
    ago, split = split_adjusted(item(L.DILUTED_SHARES, Q_1Y), now, "share_split__q")
    return result(now.value / ago.value - 1, [now, ago], [den_le_zero(ago)], [split])


@metric("rule_of_40")
def rule_of_40(p: Params) -> MetricExprs:
    g, m = metric_in("revenue_growth_yoy"), metric_in("fcf_margin")
    return result(g.value + m.value, [g, m])


@metric("eps_growth_yoy")
def eps_growth_yoy(p: Params) -> MetricExprs:
    """Computed from TTM net income (user decision): EPS = net_income_ttm / diluted shares for the
    period ending at the TTM end (the quarter's count, or the FY count at a fiscal year end), vs the
    same a year earlier. Preferred dividends are not subtracted (no line item yet). The year-ago
    count is split-adjusted to the latest count's basis (`prices.split_adjusted`)."""
    ni, ni1 = item(L.NET_INCOME, TTM), item(L.NET_INCOME, TTM_1Y)
    sh = _diluted("ttmend", TTM)
    sh1, split = split_adjusted(_diluted("ttmend_1y", TTM_1Y), sh, "share_split__ttmend")
    eps1 = ni1.value / sh1.value
    return result(
        (ni.value / sh.value) / eps1 - 1,
        [ni, sh, ni1, sh1],
        [
            den_le_zero(sh),
            den_le_zero(sh1),
            Guard(eps1 <= 0, NoteCode.NEGATIVE_DENOMINATOR, "EPS a year earlier ≤ 0"),
        ],
        [split],
    )


def _diluted(suffix: str, slot: Slot) -> In:
    """Diluted shares at the TTM end (see `inputs._eps_shares`), with item()'s null reasons."""
    base = item(L.DILUTED_SHARES, slot, label=f"diluted_shares_{slot.name}")
    col = f"diluted_shares__{suffix}"
    derived = pl.col(col + "__d").fill_null(False)
    at_end = Slot(suffix, Basis.Q, slot.end_col)  # the quarter at the TTM end (else the FY)
    return In(
        base.label, pl.col(col), base.code, base.message, derived,
        item=L.DILUTED_SHARES, slot=at_end,
    )  # fmt: skip
