"""Merge a predecessor registrant's facts into its successor's (config/cik_predecessors.yaml). Pure.

Merging is by period: wherever the successor reports any value for a line item and period, all
of the predecessor's facts for that line item and period are dropped, so the successor wins on
overlap regardless of which tags each used. Predecessor facts keep their own accessions, so every
value still points at the filing it came from.
"""

from collections.abc import Iterable

from glint.contracts.enums import LineItem
from glint.financials.concepts import ConceptMap
from glint.financials.facts import Fact
from glint.financials.periods import Period, period_of


def merge_predecessor(
    successor: Iterable[Fact], predecessor: Iterable[Fact], concepts: ConceptMap
) -> list[Fact]:
    own = list(successor)
    covered: set[tuple[LineItem, Period]] = {
        (item, period_of(f))
        for f in own
        if (item := concepts.tag_index.get((f.taxonomy, f.tag))) is not None
    }
    inherited = [
        f
        for f in predecessor
        if (item := concepts.tag_index.get((f.taxonomy, f.tag))) is not None
        and (item, period_of(f)) not in covered
    ]
    return own + inherited
