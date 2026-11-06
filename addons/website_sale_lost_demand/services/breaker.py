"""Circuit breaker for Elasticsearch calls made on behalf of shoppers.

closed    -> calls go through; `failures` consecutive failures open the circuit.
open      -> calls are refused at once (the caller falls back to Odoo) until `reset_seconds` have passed.
half_open -> exactly one trial call goes through: success closes the circuit, failure opens it again.

Odoo runs several request threads in one process, so the state is guarded by a lock.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import StrEnum


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self, failures: int = 3, reset_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if failures < 1 or reset_seconds <= 0:
            raise ValueError("failures must be >= 1 and reset_seconds > 0")
        self._threshold = failures
        self._reset_seconds = reset_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_running = False

    def _current(self) -> BreakerState:
        # Called with the lock held.
        if self._state is BreakerState.OPEN and self._clock() - self._opened_at >= self._reset_seconds:
            self._state = BreakerState.HALF_OPEN
            self._trial_running = False
        return self._state

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._current()

    def allow_request(self) -> bool:
        """True when the caller may call Elasticsearch now; it must then report the outcome."""
        with self._lock:
            state = self._current()
            if state is BreakerState.CLOSED:
                return True
            if state is BreakerState.HALF_OPEN and not self._trial_running:
                self._trial_running = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._state = BreakerState.CLOSED
            self._failures = 0
            self._trial_running = False

    def record_failure(self) -> bool:
        """Count a failure; True when this failure opened the circuit (log the outage once, not per call)."""
        with self._lock:
            state = self._current()
            self._failures += 1
            if state is BreakerState.HALF_OPEN or self._failures >= self._threshold:
                self._state = BreakerState.OPEN
                self._opened_at = self._clock()
                self._trial_running = False
                return state is not BreakerState.OPEN
            return False
