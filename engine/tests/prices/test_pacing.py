import pytest

from glint.ingest.prices.pacing import Pacer
from tests.prices.helpers import FakeClock


def test_five_calls_per_minute_then_waits() -> None:
    clock = FakeClock()
    pacer = Pacer(5, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        assert pacer.wait() == 0
    assert clock.t == 0
    assert pacer.wait() == 60
    assert clock.t == 60


def test_rolling_window_not_fixed_buckets() -> None:
    clock = FakeClock()
    pacer = Pacer(2, clock=clock, sleep=clock.sleep)
    pacer.wait()  # t=0
    clock.t = 30
    pacer.wait()  # t=30
    pacer.wait()  # must wait for the t=0 slot to expire at t=60
    assert clock.t == 60
    pacer.wait()  # next slot is the t=30 one, free at t=90
    assert clock.t == 90


def test_steady_state_rate() -> None:
    clock = FakeClock()
    pacer = Pacer(5, clock=clock, sleep=clock.sleep)
    for _ in range(25):
        pacer.wait()
    # 25 calls at 5/min: the 25th call starts at minute 4.
    assert clock.t == 240
    assert pacer.seconds_per_call == 12


def test_penalize_blocks_for_retry_after() -> None:
    clock = FakeClock()
    pacer = Pacer(5, clock=clock, sleep=clock.sleep)
    pacer.wait()
    clock.t = 10
    pacer.penalize(45)
    assert pacer.wait() == pytest.approx(45)
    assert clock.t == pytest.approx(55)


def test_rejects_zero_rate() -> None:
    with pytest.raises(ValueError):
        Pacer(0)
