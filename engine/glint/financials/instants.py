"""Balance-sheet instants (§4.3 rule 7): the MRQ value and the value about a year earlier. Pure."""

from collections.abc import Mapping
from datetime import date, timedelta

from glint.financials.select import Value


def one_year_before(d: date) -> date:
    """The same calendar day a year earlier (29 Feb → 28 Feb)."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def latest(series: Mapping[date, Value]) -> Value | None:
    """The value at the latest period end (MRQ for instants)."""
    return series[max(series)] if series else None


def nearest(series: Mapping[date, Value], target: date, window_days: int) -> Value | None:
    """The value whose end is nearest `target`, within ±`window_days` (ties → the earlier end)."""
    window = timedelta(days=window_days)
    hits = [e for e in series if abs(e - target) <= window]
    if not hits:
        return None
    return series[min(hits, key=lambda e: (abs(e - target), e))]


def year_ago(series: Mapping[date, Value], end: date, window_days: int) -> Value | None:
    """The instant nearest one year before `end`, for averages (e.g. average equity for ROE)."""
    return nearest(series, one_year_before(end), window_days)


def last_n[T](series: Mapping[date, T], n: int) -> dict[date, T]:
    """The `n` latest entries, oldest first."""
    return {e: series[e] for e in sorted(series)[-n:]} if n > 0 else {}
