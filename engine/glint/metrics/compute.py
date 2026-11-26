"""Inputs → every registered metric, in registry order, with applicability applied after each.

Registry order lets a metric read an earlier one (`metric_in`): market_cap before pe_ttm,
dividend_yield before shareholder_yield. A metric that reads another inherits its null reason.
"""

from collections.abc import Mapping
from datetime import date

import polars as pl

from glint.contracts.enums import Unit
from glint.contracts.metrics import MetricRegistry
from glint.financials.concepts import ConceptMap, load_concepts
from glint.metrics import defs
from glint.metrics.applicability import apply_applicability, apply_currency, currency_sensitive
from glint.metrics.core import REGISTRY
from glint.metrics.foreign import with_foreign_price_ok
from glint.metrics.inputs import build_inputs, join_prices
from glint.metrics.params import Params
from glint.metrics.prices import add_split_ratios
from glint.metrics.primary import NonCommon, finalize_primary, with_listing_kind
from glint.metrics.share_classes import ShareClassEntry, with_share_classes
from glint.universe.listed_classes import load_non_common_symbols

CATEGORY_MODULES = defs.__all__  # importing `defs` registers every metric function

SPLITS_SCHEMA = {
    "ticker": pl.String,
    "execution_date": pl.Date,
    "split_from": pl.Float64,
    "split_to": pl.Float64,
}


def prepare(
    companies: pl.DataFrame,
    fin: pl.DataFrame,
    stats: pl.DataFrame,
    splits: pl.DataFrame | None,
    concepts: ConceptMap,
    *,
    as_of_fundamentals: date,
    as_of_prices: date | None,
    share_classes: Mapping[str, ShareClassEntry],
    split_confirm_tolerance: float,
    non_common: NonCommon | None = None,
) -> pl.DataFrame:
    """The inputs frame with prices for the final primary ticker, split ratios and eligibility.
    `split_confirm_tolerance` (`Params`): see `prices.confirmed_splits`. `non_common`: symbols
    that are never the primary ticker, `config/share_classes.yaml` `non_common_symbols` if None."""
    non_common = load_non_common_symbols() if non_common is None else non_common
    companies = finalize_primary(companies, stats, non_common)
    frame = join_prices(build_inputs(companies, fin, concepts), stats)
    frame = frame.with_columns(
        pl.lit(as_of_fundamentals, pl.Date).alias("as_of_fundamentals"),
        pl.lit(as_of_prices, pl.Date).alias("as_of_prices"),
    )
    splits = splits if splits is not None else pl.DataFrame(schema=SPLITS_SCHEMA)
    frame = add_split_ratios(frame, splits, fin, split_confirm_tolerance)
    frame = with_foreign_price_ok(frame)
    frame = with_listing_kind(frame, non_common)
    return with_share_classes(frame, share_classes, stats, splits)


AFTER_FLAGS = frozenset({"flag_count"})  # needs the flag engine's output (`n_flags`)


def compute_metrics(
    frame: pl.DataFrame,
    registry: MetricRegistry,
    params: Params,
    *,
    only: frozenset[str] | None = None,
) -> pl.DataFrame:
    """Adds `<id>`, `<id>__code` and `<id>__msg` for every metric that has a function (or just
    `only`). `flag_count` runs only once `n_flags` exists."""
    sensitive = currency_sensitive(registry, load_concepts())
    for m in registry:
        fn = REGISTRY.get(m.id)
        if fn is None or (only is not None and m.id not in only):
            continue
        if m.id in AFTER_FLAGS and "n_flags" not in frame.columns:
            continue
        e = fn(params)
        dtype = pl.Boolean if m.unit is Unit.BOOL else pl.Float64
        frame = frame.with_columns(
            e.value.cast(dtype).alias(m.id),
            e.code.alias(f"{m.id}__code"),
            e.message.alias(f"{m.id}__msg"),
        )
        frame = apply_applicability(frame, m)
        if m.id in sensitive:
            frame = apply_currency(frame, m)
    return frame
