"""Raw XBRL facts in the `facts_raw` shape, and a reader for companyfacts JSON (fixtures, CLI)."""

from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any, NamedTuple

from glint.contracts.enums import Taxonomy


class Fact(NamedTuple):
    """One row of `facts_raw` for one company. `fy`/`fp` describe the filing, not the period.

    A NamedTuple, not a dataclass: the universe has ~37M facts, and a tuple is built about 4x
    faster than a frozen dataclass (WT-03.md, 2026-11-23). Immutable all the same; copy with
    `_replace`.
    """

    taxonomy: Taxonomy
    tag: str
    unit: str
    start: date | None  # None for instants
    end: date
    val: float
    accn: str
    fy: int | None
    fp: str | None
    form: str
    filed: date


def _date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def facts_from_companyfacts(doc: Mapping[str, Any]) -> Iterator[Fact]:
    """Every fact in a companyfacts document whose taxonomy Glint knows."""
    known = {t.value for t in Taxonomy}
    for taxonomy, tags in doc.get("facts", {}).items():
        if taxonomy not in known:
            continue
        for tag, body in tags.items():
            for unit, rows in body.get("units", {}).items():
                for r in rows:
                    end = _date(r.get("end"))
                    filed = _date(r.get("filed"))
                    if end is None or filed is None or r.get("val") is None:
                        continue
                    yield Fact(
                        taxonomy=Taxonomy(taxonomy),
                        tag=tag,
                        unit=unit,
                        start=_date(r.get("start")),
                        end=end,
                        val=float(r["val"]),
                        accn=str(r["accn"]),
                        fy=r.get("fy"),
                        fp=r.get("fp"),
                        form=str(r.get("form", "")),
                        filed=filed,
                    )
