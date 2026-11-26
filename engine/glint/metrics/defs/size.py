"""Size and liquidity (§2.4). `avg_dollar_volume_3m` lives with the price stats."""

import polars as pl

from glint.contracts.enums import LineItem as L
from glint.contracts.enums import NoteCode
from glint.metrics.core import MetricExprs, item, metric, result
from glint.metrics.inputs import TTM
from glint.metrics.params import Params
from glint.metrics.prices import price_in, shares_in

C = NoteCode


def _by_class(p: Params) -> MetricExprs:
    """Σ class shares × class close, from config/share_classes.yaml or the cover-listed classes
    (see `share_classes`)."""
    days_old = (pl.col("as_of_prices") - pl.col("sc_price_as_of")).dt.total_days()
    missing = pl.col("sc_missing").is_not_null()
    stale = days_old > p.price_stale_days
    code = (
        pl.when(missing).then(pl.lit(C.MISSING_INPUT.value))
        .when(stale).then(pl.lit(C.STALE_DATA.value))
        .otherwise(pl.lit(C.DERIVED_INPUT.value))
    )  # fmt: skip
    msg = (
        pl.when(missing).then(pl.format("close: no price bars for {}", "sc_missing"))
        .when(stale).then(pl.format(
            "close: oldest class price is from {}, {} days before the build's price date",
            pl.col("sc_price_as_of").cast(pl.String), days_old))
        .otherwise(pl.col("sc_note"))
    )  # fmt: skip
    value = pl.when(missing | stale).then(None).otherwise(pl.col("sc_mcap"))
    return MetricExprs(value, code, msg)


@metric("market_cap")
def market_cap(p: Params) -> MetricExprs:
    """Unadjusted close × shares (split-adjusted to the price date; §4.3 rules 11–12), or the
    share-class sum for companies in config/share_classes.yaml or whose every cover-page class is
    separately listed."""
    close = price_in("close", p)
    shares, split = shares_in()
    single = result(close.value * shares.value, [close, shares], infos=[split])
    classes = _by_class(p)
    use = pl.col("has_share_classes").fill_null(False)
    return MetricExprs(
        pl.when(use).then(classes.value).otherwise(single.value),
        pl.when(use).then(classes.code).otherwise(single.code),
        pl.when(use).then(classes.message).otherwise(single.message),
        single.inputs,
    )


@metric("revenue_ttm")
def revenue_ttm(p: Params) -> MetricExprs:
    r = item(L.REVENUE, TTM)
    return result(r.value, [r])
