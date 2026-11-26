"""Client-side pacing: at most N calls in any rolling window (Massive free plan: 5 per minute)."""

import time
from collections import deque
from collections.abc import Callable


class Pacer:
    """Blocks before a call until it fits in the rolling window. Clock and sleep are injectable."""

    def __init__(
        self,
        calls: int,
        *,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if calls <= 0:
            raise ValueError("calls must be positive")
        self.calls = calls
        self.window_s = window_s
        self._clock = clock
        self._sleep = sleep
        self._stamps: deque[float] = deque()

    def wait(self) -> float:
        """Reserve one call slot, sleeping first if the window is full. Returns seconds slept."""
        slept = 0.0
        while True:
            now = self._clock()
            while self._stamps and now - self._stamps[0] >= self.window_s:
                self._stamps.popleft()
            if len(self._stamps) < self.calls:
                self._stamps.append(now)
                return slept
            delay = self.window_s - (now - self._stamps[0])
            self._sleep(delay)
            slept += delay

    def penalize(self, seconds: float) -> None:
        """After a 429, treat the whole window as used for `seconds` more."""
        until = self._clock() + seconds - self.window_s
        self._stamps = deque([until] * self.calls)

    @property
    def seconds_per_call(self) -> float:
        return self.window_s / self.calls
