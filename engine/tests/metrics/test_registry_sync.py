"""Step 10: config/metrics.yaml and the metric functions agree both ways."""

from glint.contracts.enums import MetricStatus
from glint.contracts.metrics import load_registry
from glint.metrics.compute import REGISTRY


def test_every_live_metric_has_a_function_and_vice_versa() -> None:
    reg = load_registry()
    live = {m.id for m in reg if m.status is MetricStatus.LIVE}
    assert live == set(REGISTRY)


def test_planned_metrics_are_listed() -> None:
    """Metrics not implemented stay `planned`; today there are none (recorded in WT-06.md)."""
    assert [m.id for m in load_registry() if m.status is MetricStatus.PLANNED] == []
