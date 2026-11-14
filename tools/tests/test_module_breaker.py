"""Host tests of addons/website_sale_lost_demand/services/breaker.py: every state transition."""

from __future__ import annotations

import pytest

from services.breaker import BreakerState, CircuitBreaker


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def breaker(clock: Clock) -> CircuitBreaker:
    return CircuitBreaker(failures=3, reset_seconds=30, clock=clock)


def _open(breaker: CircuitBreaker) -> None:
    for _ in range(3):
        breaker.record_failure()


def test_starts_closed_and_allows(breaker: CircuitBreaker) -> None:
    assert breaker.state is BreakerState.CLOSED
    assert breaker.allow_request()


def test_opens_after_threshold_and_reports_the_opening_once(breaker: CircuitBreaker) -> None:
    assert breaker.record_failure() is False
    assert breaker.record_failure() is False
    assert breaker.record_failure() is True

    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow_request()
    assert breaker.record_failure() is False  # already open: no second warning


def test_success_resets_the_failure_count(breaker: CircuitBreaker) -> None:
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state is BreakerState.CLOSED


def test_half_open_after_reset_time(breaker: CircuitBreaker, clock: Clock) -> None:
    _open(breaker)
    clock.now += 29.9
    assert breaker.state is BreakerState.OPEN

    clock.now += 0.1
    assert breaker.state is BreakerState.HALF_OPEN


def test_half_open_allows_exactly_one_trial(breaker: CircuitBreaker, clock: Clock) -> None:
    _open(breaker)
    clock.now += 30

    assert breaker.allow_request()
    assert not breaker.allow_request()


def test_trial_success_closes(breaker: CircuitBreaker, clock: Clock) -> None:
    _open(breaker)
    clock.now += 30
    breaker.allow_request()
    breaker.record_success()

    assert breaker.state is BreakerState.CLOSED
    assert breaker.allow_request()


def test_trial_failure_reopens_for_a_full_period(breaker: CircuitBreaker, clock: Clock) -> None:
    _open(breaker)
    clock.now += 30
    breaker.allow_request()

    assert breaker.record_failure() is True
    assert breaker.state is BreakerState.OPEN
    clock.now += 29
    assert not breaker.allow_request()
    clock.now += 1
    assert breaker.allow_request()


@pytest.mark.parametrize(("failures", "reset_seconds"), [(0, 30), (3, 0)])
def test_invalid_settings(failures: int, reset_seconds: float) -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(failures=failures, reset_seconds=reset_seconds)
