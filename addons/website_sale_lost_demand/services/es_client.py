"""The module's only door to Elasticsearch: timeouts, a cached cluster status, a circuit breaker.

`elasticsearch` (pinned in the Odoo image, docker/odoo/requirements.txt) is imported only when a real client
is built, so the host tests of this file run without it (they inject a fake low-level client).

- `cluster_status()` feeds the settings page: info, license and health, each with the short status timeout,
  cached for a few seconds. It never raises: an outage is a status, not an error.
- `guarded()` runs one call on behalf of a shopper through the circuit breaker, with the search timeout.
  Any client error becomes `EsUnavailable`, which the caller answers with Odoo's own search (Task 3.3).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol, TypeVar

from .breaker import BreakerState, CircuitBreaker
from .config import EsConfig, load_config

_logger = logging.getLogger(__name__)
T = TypeVar("T")
ERROR_TEXT_LIMIT = 200


class EsUnavailable(Exception):
    """Elasticsearch cannot answer now (down, slow, refusing, or circuit open); fall back."""


@dataclass(frozen=True)
class ClusterStatus:
    reachable: bool
    version: str = ""
    license_type: str = ""
    license_status: str = ""
    health: str = ""  # green, yellow or red
    breaker: str = BreakerState.CLOSED.value
    error: str = ""  # short and safe to show to an administrator: never a password
    checked_at: float = 0.0  # time.time() of the check


class EsService(Protocol):
    """What the Odoo glue needs; tests replace it with a fake (tests/fake_es.py)."""

    def cluster_status(self, refresh: bool = False) -> ClusterStatus: ...


def _body(response: Any) -> Mapping[str, Any]:
    # The real client returns ObjectApiResponse (its JSON in `.body`); fakes return plain dicts.
    body = getattr(response, "body", response)
    return body if isinstance(body, Mapping) else {}


def describe_error(error: Exception) -> str:
    """Class name and the start of the message. The client never puts the password in its messages."""
    text = str(error).strip()
    if len(text) > ERROR_TEXT_LIMIT:
        text = text[:ERROR_TEXT_LIMIT] + "..."
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


class EsClient:
    def __init__(
        self,
        config: EsConfig,
        client: Any = None,
        errors: tuple[type[Exception], ...] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        """`client` and `errors` are for tests; by default the real client and its error classes are used."""
        self.config = config
        self._client = client
        self._errors = errors
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._cached: tuple[float, ClusterStatus] | None = None
        self.breaker = CircuitBreaker(config.breaker_failures, config.breaker_reset_seconds, clock)

    def _raw(self) -> Any:
        with self._lock:
            if self._client is None:
                from elasticsearch import Elasticsearch  # noqa: PLC0415 - see the module docstring

                self._client = Elasticsearch(
                    self.config.url,
                    basic_auth=(self.config.username, self.config.password),
                    request_timeout=self.config.status_timeout,
                    # No hidden retries: a retry doubles the wait of a shopper; callers decide what to do.
                    max_retries=0,
                    retry_on_timeout=False,
                )
            return self._client

    def _client_errors(self) -> tuple[type[Exception], ...]:
        if self._errors is None:
            # ApiError: Elasticsearch answered with an error status (401, 429, 5xx, ...).
            # TransportError: no usable answer (connection refused, DNS failure, timeout, bad JSON).
            from elasticsearch import ApiError, TransportError  # noqa: PLC0415

            self._errors = (ApiError, TransportError)
        return self._errors

    # --- settings page ---

    def cluster_status(self, refresh: bool = False) -> ClusterStatus:
        now = self._clock()
        cached = self._cached
        if not refresh and cached is not None and now - cached[0] < self.config.health_cache_seconds:
            return replace(cached[1], breaker=self.breaker.state.value)
        status = self._fetch_status()
        self._cached = (now, status)
        return status

    def _fetch_status(self) -> ClusterStatus:
        checked_at = self._wall_clock()
        breaker = self.breaker.state.value
        try:
            client = self._raw().options(request_timeout=self.config.status_timeout)
            info = _body(client.info())
            license_info = _body(client.license.get()).get("license", {})
            health = _body(client.cluster.health())
        except self._client_errors() as error:
            return ClusterStatus(
                reachable=False, breaker=breaker, error=describe_error(error), checked_at=checked_at
            )
        return ClusterStatus(
            reachable=True,
            version=str(info.get("version", {}).get("number", "")),
            license_type=str(license_info.get("type", "")),
            license_status=str(license_info.get("status", "")),
            health=str(health.get("status", "")),
            breaker=breaker,
            checked_at=checked_at,
        )

    # --- shopper requests (used from Task 3.3) ---

    def guarded(self, operation: Callable[[Any], T], timeout: float | None = None) -> T:
        """Run `operation(client)` through the circuit breaker; raise EsUnavailable instead of a client error.

        Every client error counts as a failure, including a 4xx: a wrong password or a broken query
        must not hammer the cluster on every shopper request either.
        """
        if not self.breaker.allow_request():
            raise EsUnavailable("circuit open: Elasticsearch failed recently")
        try:
            client = self._raw().options(request_timeout=timeout or self.config.search_timeout)
            result = operation(client)
        except self._client_errors() as error:
            if self.breaker.record_failure():
                _logger.warning("Elasticsearch circuit opened: %s", describe_error(error))
            raise EsUnavailable(describe_error(error)) from error
        self.breaker.record_success()
        return result


_shared: EsClient | None = None
_shared_lock = threading.Lock()


def shared_service(environ: Mapping[str, str] | None = None) -> EsClient:
    """One client per Odoo process, so the status cache and the breaker are shared by every request.

    Raises config.ConfigError when the environment is incomplete.
    """
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = EsClient(load_config(os.environ if environ is None else environ))
        return _shared
