"""Price-derived stats (SPEC §2.4, "Price and momentum"; `price_stats` table). Pure polars.

All returns are **price-only** (split-adjusted closes, dividends excluded). "N sessions ago"
counts the ticker's own trading days. A stat without enough history is null, and a note row
with `INSUFFICIENT_HISTORY` says how many sessions it needed and had.

| stat                  | definition                                             | needs rows   |
|-----------------------|--------------------------------------------------------|--------------|
| close                 | last unadjusted close (= what traded on `as_of`)        | 1            |
| return_1m/3m/6m/12m   | adj close / adj close 21/63/126/252 sessions ago − 1   | N + 1        |
| momentum_12_1         | adj close 21 ago / adj close 252 ago − 1                | 253          |
| high_52w              | max adj close over the last 252 sessions               | 252          |
| pct_from_52w_high     | adj close / high_52w − 1                               | 252          |
| volatility_1y         | sample stdev of the last 252 daily log returns × √252  | 253          |
| avg_dollar_volume_3m  | mean(close × volume) over the last 63 sessions         | 63           |
|                       | (null, MISSING_INPUT, if any of those volumes is missing)|            |
| history_days          | sessions on disk up to `as_of`                          | —            |
"""

import math
from dataclasses import dataclass
from datetime import date

import polars as pl

from glint.contracts.enums import NoteCode

STAT_COLUMNS = (
    "close",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_12m",
    "momentum_12_1",
    "high_52w",
    "pct_from_52w_high",
    "volatility_1y",
    "avg_dollar_volume_3m",
)


@dataclass(frozen=True)
class Windows:
    """Session counts from the metric definitions (`config/metrics.yaml`). Tests shrink them."""

    m1: int = 21
    m3: int = 63
    m6: int = 126
    m12: int = 252
    high: int = 252
    vol: int = 252
    adv: int = 63
    annualize: int = 252

    def required(self) -> dict[str, int]:
        """Minimum rows each stat needs."""
        return {
            "close": 1,
            "return_1m": self.m1 + 1,
            "return_3m": self.m3 + 1,
            "return_6m": self.m6 + 1,
            "return_12m": self.m12 + 1,
            "momentum_12_1": self.m12 + 1,
            "high_52w": self.high,
            "pct_from_52w_high": self.high,
            "volatility_1y": self.vol + 1,
            "avg_dollar_volume_3m": self.adv,
        }


@dataclass(frozen=True)
class PriceStats:
    stats: pl.DataFrame  # the `price_stats` table: ticker, as_of, STAT_COLUMNS…, history_days
    notes: pl.DataFrame  # ticker, stat, code, message


def _ago(n: int) -> pl.Expr:
    """Adjusted close `n` sessions before the last one (needs n + 1 rows)."""
    return pl.col("adj_close").tail(n + 1).first()


def _if_rows(need: int, expr: pl.Expr) -> pl.Expr:
    return pl.when(pl.len() >= need).then(expr).otherwise(None)


DEFAULT_WINDOWS = Windows()


def price_stats(
    adjusted: pl.DataFrame, as_of: date, windows: Windows = DEFAULT_WINDOWS
) -> PriceStats:
    """Stats per ticker from split-adjusted bars (see `splits.adjust_for_splits`).

    `adjusted` needs ticker, date, close, volume, adj_close. Rows after `as_of` are ignored;
    each ticker's own `as_of` is its last bar on or before it.
    """
    w = windows
    need = w.required()
    last = pl.col("adj_close").last()
    high = pl.col("adj_close").tail(w.high).max()
    stats = (
        adjusted.filter(pl.col("date") <= as_of)
        .sort(["ticker", "date"])
        .group_by("ticker", maintain_order=True)
        .agg(
            pl.col("date").last().alias("as_of"),
            pl.col("close").last().alias("close"),
            _if_rows(need["return_1m"], last / _ago(w.m1) - 1).alias("return_1m"),
            _if_rows(need["return_3m"], last / _ago(w.m3) - 1).alias("return_3m"),
            _if_rows(need["return_6m"], last / _ago(w.m6) - 1).alias("return_6m"),
            _if_rows(need["return_12m"], last / _ago(w.m12) - 1).alias("return_12m"),
            _if_rows(need["momentum_12_1"], _ago(w.m1) / _ago(w.m12) - 1).alias("momentum_12_1"),
            _if_rows(need["high_52w"], high).alias("high_52w"),
            _if_rows(need["pct_from_52w_high"], last / high - 1).alias("pct_from_52w_high"),
            _if_rows(
                need["volatility_1y"],
                pl.col("adj_close").tail(w.vol + 1).log().diff().std(ddof=1)
                * math.sqrt(w.annualize),
            ).alias("volatility_1y"),
            pl.when(pl.col("volume").tail(w.adv).null_count() > 0)
            .then(None)
            .otherwise(
                _if_rows(
                    need["avg_dollar_volume_3m"],
                    (pl.col("close") * pl.col("volume")).tail(w.adv).mean(),
                )
            )
            .alias("avg_dollar_volume_3m"),
            pl.col("volume").tail(w.adv).null_count().alias("_adv_missing_volume"),
            pl.len().cast(pl.Int32).alias("history_days"),
        )
    )
    missing_volume = stats.filter(
        (pl.col("_adv_missing_volume") > 0)
        & (pl.col("history_days") >= need["avg_dollar_volume_3m"])
    ).select(
        "ticker",
        pl.lit("avg_dollar_volume_3m").alias("stat"),
        pl.lit(NoteCode.MISSING_INPUT.value).alias("code"),
        pl.format(
            "avg_dollar_volume_3m: volume missing on {} of the last {} sessions",
            "_adv_missing_volume",
            pl.lit(w.adv),
        ).alias("message"),
    )
    stats = stats.select("ticker", "as_of", *STAT_COLUMNS, "history_days")
    notes = pl.concat(
        [
            missing_volume,
            *(
                stats.filter(pl.col("history_days") < n).select(
                    "ticker",
                    pl.lit(stat).alias("stat"),
                    pl.lit(NoteCode.INSUFFICIENT_HISTORY.value).alias("code"),
                    pl.format(
                        f"{stat} needs {n} sessions of prices; has {{}}", "history_days"
                    ).alias("message"),
                )
                for stat, n in need.items()
            ),
        ]
    ).sort(["ticker", "stat"])
    return PriceStats(stats=stats, notes=notes)
