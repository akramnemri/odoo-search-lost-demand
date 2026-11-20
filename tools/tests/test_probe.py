"""`shop probe products` (Task 3.2) without Odoo or Elasticsearch: fake API, fake searches, fake clock."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from shoptools import probe
from shoptools.doctor.system import HttpResponse


class FakeShop:
    """Odoo's JSON-2 calls the probe makes, and the index that becomes searchable `lag` seconds later."""

    def __init__(self, lag: float | None) -> None:
        self.lag = lag  # None: the change never shows
        self.now = 0.0
        self.indexed = {7: {"price": 10.0, "free_qty": 5.0}}
        self.pending: list[tuple[float, int, str, float]] = []
        self.calls: list[tuple[str, str]] = []

    def call(self, model: str, method: str, body: dict[str, Any]) -> Any:
        self.calls.append((model, method))
        if method == "write":
            self._later(body["ids"][0], "price", body["vals"]["list_price"])
        elif method == "create":
            self.quant = body["vals_list"][0]
            return [99]
        elif method == "action_apply_inventory":
            self._later(7, "free_qty", float(self.quant["inventory_quantity"]))
        return None

    def _later(self, template_id: int, field: str, value: float) -> None:
        if self.lag is not None:
            self.pending.append((self.now + self.lag, template_id, field, value))

    def get(self, path: str) -> HttpResponse:
        for due, template_id, field, value in list(self.pending):
            if due <= self.now:
                self.indexed[template_id][field] = value
                self.pending.remove((due, template_id, field, value))
        hits = [{"_source": dict(self.indexed[7])}] if "template_id%3A7" in path else []
        return HttpResponse(200, json.dumps({"hits": {"hits": hits}}))

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


PRODUCT = {"id": 7, "list_price": 10.0, "qty_available": 5.0, "product_variant_id": [70, "Mug"]}


def _probe(shop: FakeShop, kind: str, timeout: float = 120.0) -> probe.Observation:
    return probe.probe_one(shop.call, shop.get, PRODUCT, kind, 8, timeout, shop.clock, shop.sleep)


def test_price_change_is_timed_and_undone() -> None:
    shop = FakeShop(lag=1.5)
    observation = _probe(shop, "price")
    assert (observation.kind, observation.before, observation.after) == ("price", 10.0, 11.0)
    assert observation.delay_seconds == pytest.approx(1.6)  # first poll at or after 1.5 s (0.2 s steps)
    assert shop.indexed[7]["price"] == 10.0  # undone, and the undo awaited
    assert shop.calls == [("product.template", "write"), ("product.template", "write")]


def test_stock_change_uses_an_inventory_adjustment() -> None:
    shop = FakeShop(lag=0.0)
    observation = _probe(shop, "stock")
    assert (observation.before, observation.after, observation.delay_seconds) == (5.0, 4.0, 0.0)
    assert shop.calls.count(("stock.quant", "action_apply_inventory")) == 2  # change and undo
    assert shop.indexed[7]["free_qty"] == 5.0


def test_a_change_that_never_shows_is_a_timeout() -> None:
    observation = _probe(FakeShop(lag=None), "price", timeout=1.0)
    assert observation.delay_seconds is None


def test_a_product_missing_from_the_index_stops_the_probe() -> None:
    with pytest.raises(probe.ProbeError, match="not in shop-products"):
        probe.probe_one(FakeShop(0.0).call, FakeShop(0.0).get, {**PRODUCT, "id": 8}, "price", 8, 1.0)


def test_nearest_rank() -> None:
    values = [float(n) for n in range(1, 31)]  # 1..30
    assert probe.nearest_rank(values, 0.5) == 15.0
    assert probe.nearest_rank(values, 0.95) == 29.0  # ceil(0.95 * 30) = 29th
    assert probe.nearest_rank([3.0], 0.95) == 3.0
    assert math.isnan(probe.nearest_rank([], 0.5))


def test_summary_counts_timeouts_and_renders_a_table() -> None:
    observations = [
        probe.Observation(1, "price", 1.0, 2.0, 0.1, 1.2),
        probe.Observation(2, "stock", 5.0, 4.0, 0.2, 2.4),
        probe.Observation(3, "price", 1.0, 2.0, 0.1, None),
    ]
    stats = probe.summarize(observations)
    assert stats["changes"] == 3
    assert (stats["visible"], stats["timeouts"], stats["within_target"]) == (2, 1, 2)
    assert (stats["p50"], stats["p95"], stats["max"]) == (1.2, 2.4, 2.4)
    assert (stats["price_p50"], stats["stock_p50"]) == (1.2, 2.4)
    meta = {
        "run_id": "probe-products-20261120T120000Z",
        "git": "a" * 40 + "-dirty",
        "start": "2026-11-20T12:00:00Z",
        "seed": 20261025,
        "timeout": 120.0,
        "database": "shop",
        "index": "shop-products-v5",
        "machine": "Windows AMD64",
    }
    table = probe.render_summary(meta, stats)
    assert "| 3 | 2 | 1 | 1.20 s | 2.40 s | 2.40 s | 2 | 1.20 s | 2.40 s |" in table
    assert "(git aaaaaaa-dirty)" in table
    assert "synthetic" in table


def test_product_draw_is_seeded() -> None:
    ids = list(range(1, 101))

    def call(model: str, method: str, body: dict[str, Any]) -> Any:
        if method == "search":
            return ids
        return [
            {"id": i, "list_price": 1.0, "qty_available": 3.0, "product_variant_id": [i, ""]}
            for i in body["ids"]
        ]

    first = [row["id"] for row in probe.pick_products(call, 5, 20261025)]
    assert first == [row["id"] for row in probe.pick_products(call, 5, 20261025)]
    assert first != [row["id"] for row in probe.pick_products(call, 5, 1)]
    with pytest.raises(probe.ProbeError, match="need 101"):
        probe.pick_products(call, 101, 1)
