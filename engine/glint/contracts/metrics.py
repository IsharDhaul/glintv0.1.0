"""Metric definition model and the registry loader for `config/metrics.yaml`."""

import re
from collections.abc import Iterator
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from glint.contracts.enums import (
    ApplicabilityScope,
    Basis,
    Better,
    Category,
    MetricStatus,
    Priority,
    Tier,
    Unit,
)
from glint.core.errors import ContractError
from glint.core.settings import REPO_ROOT

METRIC_ID_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "metrics.yaml"


class Applicability(BaseModel):
    """Where a metric is not meaningful (§4.5). Anything not listed is `ok`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    not_meaningful: list[ApplicabilityScope] = Field(default_factory=list[ApplicabilityScope])
    notes: dict[ApplicabilityScope, str] = Field(default_factory=dict[ApplicabilityScope, str])


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    category: Category
    unit: Unit
    better: Better
    tier: Tier
    priority: Priority
    basis: Basis
    definition: str = Field(min_length=1, description="Formula and null rules, in words")
    inputs: list[str] = Field(
        min_length=1, description="Line items, price fields or other metric ids used"
    )
    applicability: Applicability = Field(default_factory=Applicability)
    status: MetricStatus = MetricStatus.PLANNED
    tells_you: str | None = Field(
        default=None, description="What the metric tells you, in plain words (optional)"
    )
    misleads: str | None = Field(default=None, description="When the metric can mislead (optional)")

    @field_validator("id")
    @classmethod
    def _snake_case(cls, value: str) -> str:
        if not METRIC_ID_RE.match(value):
            raise ValueError(f"metric id {value!r} is not snake_case")
        return value

    @field_validator("unit")
    @classmethod
    def _metric_unit(cls, value: Unit) -> Unit:
        if value is Unit.TEXT:
            raise ValueError("metrics are numeric or bool; 'text' is for categorical fields")
        return value


class MetricRegistry:
    """The loaded registry, in file order.

    `treat_all_as_live=True` is for synthetic builds, where every metric has a value.
    """

    def __init__(self, metrics: list[MetricDefinition], *, treat_all_as_live: bool = False):
        seen: set[str] = set()
        for m in metrics:
            if m.id in seen:
                raise ContractError(f"duplicate metric id {m.id!r} in registry")
            seen.add(m.id)
        self._metrics = {m.id: m for m in metrics}
        self.treat_all_as_live = treat_all_as_live

    def __iter__(self) -> Iterator[MetricDefinition]:
        return iter(self._metrics.values())

    def __len__(self) -> int:
        return len(self._metrics)

    def __contains__(self, metric_id: object) -> bool:
        return metric_id in self._metrics

    def get(self, metric_id: str) -> MetricDefinition | None:
        return self._metrics.get(metric_id)

    def is_live(self, metric_id: str) -> bool:
        m = self._metrics.get(metric_id)
        return m is not None and (self.treat_all_as_live or m.status is MetricStatus.LIVE)

    def live(self) -> list[MetricDefinition]:
        return [m for m in self if self.is_live(m.id)]


class _RegistryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    metrics: list[MetricDefinition]


def load_registry(
    path: Path = DEFAULT_REGISTRY_PATH, *, treat_all_as_live: bool = False
) -> MetricRegistry:
    raw = yaml.safe_load(path.read_text())
    parsed = _RegistryFile.model_validate(raw)
    return MetricRegistry(parsed.metrics, treat_all_as_live=treat_all_as_live)
