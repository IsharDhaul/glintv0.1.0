"""Piotroski F-score (Piotroski 2000, latest FY vs prior FY). altman_z lives in `balance`,
greenblatt_roc in `profitability`.

Scaling follows the paper: ROA, CFO and asset turnover use total assets at the *start* of the year
(the prior FY end); leverage is long-term debt over average total assets. "No new shares" compares
diluted weighted shares (FY0 ≤ FY1), FY1 split-adjusted to FY0's basis (`prices.split_adjusted`).
Each test is 1 or 0; the score is null if any input of any test is missing (debt untagged is
MISSING_INPUT, user decision 2026-10-30). The nine parts are written to `metric_history` as
`piotroski_f.<test>` for drill-down.
"""

import polars as pl

from glint.contracts.enums import LineItem as L
from glint.metrics.core import In, Info, MetricExprs, den_le_zero, item, metric, result
from glint.metrics.inputs import FY
from glint.metrics.params import Params
from glint.metrics.prices import split_adjusted

PIOTROSKI_TESTS = (
    "roa_positive",
    "cfo_positive",
    "roa_up",
    "cfo_above_net_income",
    "leverage_down",
    "current_ratio_up",
    "no_new_shares",
    "gross_margin_up",
    "asset_turnover_up",
)


def _inputs() -> dict[str, In]:
    return _inputs_and_split()[0]


def _inputs_and_split() -> tuple[dict[str, In], Info]:
    f0, f1, f2 = FY[0], FY[1], FY[2]
    sh0 = item(L.DILUTED_SHARES, f0)
    sh1, split = split_adjusted(item(L.DILUTED_SHARES, f1), sh0, "share_split__fy")
    return {
        "ni0": item(L.NET_INCOME, f0),
        "ni1": item(L.NET_INCOME, f1),
        "cfo0": item(L.CFO, f0),
        "ta0": item(L.TOTAL_ASSETS, f0),
        "ta1": item(L.TOTAL_ASSETS, f1),
        "ta2": item(L.TOTAL_ASSETS, f2),
        "ltd0": item(L.DEBT_NONCURRENT, f0),
        "ltd1": item(L.DEBT_NONCURRENT, f1),
        "ca0": item(L.CURRENT_ASSETS, f0),
        "ca1": item(L.CURRENT_ASSETS, f1),
        "cl0": item(L.CURRENT_LIABILITIES, f0),
        "cl1": item(L.CURRENT_LIABILITIES, f1),
        "sh0": sh0,
        "sh1": sh1,
        "gp0": item(L.GROSS_PROFIT, f0),
        "gp1": item(L.GROSS_PROFIT, f1),
        "rev0": item(L.REVENUE, f0),
        "rev1": item(L.REVENUE, f1),
    }, split


def _tests() -> dict[str, pl.Expr]:
    v = {k: i.value for k, i in _inputs().items()}
    roa0, roa1 = v["ni0"] / v["ta1"], v["ni1"] / v["ta2"]
    lev0 = v["ltd0"] / ((v["ta0"] + v["ta1"]) / 2)
    lev1 = v["ltd1"] / ((v["ta1"] + v["ta2"]) / 2)
    return {
        "roa_positive": roa0 > 0,
        "cfo_positive": v["cfo0"] > 0,
        "roa_up": roa0 > roa1,
        "cfo_above_net_income": v["cfo0"] > v["ni0"],
        "leverage_down": lev0 < lev1,
        "current_ratio_up": v["ca0"] / v["cl0"] > v["ca1"] / v["cl1"],
        "no_new_shares": v["sh0"] <= v["sh1"],
        "gross_margin_up": v["gp0"] / v["rev0"] > v["gp1"] / v["rev1"],
        "asset_turnover_up": v["rev0"] / v["ta1"] > v["rev1"] / v["ta2"],
    }


def piotroski_parts(p: Params) -> dict[str, pl.Expr]:
    """Each test as 1.0 / 0.0 (null when an input is missing), keyed in PIOTROSKI_TESTS order."""
    return {k: e.cast(pl.Float64) for k, e in _tests().items()}


@metric("piotroski_f")
def piotroski_f(p: Params) -> MetricExprs:
    score = pl.sum_horizontal(*piotroski_parts(p).values())
    i, split = _inputs_and_split()
    dens = [den_le_zero(i[k]) for k in ("ta1", "ta2", "cl0", "cl1", "rev0", "rev1")]
    return result(score, list(i.values()), dens, [split])
