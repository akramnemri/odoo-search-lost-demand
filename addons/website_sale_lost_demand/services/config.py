"""Connection settings of the module, read in one place from the container environment.

compose.yaml passes LOST_DEMAND_ES_URL, LOST_DEMAND_ES_USERNAME and LOST_DEMAND_ES_PASSWORD to the `odoo`
service. They are never stored in the Odoo database (docs/ai/01_ARCHITECTURE.md §6.2). The optional
timeouts and breaker settings have defaults; set them in the environment only to experiment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

PREFIX = "LOST_DEMAND_ES_"
REQUIRED = ("URL", "USERNAME", "PASSWORD")
# name -> (default, minimum); every value is a positive number
OPTIONAL_NUMBERS: dict[str, tuple[float, float]] = {
    # Both are hard deadlines, DNS lookup included (es_client.EsClient._within).
    "SEARCH_TIMEOUT_MS": (500, 1),  # one shopper call: short, then fall back to Odoo (docs/ai/02 §3)
    "STATUS_TIMEOUT_MS": (2000, 1),  # the whole status check of the settings page (3 requests)
    "HEALTH_CACHE_SECONDS": (10, 0),  # how long the settings page reuses the last status
    "BREAKER_FAILURES": (3, 1),  # consecutive failures that open the circuit
    "BREAKER_RESET_SECONDS": (30, 1),  # time an open circuit waits before one trial request
}


class ConfigError(ValueError):
    """The environment does not describe a usable Elasticsearch connection; the message says what to fix."""


@dataclass(frozen=True)
class EsConfig:
    url: str
    username: str
    password: str = field(repr=False)  # never in logs or error messages
    search_timeout: float = 0.5  # seconds
    status_timeout: float = 2.0  # seconds
    health_cache_seconds: float = 10.0
    breaker_failures: int = 3
    breaker_reset_seconds: float = 30.0


def _number(environ: Mapping[str, str], name: str, problems: list[str]) -> float:
    default, minimum = OPTIONAL_NUMBERS[name]
    raw = environ.get(PREFIX + name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        problems.append(f"{PREFIX}{name} must be a number, got {raw!r}")
        return default
    if value < minimum:
        problems.append(f"{PREFIX}{name} must be at least {minimum:g}, got {raw!r}")
        return default
    return value


def _check_url(url: str, problems: list[str]) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        problems.append(f"{PREFIX}URL must look like http://host:9200, got {url!r}")
    elif parts.username or parts.password:
        # Credentials belong in USERNAME/PASSWORD: a URL ends up in logs and error messages.
        problems.append(f"{PREFIX}URL must not contain a login; use {PREFIX}USERNAME and {PREFIX}PASSWORD")


def load_config(environ: Mapping[str, str]) -> EsConfig:
    """Build the configuration from environment variables; raise ConfigError listing every problem."""
    problems = [
        f"{PREFIX}{name} is not set" for name in REQUIRED if not environ.get(PREFIX + name, "").strip()
    ]
    url = environ.get(PREFIX + "URL", "").strip()
    if url:
        _check_url(url, problems)
    numbers = {name: _number(environ, name, problems) for name in OPTIONAL_NUMBERS}
    if problems:
        raise ConfigError("; ".join(problems))
    return EsConfig(
        url=url.rstrip("/"),
        username=environ[PREFIX + "USERNAME"].strip(),
        password=environ[PREFIX + "PASSWORD"],
        search_timeout=numbers["SEARCH_TIMEOUT_MS"] / 1000,
        status_timeout=numbers["STATUS_TIMEOUT_MS"] / 1000,
        health_cache_seconds=numbers["HEALTH_CACHE_SECONDS"],
        breaker_failures=int(numbers["BREAKER_FAILURES"]),
        breaker_reset_seconds=numbers["BREAKER_RESET_SECONDS"],
    )
