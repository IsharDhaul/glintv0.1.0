"""Ticker changes from config/ticker_changes.yaml: price history follows the company (CIK).

Bars and splits are stored under the symbol that traded that day. When a company changes ticker
(same CIK), its earlier bars sit under the old symbol, and the new symbol would start with no
history (failing every "needs N sessions" stat). At read time, once a change is effective in the
data (`effective <= as_of`), the old symbol's bars and splits dated before `effective` are
relabelled to the new symbol, and any new-symbol rows dated before `effective` (another security
that used the symbol earlier) are dropped. The old symbol's rows from `effective` on are left
alone: a reused symbol belongs to whoever trades it now. Before the change is effective, nothing
is relabelled, so the old ticker keeps working until the new one trades.
"""

import re
from datetime import date
from pathlib import Path
from typing import Self

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from glint.core.errors import ContractError
from glint.core.settings import REPO_ROOT

TICKER_CHANGES_PATH = REPO_ROOT / "config" / "ticker_changes.yaml"
_CIK = re.compile(r"^\d{10}$")


class TickerChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str
    old: str = Field(min_length=1)  # canonical symbols (`BRK.B` style)
    new: str = Field(min_length=1)
    effective: date  # first session under the new symbol
    name: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    added: date

    @field_validator("cik")
    @classmethod
    def _ten_digits(cls, value: str) -> str:
        if not _CIK.match(value):
            raise ValueError(f"CIK {value!r} must be 10 digits, zero-padded")
        return value

    @model_validator(mode="after")
    def _differs(self) -> Self:
        if self.old == self.new:
            raise ValueError(f"{self.old}: old and new symbols are the same")
        return self


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[TickerChange] = Field(default_factory=list[TickerChange])


def load_ticker_changes(path: Path = TICKER_CHANGES_PATH) -> list[TickerChange]:
    """Changes sorted by effective date (so chains A → B → C apply in order)."""
    if not path.exists():
        return []
    changes = _File.model_validate(yaml.safe_load(path.read_text()) or {}).changes
    seen: set[tuple[str, date]] = set()
    for c in changes:
        if (c.old, c.effective) in seen:
            raise ContractError(f"{path.name}: {c.old} changes twice on {c.effective}")
        seen.add((c.old, c.effective))
    return sorted(changes, key=lambda c: c.effective)


def effective_changes(changes: list[TickerChange], as_of: date | None) -> list[TickerChange]:
    return [] if as_of is None else [c for c in changes if c.effective <= as_of]


def related_symbols(symbols: set[str], changes: list[TickerChange]) -> set[str]:
    """`symbols` plus every earlier symbol whose history feeds them."""
    out = set(symbols)
    for c in reversed(changes):
        if c.new in out:
            out.add(c.old)
    return out


def follow_changes(
    frame: pl.DataFrame, changes: list[TickerChange], date_col: str = "date"
) -> pl.DataFrame:
    """Relabel pre-change rows of each old symbol to the new one (pass effective changes only)."""
    for c in changes:
        before = pl.col(date_col) < c.effective
        frame = frame.filter(~((pl.col("ticker") == c.new) & before)).with_columns(
            pl.when((pl.col("ticker") == c.old) & before)
            .then(pl.lit(c.new))
            .otherwise(pl.col("ticker"))
            .alias("ticker")
        )
    return frame


def renamed_to(symbol: str, changes: list[TickerChange]) -> TickerChange | None:
    """The last change in the chain that retired `symbol` (its `new` is the current symbol);
    None if `symbol` was never renamed. Pass effective changes only."""
    hit = None
    for c in changes:  # sorted by effective date
        if c.old == (hit.new if hit else symbol):
            hit = c
    return hit
