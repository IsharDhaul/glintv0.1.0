"""Multi-class share counts for market cap (§4.3 rule 11), from two places:

- `config/share_classes.yaml` (WT-01's file, read only) `companies`: hand-keyed entries, for a
  company whose classes neither the cover nor a filing quote can supply (none today).
- The cover page: companies.parquet `listed_classes` (`universe/listed_classes.py`), when every
  common class on the latest 10-K/10-Q cover has its own trading symbol (HEI/HEI.A, BRK.A/BRK.B),
  or is an unlisted class that `unlisted_economic` in the same yaml confirms, in the filing's
  words, has the listed class's economics (GOOGL's Class B, HUBG, DUOL): that class is priced at
  the close of the listed class it converts into. A `companies` entry wins for its CIK.
  A cover entry is only made when every class has a close no more than `price_stale_days` old;
  otherwise the company keeps its single-count market cap (logged), rather than turning a value
  into MISSING_INPUT or STALE_DATA.

Market cap for such a company = Σ class shares × that class's own unadjusted close, each class's
shares adjusted for splits between its `as_of` and its price date. A yaml class without bars makes
the cell MISSING_INPUT; the oldest class price drives STALE_DATA.
"""

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from glint.core.log import get_logger, log_event
from glint.ingest.prices.splits import SplitIndex
from glint.universe.listed_classes import (
    SHARE_CLASSES_PATH,
    CoverSymbols,
    ListedClassExclude,
    NonCommonSymbol,
    UnlistedEconomic,
    load_cover_symbols,
    load_unlisted_economic,
)

log = get_logger(__name__)

LISTED_COLUMN = "listed_classes"  # companies.parquet, WT-01


