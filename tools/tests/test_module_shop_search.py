"""Host tests of addons/website_sale_lost_demand/services/shop_search.py: the engine switch and one search
through a real `EsClient` (breaker, deadline) with a fake low-level client."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from services.config import EsConfig
from services.es_client import EsClient, EsUnavailable
from services.query_builder import (
    DEFAULT_ENGINE,
    ES_PLAIN,
    ES_TUNED_STOCK,
    ODOO,
    MalformedResponse,
    SearchFilters,
)
from services.shop_search import (
    ENGINE_HEADER,
    KEY_HEADER,
    EngineChoice,
    SearchOutcome,
    choose_engine,
    search_template_ids,
)

KEY = "a-generated-load-test-key-0123456789"  # pragma: allowlist secret


@pytest.mark.parametrize(
    ("headers", "configured", "expected"),
    [
        ({}, KEY, EngineChoice(DEFAULT_ENGINE, trusted=False)),
        ({ENGINE_HEADER: ODOO}, KEY, EngineChoice(DEFAULT_ENGINE, trusted=False)),  # no key: ignored
        (
            {ENGINE_HEADER: ODOO, KEY_HEADER: "wrong-key-of-some-length"},
            KEY,
            EngineChoice(DEFAULT_ENGINE, False),
        ),
        (
            {ENGINE_HEADER: ODOO, KEY_HEADER: KEY},
            "",
            EngineChoice(DEFAULT_ENGINE, trusted=False),
        ),  # switch off
        ({ENGINE_HEADER: ODOO, KEY_HEADER: ""}, "", EngineChoice(DEFAULT_ENGINE, trusted=False)),
        ({ENGINE_HEADER: ODOO, KEY_HEADER: KEY}, KEY, EngineChoice(ODOO, trusted=True)),
        ({ENGINE_HEADER: " es_plain ", KEY_HEADER: f" {KEY} "}, KEY, EngineChoice(ES_PLAIN, trusted=True)),
        ({ENGINE_HEADER: "es_magic", KEY_HEADER: KEY}, KEY, EngineChoice(DEFAULT_ENGINE, trusted=True)),
        ({KEY_HEADER: KEY}, KEY, EngineChoice(DEFAULT_ENGINE, trusted=True)),
    ],
)
def test_engine_switch_needs_the_key(
    headers: dict[str, str], configured: str, expected: EngineChoice
) -> None:
    assert choose_engine(headers, configured) == expected


def test_outcome_says_who_answered() -> None:
    assert SearchOutcome("shoes", "es_tuned_stock").served_by_elasticsearch
    assert not SearchOutcome("shoes", "odoo").served_by_elasticsearch
    assert not SearchOutcome("shoes", "odoo_fallback", reason="EsUnavailable").served_by_elasticsearch


class FakeError(Exception):
    """Stands for the client's ApiError / TransportError."""


class FakeRaw:
    def __init__(self, answer: Any = None) -> None:
        self.answer = (
            answer if answer is not None else {"took": 4, "hits": {"hits": [{"_id": "5"}, {"_id": "2"}]}}
        )
        self.down = False
        self.hang: threading.Event | None = None
        self.requests: list[dict[str, Any]] = []

    def options(self, request_timeout: float) -> FakeRaw:
        return self

    def search(self, index: str, body: dict[str, Any]) -> Any:
        self.requests.append({"index": index, **body})
        if self.hang is not None:
            self.hang.wait(timeout=5)
        if self.down:
            raise FakeError("ConnectionError: connection refused")
        return self.answer


CONFIG = EsConfig(
    url="http://elasticsearch:9200",
    username="odoo_app",
    password="fake-value",  # pragma: allowlist secret
    search_timeout=0.1,
    breaker_failures=2,
)


def _search(service: EsClient) -> Any:
    return search_template_ids(
        service, "shop-products", ES_PLAIN, "usb cable", SearchFilters(website_id=1), 100
    )


def test_search_returns_ranked_ids_and_took() -> None:
    raw = FakeRaw()
    hits = _search(EsClient(CONFIG, client=raw, errors=(FakeError,)))

    assert hits.ids == (5, 2)
    assert hits.took_ms == 4
    assert raw.requests[0]["index"] == "shop-products"
    assert raw.requests[0]["size"] == 100


def test_down_cluster_opens_the_circuit_then_is_not_called() -> None:
    raw = FakeRaw()
    raw.down = True
    service = EsClient(CONFIG, client=raw, errors=(FakeError,))

    for _ in range(3):
        with pytest.raises(EsUnavailable):
            _search(service)

    assert len(raw.requests) == 2  # the third search was refused by the open circuit, never sent


def test_slow_cluster_gives_up_at_the_deadline() -> None:
    raw = FakeRaw()
    raw.hang = threading.Event()
    service = EsClient(CONFIG, client=raw, errors=(FakeError,))
    started = time.monotonic()
    try:
        with pytest.raises(EsUnavailable, match="DeadlineExceeded"):
            _search(service)
    finally:
        raw.hang.set()

    assert time.monotonic() - started < 1


def test_odd_answer_is_malformed_not_empty() -> None:
    with pytest.raises(MalformedResponse):
        _search(EsClient(CONFIG, client=FakeRaw(answer={"error": "?"}), errors=(FakeError,)))


def test_stock_engine_puts_in_stock_hits_first_after_the_cut() -> None:
    hits = [{"_id": "35", "fields": {"in_stock": [False]}}, {"_id": "7", "fields": {"in_stock": [True]}}]
    raw = FakeRaw(answer={"took": 2, "hits": {"hits": hits}})
    service = EsClient(CONFIG, client=raw, errors=(FakeError,))

    result = search_template_ids(
        service, "shop-products", ES_TUNED_STOCK, "usb", SearchFilters(website_id=1), 2
    )

    assert result.ids == (7, 35)  # the sold-out best match stays among the hits, after the in-stock one
    assert raw.requests[0]["docvalue_fields"] == ["in_stock"]
