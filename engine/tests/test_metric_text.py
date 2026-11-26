"""WT-10: every live metric explains itself in plain English (what it tells you, where it misleads)."""

from glint.contracts.enums import MetricStatus
from glint.contracts.metrics import load_registry


def test_every_live_metric_has_tells_you_and_misleads() -> None:
    for m in load_registry():
        if m.status is not MetricStatus.LIVE:
            continue
        assert m.tells_you and m.tells_you.strip(), f"{m.id}: tells_you missing"
        assert m.misleads and m.misleads.strip(), f"{m.id}: misleads missing"


def test_plain_text_is_one_sentence_each() -> None:
    for m in load_registry():
        for text in (m.tells_you, m.misleads):
            if text is None:
                continue
            assert text.endswith("."), f"{m.id}: {text!r}"
            assert ". " not in text, f"{m.id}: one sentence please: {text!r}"