class ShareClass(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    shares_outstanding: float = Field(gt=0)
    as_of: date
    accn: str
    conversion_ratio: float | None = Field(default=None, gt=0)  # None: the filing doesn't say
    reason: str
    label: str | None = None  # how the note names the class when not by `ticker` (unlisted)


class ShareClassEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str
    name: str
    source: str
    keyed_by: str
    classes: list[ShareClass] = Field(min_length=2)
    origin: Literal["config", "cover"] = "config"


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    companies: list[ShareClassEntry]
    unlisted_economic: list[UnlistedEconomic] = []  # read by universe/listed_classes.py
    cover_symbols: list[CoverSymbols] = []  # read by universe/listed_classes.py
    non_common_symbols: list[NonCommonSymbol] = []  # read by metrics/primary.py via compute.py
    cover_excluded: list[ListedClassExclude] = []

    @model_validator(mode="after")
    def _config_only(self) -> "_File":
        if any(e.origin != "config" for e in self.companies):
            raise ValueError("share_classes.yaml: `origin` is set by the loader, not the file")
        return self


def load_share_classes(path: Path = SHARE_CLASSES_PATH) -> dict[str, ShareClassEntry]:
    parsed = _File.model_validate(yaml.safe_load(path.read_text()))
    return {e.cik: e for e in parsed.companies}


def _local(member: str) -> str:
    return member.rsplit(":", maxsplit=1)[-1].removesuffix("Member")


def cover_entries(
    companies: pl.DataFrame,
    priced: set[str],
    unlisted: Mapping[str, UnlistedEconomic] | None = None,
) -> dict[str, ShareClassEntry]:
    """Entries from companies.parquet `listed_classes` for every CIK whose classes all have a
    usable close (`priced` tickers). The others are logged and keep their single-count market
    cap. A record with no cover symbol is an unlisted class confirmed in `unlisted` (default:
    config/share_classes.yaml), priced at its listed class."""
    if LISTED_COLUMN not in companies.columns:
        return {}
    confirmed = load_unlisted_economic() if unlisted is None else unlisted
    keyed_symbols = load_cover_symbols()
    rows = companies.filter(pl.col(LISTED_COLUMN).list.len() >= 2)
    out: dict[str, ShareClassEntry] = {}
    for cik, name, listed in rows.select("cik", "name", LISTED_COLUMN).iter_rows():
        unpriced = [c["ticker"] for c in listed if c["ticker"] not in priced]
        if unpriced:
            log_event(
                log, "share_classes_cover_skipped", cik=cik, no_close=unpriced,
                reason="a cover-listed class has no fresh close: single-count market cap kept",
            )  # fmt: skip
            continue
        first = listed[0]
        source = f"{first['form']} accn {first['accn']}"
        quote = confirmed.get(cik)
        if quote is not None and any(not c["symbol"] for c in listed):
            source += f"; unlisted class economics per {quote.source}, accn {quote.accn}"
        if (keyed := keyed_symbols.get(cik)) is not None:  # the cover XBRL tags no symbol
            source += f"; class symbols per {keyed.source}, accn {keyed.accn}"
        out[cik] = ShareClassEntry(
            cik=cik,
            name=name or "",
            source=source,
            keyed_by="cover page XBRL (dei:EntityCommonStockSharesOutstanding, dei:TradingSymbol)",
            classes=[_cover_class(c) for c in listed],
            origin="cover",
        )
    return out


def _cover_class(c: Mapping[str, Any]) -> ShareClass:
    if c["symbol"]:
        reason, label = f"{c['member']} (cover symbol {c['symbol']})", None
    else:
        reason = f"{c['member']} (unlisted; filing-confirmed same economics): at {c['ticker']}"
        label = f"{_local(c['member'])} (unlisted, at {c['ticker']})"
    return ShareClass(
        ticker=c["ticker"],
        shares_outstanding=c["shares"],
        as_of=c["as_of"],
        accn=c["accn"],
        reason=reason,
        label=label,
    )


def merged_share_classes(
    config: Mapping[str, ShareClassEntry],
    companies: pl.DataFrame,
    stats: pl.DataFrame,
    *,
    as_of_prices: date | None,
    stale_days: int,
) -> dict[str, ShareClassEntry]:
    """Cover entries, then the yaml's on top: a yaml entry wins for its CIK. A cover class is
    priced when its close is at most `stale_days` before the build's price date."""
    priced = {
        t
        for t, c, d in stats.select("ticker", "close", "as_of").iter_rows()
        if c is not None
        and (as_of_prices is None or d is None or (as_of_prices - d).days <= stale_days)
    }
    return {**cover_entries(companies, priced), **config}


SC_SCHEMA = {
    "cik": pl.String,
    "sc_mcap": pl.Float64,
    "sc_price_as_of": pl.Date,
    "sc_missing": pl.String,
    "sc_note": pl.String,
}


def _prefix(e: ShareClassEntry) -> str:
    if e.origin == "cover":
        return f"share classes from the cover page ({e.source}): "
    return f"share classes from config/share_classes.yaml ({e.source}): "


def with_share_classes(
    frame: pl.DataFrame,
    entries: Mapping[str, ShareClassEntry],
    stats: pl.DataFrame,
    splits: pl.DataFrame,
) -> pl.DataFrame:
    """Adds `has_share_classes`, `sc_mcap`, `sc_price_as_of` (oldest class price date),
    `sc_missing` (first class without a price) and `sc_note`."""
    closes = {
        t: (c, d)
        for t, c, d in stats.select("ticker", "close", "as_of").iter_rows()
        if c is not None
    }
    index = SplitIndex(splits)
    rows: list[dict[str, object]] = []
    for cik, e in sorted(entries.items()):
        total, oldest, missing = 0.0, None, None
        parts: list[str] = []
        for c in e.classes:
            if c.ticker not in closes:
                missing = missing or c.ticker
                continue
            close, day = closes[c.ticker]
            ratio = index.split_between(c.ticker, c.as_of, day)
            shares = c.shares_outstanding * (ratio or 1.0)
            total += shares * close
            oldest = day if oldest is None else min(oldest, day)
            split = f" × {ratio:g} split" if ratio else ""
            parts.append(f"{c.label or c.ticker} {c.shares_outstanding:,.0f}{split} × {close:,.2f}")
        rows.append({
            "cik": cik,
            "sc_mcap": None if missing else total,
            "sc_price_as_of": oldest,
            "sc_missing": missing,
            "sc_note": _prefix(e) + " + ".join(parts),
        })  # fmt: skip
    sc = pl.DataFrame(rows, schema=SC_SCHEMA)
    return frame.join(sc, on="cik", how="left").with_columns(
        pl.col("cik").is_in(list(entries)).alias("has_share_classes")
    )
