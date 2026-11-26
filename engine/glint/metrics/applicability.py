"""The §4.5 applicability matrix (`applicability.not_meaningful` in config/metrics.yaml), applied
after a metric is computed. It overrides the value and any other reason.

Scopes: banks / insurance / capital_markets / utilities by Glint sector, reits by `is_reit`, and
foreign_filers by `is_foreign_filer` unless the filer is eligible for US prices (§4.3 rule 13,
`foreign_price_ok`). A sector scope is checked first: a foreign bank's EV is n/m for the sector.
Foreign scope → FOREIGN_PRICE_BASIS; every other scope → NOT_APPLICABLE_SECTOR.
"""

import polars as pl

from glint.contracts.enums import ApplicabilityScope, NoteCode, Sector, Tier, Unit
from glint.contracts.metrics import MetricDefinition, MetricRegistry
from glint.financials.concepts import ConceptMap, UnitKind
from glint.metrics.core import first

S = ApplicabilityScope

SCOPE_LABEL = {
    S.BANKS: "banks",
    S.INSURANCE: "insurers",
    S.CAPITAL_MARKETS: "capital-markets firms",
    S.REITS: "REITs",
    S.UTILITIES: "utilities",
}


def scope_expr(scope: ApplicabilityScope) -> pl.Expr:
    match scope:
        case S.BANKS:
            return pl.col("sector") == Sector.BANKS.value
        case S.INSURANCE:
            return pl.col("sector") == Sector.INSURANCE.value
        case S.CAPITAL_MARKETS:
            return pl.col("sector") == Sector.CAPITAL_MARKETS.value
        case S.UTILITIES:
            return pl.col("sector") == Sector.UTILITIES.value
        case S.REITS:
            return pl.col("is_reit").fill_null(False)
        case S.FOREIGN_FILERS:
            return pl.col("is_foreign_filer").fill_null(False) & ~pl.col("foreign_price_ok")


def apply_applicability(frame: pl.DataFrame, m: MetricDefinition) -> pl.DataFrame:
    scopes = m.applicability.not_meaningful
    if not scopes:
        return frame
    ordered = [s for s in scopes if s is not S.FOREIGN_FILERS]
    ordered += [s for s in scopes if s is S.FOREIGN_FILERS]
    codes: list[tuple[pl.Expr, pl.Expr]] = []
    msgs: list[tuple[pl.Expr, pl.Expr]] = []
    for s in ordered:
        cond = scope_expr(s)
        if s is S.FOREIGN_FILERS:
            c = pl.lit(NoteCode.FOREIGN_PRICE_BASIS.value)
            t = pl.format(
                f"{m.id}: foreign filer reporting in {{}}; its US listing's price and share basis "
                "may not match the filings (ADR ratio, currency) until F20",
                pl.col("reporting_currency").fill_null("an unknown currency"),
            )
        else:
            c = pl.lit(NoteCode.NOT_APPLICABLE_SECTOR.value)
            t = pl.lit(f"{m.id} is not meaningful for {SCOPE_LABEL[s]} (§4.5)")
        codes.append((cond, c))
        msgs.append((cond, t))
    hit = pl.any_horizontal(*(cond for cond, _ in codes))
    return frame.with_columns(
        pl.when(hit).then(None).otherwise(pl.col(m.id)).alias(m.id),
        first(codes, pl.col(f"{m.id}__code")).alias(f"{m.id}__code"),
        first(msgs, pl.col(f"{m.id}__msg")).alias(f"{m.id}__msg"),
    )


def currency_sensitive(registry: MetricRegistry, concepts: ConceptMap) -> frozenset[str]:
    """Metrics that mix currencies when a filer doesn't report in USD (user decision 2026-10-30,
    principle 7): sec-tier USD amounts, and price-tier metrics that combine the USD price with a
    monetary line item (directly or through another metric). Ratios of two reporting-currency
    amounts (margins, growth) are currency-free and not listed."""
    money = {i.value for i, c in concepts.concepts.items() if c.unit is UnitKind.CURRENCY}

    def uses_money(mid: str, seen: frozenset[str] = frozenset()) -> bool:
        m = registry.get(mid)
        if m is None or mid in seen:
            return False
        return any(i in money or uses_money(i, seen | {mid}) for i in m.inputs)

    out = {m.id for m in registry if m.tier is Tier.SEC and m.unit is Unit.USD}
    out |= {m.id for m in registry if m.tier is Tier.PRICE and uses_money(m.id)}
    return frozenset(out)


def apply_currency(frame: pl.DataFrame, m: MetricDefinition) -> pl.DataFrame:
    """Null a currency-sensitive metric (FOREIGN_PRICE_BASIS) for a non-USD reporter, unless a
    §4.5 scope already explains the cell."""
    other = pl.col("reporting_currency").is_not_null() & (pl.col("reporting_currency") != "USD")
    scoped = pl.col(f"{m.id}__code").is_in(
        [NoteCode.NOT_APPLICABLE_SECTOR.value, NoteCode.FOREIGN_PRICE_BASIS.value]
    )
    hit = other & ~scoped.fill_null(False)
    msg = pl.format(
        f"{m.id}: reported in {{}}, not USD; no FX conversion until F20", "reporting_currency"
    )
    return frame.with_columns(
        pl.when(hit).then(None).otherwise(pl.col(m.id)).alias(m.id),
        pl.when(hit)
        .then(pl.lit(NoteCode.FOREIGN_PRICE_BASIS.value))
        .otherwise(pl.col(f"{m.id}__code"))
        .alias(f"{m.id}__code"),
        pl.when(hit).then(msg).otherwise(pl.col(f"{m.id}__msg")).alias(f"{m.id}__msg"),
    )
