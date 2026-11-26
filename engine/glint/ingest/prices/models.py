"""Price data shapes shared by every provider. Prices are tier 2 (market data, labelled)."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily OHLCV bar, **unadjusted** (as traded that day), keyed by Glint's canonical symbol.

    Split adjustment happens at read time from the splits table (see `splits.py`), so a stored
    bar never changes after it is written. Fields a source didn't give are None, never
    filled in.
    """

    ticker: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    vwap: float | None = None


@dataclass(frozen=True, slots=True)
class Split:
    """A share split (or stock dividend) taking effect at the open of `execution_date`.

    `split_to / split_from` new shares per old share: a 4-for-1 split is `split_from=1, split_to=4`.
    """

    ticker: str
    execution_date: date
    split_from: float
    split_to: float
    adjustment_type: str | None = None

    @property
    def ratio(self) -> float:
        return self.split_to / self.split_from
