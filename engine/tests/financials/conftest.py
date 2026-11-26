"""Shared helpers: the committed real SEC fixtures, loaded as facts."""

from functools import cache
from pathlib import Path

import orjson

from glint.financials.concepts import ConceptMap, load_concepts
from glint.financials.facts import Fact, facts_from_companyfacts
from glint.fixtures.sec import FIXTURE_DIR, fixture_name

# Real facts trimmed from SEC companyfacts (share, NI, EPS, revenue, assets tags since 2024) for
# companies outside the Appendix D fixtures, kept for share-count regression tests.
DATA_DIR = Path(__file__).resolve().parent / "share_facts"


@cache
def fixture_facts(ticker: str) -> tuple[Fact, ...]:
    path = FIXTURE_DIR / f"{fixture_name(ticker)}.companyfacts.json"
    return tuple(facts_from_companyfacts(orjson.loads(path.read_bytes())))


@cache
def concepts() -> ConceptMap:
    return load_concepts()
