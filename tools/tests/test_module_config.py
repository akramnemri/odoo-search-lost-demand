"""Host tests of addons/website_sale_lost_demand/services/config.py (no Odoo, no Elasticsearch)."""

from __future__ import annotations

import pytest

from services.config import ConfigError, load_config

VALID = {
    "LOST_DEMAND_ES_URL": "http://elasticsearch:9200/",
    "LOST_DEMAND_ES_USERNAME": "odoo_app",
    "LOST_DEMAND_ES_PASSWORD": "fake-value",  # pragma: allowlist secret
}


def test_valid_environment_uses_defaults() -> None:
    config = load_config(VALID)

    assert config.url == "http://elasticsearch:9200"
    assert config.username == "odoo_app"
    assert config.search_timeout == 0.5
    assert config.status_timeout == 2.0
    assert config.breaker_failures == 3


def test_password_never_in_repr() -> None:
    assert "fake-value" not in repr(load_config(VALID))


def test_missing_values_are_all_reported() -> None:
    with pytest.raises(ConfigError) as caught:
        load_config({"LOST_DEMAND_ES_URL": "http://elasticsearch:9200"})

    message = str(caught.value)
    assert "LOST_DEMAND_ES_USERNAME is not set" in message
    assert "LOST_DEMAND_ES_PASSWORD is not set" in message


def test_blank_value_counts_as_missing() -> None:
    with pytest.raises(ConfigError, match="LOST_DEMAND_ES_USERNAME is not set"):
        load_config({**VALID, "LOST_DEMAND_ES_USERNAME": "  "})


@pytest.mark.parametrize("url", ["elasticsearch:9200", "ftp://elasticsearch", "http://"])
def test_bad_url(url: str) -> None:
    with pytest.raises(ConfigError, match="must look like http://host:9200"):
        load_config({**VALID, "LOST_DEMAND_ES_URL": url})


def test_login_inside_url_is_refused_without_echoing_it() -> None:
    url = "http://odoo_app:fake-value@elasticsearch:9200"  # pragma: allowlist secret
    with pytest.raises(ConfigError) as caught:
        load_config({**VALID, "LOST_DEMAND_ES_URL": url})

    assert "must not contain a login" in str(caught.value)
    assert "fake-value" not in str(caught.value)


def test_optional_numbers_override_defaults() -> None:
    config = load_config(
        {**VALID, "LOST_DEMAND_ES_SEARCH_TIMEOUT_MS": "250", "LOST_DEMAND_ES_BREAKER_FAILURES": "5"}
    )

    assert config.search_timeout == 0.25
    assert config.breaker_failures == 5


@pytest.mark.parametrize(
    ("name", "value", "problem"),
    [
        ("LOST_DEMAND_ES_SEARCH_TIMEOUT_MS", "fast", "must be a number"),
        ("LOST_DEMAND_ES_SEARCH_TIMEOUT_MS", "0", "must be at least 1"),
        ("LOST_DEMAND_ES_BREAKER_FAILURES", "-2", "must be at least 1"),
    ],
)
def test_bad_numbers(name: str, value: str, problem: str) -> None:
    with pytest.raises(ConfigError, match=problem):
        load_config({**VALID, name: value})


def test_zero_cache_is_allowed() -> None:
    assert load_config({**VALID, "LOST_DEMAND_ES_HEALTH_CACHE_SECONDS": "0"}).health_cache_seconds == 0
