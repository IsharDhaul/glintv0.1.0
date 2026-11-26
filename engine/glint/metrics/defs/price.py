"""Price and momentum (§2.4): WT-02's `price_stats` for the primary ticker. Price return only."""

from glint.metrics.core import MetricExprs, metric, result
from glint.metrics.params import Params
from glint.metrics.prices import price_in


def _stat(stat: str, p: Params) -> MetricExprs:
    s = price_in(stat, p)
    return result(s.value, [s])


@metric("price")
def price(p: Params) -> MetricExprs:
    return _stat("close", p)


@metric("avg_dollar_volume_3m")
def avg_dollar_volume_3m(p: Params) -> MetricExprs:
    return _stat("avg_dollar_volume_3m", p)


@metric("return_1m")
def return_1m(p: Params) -> MetricExprs:
    return _stat("return_1m", p)


@metric("return_3m")
def return_3m(p: Params) -> MetricExprs:
    return _stat("return_3m", p)


@metric("return_6m")
def return_6m(p: Params) -> MetricExprs:
    return _stat("return_6m", p)


@metric("return_12m")
def return_12m(p: Params) -> MetricExprs:
    return _stat("return_12m", p)


@metric("momentum_12_1")
def momentum_12_1(p: Params) -> MetricExprs:
    return _stat("momentum_12_1", p)


@metric("pct_from_52w_high")
def pct_from_52w_high(p: Params) -> MetricExprs:
    return _stat("pct_from_52w_high", p)


@metric("volatility_1y")
def volatility_1y(p: Params) -> MetricExprs:
    return _stat("volatility_1y", p)
