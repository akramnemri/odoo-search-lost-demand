"""Host tests of addons/website_sale_lost_demand/services/es_client.py with a fake low-level client."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest

from services.breaker import BreakerState
from services.config import EsConfig
from services.es_client import POOL_WORKERS, ClusterStatus, EsClient, EsUnavailable, describe_error


class FakeTransportError(Exception):
    """Stands for the client's ApiError / TransportError."""


class FakeLicense:
    def __init__(self, owner: FakeRaw) -> None:
        self._owner = owner

    def get(self) -> dict[str, Any]:
        return self._owner.answer("license", {"license": {"type": "basic", "status": "active"}})


class FakeCluster:
    def __init__(self, owner: FakeRaw) -> None:
        self._owner = owner

    def health(self) -> dict[str, Any]:
        return self._owner.answer("health", {"status": "green"})


class FakeRaw:
    """Mimics the parts of `elasticsearch.Elasticsearch` the service uses."""

    def __init__(self) -> None:
        self.down = False
        # Set to an unset Event to make every call hang (like a DNS lookup of a stopped container).
        self.hang: threading.Event | None = None
        self.calls: list[str] = []
        self.timeouts: list[float] = []
        self.license = FakeLicense(self)
        self.cluster = FakeCluster(self)

    def options(self, request_timeout: float) -> FakeRaw:
        self.timeouts.append(request_timeout)
        return self

    def answer(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        if self.hang is not None:
            self.hang.wait(timeout=5)
        if self.down:
            raise FakeTransportError("Connection error caused by: name resolution failed")
        return body

    def info(self) -> dict[str, Any]:
        return self.answer("info", {"version": {"number": "9.5.5"}})


class Clock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


CONFIG = EsConfig(
    url="http://elasticsearch:9200",
    username="odoo_app",
    password="fake-value",  # pragma: allowlist secret
    search_timeout=0.5,
    status_timeout=2.0,
    health_cache_seconds=10,
    breaker_failures=2,
    breaker_reset_seconds=30,
)


@pytest.fixture
def raw() -> FakeRaw:
    return FakeRaw()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(raw: FakeRaw, clock: Clock) -> EsClient:
    return EsClient(CONFIG, client=raw, errors=(FakeTransportError,), clock=clock, wall_clock=lambda: 42.0)


def test_status_of_a_healthy_cluster(service: EsClient, raw: FakeRaw) -> None:
    status = service.cluster_status()

    assert status == ClusterStatus(
        reachable=True,
        version="9.5.5",
        license_type="basic",
        license_status="active",
        health="green",
        breaker="closed",
        checked_at=42.0,
    )
    assert raw.timeouts == [2.0]


def test_status_when_down_never_raises(service: EsClient, raw: FakeRaw) -> None:
    raw.down = True

    status = service.cluster_status()

    assert not status.reachable
    assert status.error.startswith("FakeTransportError: Connection error")
    assert raw.calls == ["info"]  # stops at the first failure: one timeout at most


def test_status_is_cached(service: EsClient, raw: FakeRaw, clock: Clock) -> None:
    service.cluster_status()
    raw.down = True
    clock.now += 9.9

    assert service.cluster_status().reachable
    assert raw.calls.count("info") == 1

    clock.now += 0.1
    assert not service.cluster_status().reachable


def test_refresh_bypasses_the_cache(service: EsClient, raw: FakeRaw) -> None:
    service.cluster_status()
    raw.down = True

    assert not service.cluster_status(refresh=True).reachable


def test_cached_status_shows_the_current_breaker(service: EsClient, raw: FakeRaw) -> None:
    service.cluster_status()
    service.breaker.record_failure()
    service.breaker.record_failure()

    assert service.cluster_status().breaker == "open"


def test_guarded_call_uses_the_search_timeout(service: EsClient, raw: FakeRaw) -> None:
    assert service.guarded(lambda client: client.info())["version"]["number"] == "9.5.5"
    assert raw.timeouts == [0.5]


def test_guarded_failures_open_the_circuit_and_warn_once(
    service: EsClient, raw: FakeRaw, caplog: pytest.LogCaptureFixture
) -> None:
    raw.down = True
    for _ in range(2):
        with pytest.raises(EsUnavailable, match="FakeTransportError"):
            service.guarded(lambda client: client.info())

    assert service.breaker.state is BreakerState.OPEN
    with pytest.raises(EsUnavailable, match="circuit open"):
        service.guarded(lambda client: client.info())
    assert raw.calls == ["info", "info"]  # the open circuit did not call Elasticsearch
    assert [record.getMessage() for record in caplog.records].count(
        "Elasticsearch circuit opened: FakeTransportError: Connection error caused by: name resolution failed"
    ) == 1


def test_guarded_recovers_after_the_reset_time(service: EsClient, raw: FakeRaw, clock: Clock) -> None:
    raw.down = True
    for _ in range(2):
        with pytest.raises(EsUnavailable):
            service.guarded(lambda client: client.info())
    raw.down = False
    clock.now += 30

    service.guarded(lambda client: client.info())

    assert service.breaker.state is BreakerState.CLOSED


def test_unexpected_errors_are_not_swallowed(service: EsClient) -> None:
    def broken(client: Any) -> None:
        raise KeyError("bug in our code")

    with pytest.raises(KeyError):
        service.guarded(broken)


def test_long_error_messages_are_cut() -> None:
    text = describe_error(FakeTransportError("x" * 500))

    assert text.startswith("FakeTransportError: xxx")
    assert text.endswith("...")
    assert len(text) < 250


# --- hard deadline (the client's own timeout does not cover a hanging DNS lookup) ---

FAST = replace(CONFIG, search_timeout=0.05, status_timeout=0.05, breaker_failures=100)


@pytest.fixture
def hanging(raw: FakeRaw) -> Iterator[FakeRaw]:
    raw.hang = threading.Event()
    yield raw
    raw.hang.set()  # let the background calls finish


@pytest.fixture
def fast_service(hanging: FakeRaw) -> EsClient:
    return EsClient(FAST, client=hanging, errors=(FakeTransportError,))


def test_status_returns_after_the_deadline_when_a_call_hangs(fast_service: EsClient) -> None:
    started = time.monotonic()

    status = fast_service.cluster_status()

    assert time.monotonic() - started < 1
    assert not status.reachable
    assert status.error == "DeadlineExceeded: no answer within 0.05 s"


def test_guarded_returns_after_the_deadline_and_counts_a_failure(fast_service: EsClient) -> None:
    started = time.monotonic()

    with pytest.raises(EsUnavailable, match="DeadlineExceeded: no answer within 0.05 s"):
        fast_service.guarded(lambda client: client.info())

    assert time.monotonic() - started < 1
    assert fast_service.breaker._failures == 1


def test_hanging_calls_do_not_pile_up(fast_service: EsClient, hanging: FakeRaw) -> None:
    calls = POOL_WORKERS + 3  # more calls than workers: the extra ones wait in the queue
    started = time.monotonic()

    for _ in range(calls):
        with pytest.raises(EsUnavailable):
            fast_service.guarded(lambda client: client.info())

    assert time.monotonic() - started < calls * 0.05 + 1
    assert len(hanging.calls) <= POOL_WORKERS  # queued calls were cancelled, never sent
