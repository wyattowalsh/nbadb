"""Resilience primitives for the extraction pipeline.

Provides adaptive rate control, circuit breaking, and latency tracking
to protect against cascading failures when calling external APIs.
"""

from __future__ import annotations

import collections
import time

from loguru import logger


class _AdaptiveThrottle:
    """Track success/failure streaks and compute adaptive request rate.

    Backs off by 30% on each failure (down to *min_rate*).  After
    *recovery_threshold* consecutive successes, recovers by 10%
    (up to *base_rate*).
    """

    __slots__ = (
        "_base_rate",
        "_min_rate",
        "_current_rate",
        "_consecutive_success",
        "_recovery_threshold",
    )

    def __init__(
        self,
        base_rate: float,
        min_rate: float = 1.0,
        recovery_threshold: int = 50,
    ) -> None:
        self._base_rate = base_rate
        self._min_rate = min_rate
        self._current_rate = base_rate
        self._consecutive_success = 0
        self._recovery_threshold = recovery_threshold

    def record_success(self) -> float | None:
        """Record success.  Returns new rate if it changed, else ``None``."""
        self._consecutive_success += 1
        if (
            self._consecutive_success >= self._recovery_threshold
            and self._current_rate < self._base_rate
        ):
            old = self._current_rate
            self._current_rate = min(self._base_rate, self._current_rate * 1.1)
            self._consecutive_success = 0
            if abs(self._current_rate - old) > 0.05:
                return self._current_rate
        return None

    def record_failure(self) -> float | None:
        """Record failure.  Returns new rate if it changed, else ``None``."""
        self._consecutive_success = 0
        old = self._current_rate
        self._current_rate = max(self._min_rate, self._current_rate * 0.7)
        if abs(self._current_rate - old) > 0.05:
            return self._current_rate
        return None

    @property
    def current_rate(self) -> float:
        return self._current_rate


class _CircuitBreaker:
    """Per-endpoint circuit breaker — trips after *threshold* consecutive
    failures, preventing further API calls until *recovery_seconds* elapse.

    States:
    - CLOSED: normal operation, calls proceed
    - OPEN:   tripped, calls are rejected immediately
    - HALF-OPEN: after recovery window, one probe call is allowed
    """

    __slots__ = ("_threshold", "_recovery_seconds", "_state", "_half_open_probing")

    def __init__(
        self,
        threshold: int = 10,
        recovery_seconds: float = 120.0,
    ) -> None:
        self._threshold = threshold
        self._recovery_seconds = recovery_seconds
        # state per endpoint: (consecutive_failures, tripped_at_monotonic | None)
        self._state: dict[str, tuple[int, float | None]] = {}
        self._half_open_probing: set[str] = set()

    def is_open(self, endpoint: str) -> bool:
        """Return True if the breaker is tripped and recovery hasn't elapsed."""
        failures, tripped_at = self._state.get(endpoint, (0, None))
        if tripped_at is None:
            # State is cleared, but a probe may still be in flight
            return endpoint in self._half_open_probing
        if time.monotonic() - tripped_at >= self._recovery_seconds:
            # Half-open: allow exactly one probe call through
            if endpoint in self._half_open_probing:
                return True  # another probe is already in flight
            self._half_open_probing.add(endpoint)
            self._state[endpoint] = (self._threshold - 1, None)
            return False
        return True

    def record_success(self, endpoint: str) -> None:
        """Reset the failure counter on success."""
        self._half_open_probing.discard(endpoint)
        if endpoint in self._state:
            self._state[endpoint] = (0, None)

    def record_failure(self, endpoint: str) -> None:
        """Increment failure counter; trip if threshold reached."""
        self._half_open_probing.discard(endpoint)
        failures, _ = self._state.get(endpoint, (0, None))
        failures += 1
        if failures >= self._threshold:
            self._state[endpoint] = (failures, time.monotonic())
            logger.warning(
                "circuit breaker OPEN for '{}' after {} consecutive failures (recovery in {:.0f}s)",
                endpoint,
                failures,
                self._recovery_seconds,
            )
        else:
            self._state[endpoint] = (failures, None)

    def tripped_endpoints(self) -> list[str]:
        """Return list of currently tripped endpoint names."""
        return [
            ep
            for ep, (_, tripped_at) in self._state.items()
            if tripped_at is not None and time.monotonic() - tripped_at < self._recovery_seconds
        ]


class _LatencyTracker:
    """Lightweight per-endpoint latency histogram.

    Stores the last *window_size* latencies and provides percentile queries.
    """

    __slots__ = ("_window_size", "_data")

    def __init__(self, window_size: int = 200) -> None:
        self._window_size = window_size
        self._data: dict[str, collections.deque[float]] = {}

    def record(self, endpoint: str, duration: float) -> None:
        """Record a latency sample."""
        if endpoint not in self._data:
            self._data[endpoint] = collections.deque(maxlen=self._window_size)
        self._data[endpoint].append(duration)

    def percentile(self, endpoint: str, p: float) -> float | None:
        """Return the *p*-th percentile (0–100) latency, or None if no data."""
        buf = self._data.get(endpoint)
        if not buf:
            return None
        s = sorted(buf)
        idx = int(len(s) * p / 100)
        return s[min(idx, len(s) - 1)]

    def summary(self, endpoint: str) -> dict[str, float] | None:
        """Return p50/p95/p99 for an endpoint, or None."""
        if endpoint not in self._data:
            return None
        return {
            "p50": self.percentile(endpoint, 50) or 0.0,
            "p95": self.percentile(endpoint, 95) or 0.0,
            "p99": self.percentile(endpoint, 99) or 0.0,
            "count": float(len(self._data[endpoint])),
        }

    def all_summaries(self) -> dict[str, dict[str, float]]:
        """Return latency summaries for all tracked endpoints."""
        return {ep: s for ep in self._data if (s := self.summary(ep)) is not None}
