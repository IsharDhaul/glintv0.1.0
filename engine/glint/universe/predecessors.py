"""Successor → predecessor CIK links from config/cik_predecessors.yaml.

A registrant can change CIK while the listed company stays the same (holding-company
reorganizations). The universe keeps one row per *current* CIK; WT-03 reads these links to merge
the predecessor's facts by period, with the successor winning on overlap.
"""

import re
from datetime import date
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from glint.core.errors import ContractError
from glint.core.settings import REPO_ROOT

PREDECESSORS_PATH = REPO_ROOT / "config" / "cik_predecessors.yaml"
_CIK = re.compile(r"^\d{10}$")


class PredecessorLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    successor_cik: str
    predecessor_cik: str
    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    added: date

    @field_validator("successor_cik", "predecessor_cik")
    @classmethod
    def _ten_digits(cls, value: str) -> str:
        if not _CIK.match(value):
            raise ValueError(f"CIK {value!r} must be 10 digits, zero-padded")
        return value

    @model_validator(mode="after")
    def _not_self(self) -> Self:
        if self.successor_cik == self.predecessor_cik:
            raise ValueError("a CIK can't be its own predecessor")
        return self


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    links: list[PredecessorLink] = Field(default_factory=list[PredecessorLink])


def load_predecessors(path: Path = PREDECESSORS_PATH) -> dict[str, PredecessorLink]:
    """successor CIK → link. Rejects duplicates and chains (a predecessor that is also a
    successor, or one predecessor claimed twice): resolve those by hand in the config."""
    links = _File.model_validate(yaml.safe_load(path.read_text()) or {}).links
    by_successor: dict[str, PredecessorLink] = {}
    predecessors: set[str] = set()
    for link in links:
        if link.successor_cik in by_successor:
            raise ContractError(f"{path.name}: successor {link.successor_cik} listed twice")
        if link.predecessor_cik in predecessors:
            raise ContractError(f"{path.name}: predecessor {link.predecessor_cik} claimed twice")
        by_successor[link.successor_cik] = link
        predecessors.add(link.predecessor_cik)
    if chained := predecessors & set(by_successor):
        raise ContractError(f"{path.name}: chained links through {sorted(chained)}; flatten them")
    return by_successor
