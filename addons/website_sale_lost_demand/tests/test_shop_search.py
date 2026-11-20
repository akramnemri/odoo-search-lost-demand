"""The /shop search through Elasticsearch, with fallback (Task 3.3), on real shop pages (`HttpCase.url_open`).

Elasticsearch is a real `EsClient` (breaker, deadline, worker pool) around a fake low-level client
(tests/fake_es.py `FakeSearchClient`) that answers with the template IDs a test chooses, whatever the query:
the tests check what Odoo does with Elasticsearch's answer, not relevance (that is Task 3.4-3.5).
"""

import re
import threading
import time

from odoo.tests import HttpCase, tagged

from ..controllers import main as controller
from ..services.config import EsConfig
from ..services.es_client import EsClient
from ..services.shop_search import ENGINE_HEADER, ENGINE_USED_HEADER, KEY_HEADER
from .fake_es import FakeEsError, FakeSearchClient

KEY = "test-load-test-key-0123456789"  # pragma: allowlist secret
WORD = "zqxlamp"  # a word no other product of the test database contains
# A product link is /shop/<product>, or /shop/<category>/<product> on a category page
# (website_sale/models/product_template.py:1117, `_get_product_url`).
_PRODUCT = re.compile(r'href="/shop/(?!category/|cart|checkout|wishlist|page/)(?:[a-z0-9-]+/)?[a-z0-9-]*?-(\d+)"')
_GRID = 'id="o_wsale_products_grid"'
_COUNT = re.compile(r"Search results for </span>'<strong>[^<]*</strong>'\s*(?:<small[^>]*>\s*\((\d+)\)</small>)?")


def config(**changes):
    values = {
        "url": "http://elasticsearch:9200",
        "username": "odoo_app",
        "password": "fake-value",  # pragma: allowlist secret
        "search_timeout": 0.3,
        "breaker_failures": 3,
        "breaker_reset_seconds": 30,
    }
    values.update(changes)
    return EsConfig(**values)


@tagged("post_install", "-at_install")
class TestShopSearch(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["product.public.category"]
        cls.lamps = Category.create({"name": "Zqx Lamps"})
        cls.desk_lamps = Category.create({"name": "Zqx Desk Lamps", "parent_id": cls.lamps.id})
        cls.garden = Category.create({"name": "Zqx Garden"})

        def product(name, price, category, published=True):
            return cls.env["product.template"].create(
                {
                    "name": name,
                    "list_price": price,
                    "type": "consu",
                    "sale_ok": True,
                    "is_published": published,
                    "public_categ_ids": [(6, 0, category.ids)],
                }
            )

        cls.alpha = product(f"Alpha {WORD}", 30.0, cls.lamps)
        cls.beta = product(f"Beta {WORD}", 10.0, cls.desk_lamps)
        cls.gamma = product(f"Gamma {WORD}", 20.0, cls.lamps)
        cls.delta = product(f"Delta {WORD}", 40.0, cls.lamps)
        cls.garden_chair = product("Garden chair", 50.0, cls.garden)
        cls.hidden = product(f"Hidden {WORD}", 5.0, cls.lamps, published=False)

    def setUp(self):
        super().setUp()
        self.client = FakeSearchClient()
        self.use_service(config())
        self.patch(controller, "load_test_key", lambda environ: KEY)

    def use_service(self, es_config):
        self.service = EsClient(es_config, client=self.client, errors=(FakeEsError,))
        self.patch(controller, "es_service", lambda: self.service)

    def shop(self, query, path="/shop", headers=None, **params):
        response = self.url_open(path, params={"search": query, **params}, headers=headers)
        self.assertEqual(response.status_code, 200)
        return response

    @staticmethod
    def shown(response):
        page = response.text
        ids = []
        for match in _PRODUCT.finditer(page, max(page.find(_GRID), 0)):
            if int(match.group(1)) not in ids:
                ids.append(int(match.group(1)))
        return ids

    @staticmethod
    def total(response):
        match = _COUNT.search(response.text)
        return int(match.group(1)) if match and match.group(1) else 0

    def rank(self, *products):
        self.client.ranked = [product.id for product in products]

    # --- Elasticsearch answers ---

    def test_elasticsearch_order_is_kept(self):
        self.rank(self.gamma, self.alpha, self.beta)

        response = self.shop(WORD)

        self.assertEqual(self.shown(response), [self.gamma.id, self.alpha.id, self.beta.id])
        self.assertEqual(self.total(response), 3)
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0]["index"], "shop-products")

    def test_unpublished_product_never_shown_even_if_elasticsearch_returns_it(self):
        self.rank(self.hidden, self.alpha)

        response = self.shop(WORD)

        self.assertEqual(self.shown(response), [self.alpha.id])
        self.assertEqual(self.total(response), 1)

    def test_products_odoo_words_cannot_find_are_shown_with_their_category(self):
        # A typo: Odoo's every-word-must-match search finds nothing, Elasticsearch found Beta.
        self.rank(self.beta)

        response = self.shop("zqxlmap")

        self.assertEqual(self.shown(response), [self.beta.id])
        self.assertIn(f"/shop/category/{self.env['ir.http']._slug(self.lamps)}", response.text)
        self.assertNotIn(f"/shop/category/{self.env['ir.http']._slug(self.garden)}", response.text)

    def test_no_hit_shows_no_result_without_odoo_retry(self):
        self.rank()

        response = self.shop(WORD)

        self.assertEqual(self.shown(response), [])
        self.assertNotIn("Showing results for", response.text)

    def test_pages_follow_elasticsearch_order(self):
        self.env["website"].get_current_website().shop_ppg = 2
        self.rank(self.delta, self.beta, self.gamma, self.alpha)

        first = self.shop(WORD)
        second = self.shop(WORD, path="/shop/page/2")

        self.assertEqual(self.shown(first), [self.delta.id, self.beta.id])
        self.assertEqual(self.shown(second), [self.gamma.id, self.alpha.id])
        self.assertEqual(self.total(first), 4)

    def test_category_page_filters_in_elasticsearch_and_in_odoo(self):
        self.rank(self.garden_chair, self.beta, self.alpha)  # the chair is not a lamp

        response = self.shop(WORD, path=f"/shop/category/{self.env['ir.http']._slug(self.lamps)}")

        self.assertEqual(self.shown(response), [self.beta.id, self.alpha.id])
        sent = self.client.requests[0]["query"]["bool"]["filter"][-1]
        self.assertEqual(sent, {"terms": {"category_ids": sorted([self.lamps.id, self.desk_lamps.id])}})

    def test_chosen_sort_orders_the_elasticsearch_hits(self):
        self.rank(self.gamma, self.alpha, self.beta)

        response = self.shop(WORD, order="list_price asc")

        self.assertEqual(self.shown(response), [self.beta.id, self.gamma.id, self.alpha.id])

    def test_browsing_without_search_text_does_not_ask_elasticsearch(self):
        self.url_open("/shop")
        self.shop("   ")

        self.assertEqual(self.client.requests, [])

    # --- fallback ---

    def native(self):
        """What Odoo's own search shows for WORD: the published products whose name holds it."""
        return {self.alpha.id, self.beta.id, self.gamma.id, self.delta.id}

    def test_elasticsearch_down_gives_odoo_results(self):
        self.client.down = True

        response = self.shop(WORD, headers={KEY_HEADER: KEY})

        self.assertEqual(set(self.shown(response)), self.native())
        self.assertEqual(response.headers.get(ENGINE_USED_HEADER), "odoo_fallback")

    def test_circuit_opens_after_repeated_failures(self):
        self.client.down = True

        for _ in range(4):
            self.assertEqual(set(self.shown(self.shop(WORD))), self.native())

        self.assertEqual(len(self.client.requests), 3)  # the fourth search did not try Elasticsearch

    def test_slow_elasticsearch_times_out_to_odoo_results_within_budget(self):
        self.client.hang = threading.Event()
        self.addCleanup(self.client.hang.set)
        self.rank(self.alpha)

        started = time.monotonic()
        response = self.shop(WORD, headers={KEY_HEADER: KEY})
        elapsed = time.monotonic() - started

        self.assertEqual(set(self.shown(response)), self.native())
        self.assertEqual(response.headers.get(ENGINE_USED_HEADER), "odoo_fallback")
        # 0.3 s deadline + Odoo's own search and rendering; the fake would hang 10 s.
        self.assertLess(elapsed, 5)

    # --- evaluation switch ---

    def test_engine_switch_ignored_without_the_key(self):
        self.rank(self.alpha)

        for headers in ({ENGINE_HEADER: "odoo"}, {ENGINE_HEADER: "odoo", KEY_HEADER: "wrong-key-0123456789"}):
            response = self.shop(WORD, headers=headers)
            self.assertEqual(self.shown(response), [self.alpha.id])
            self.assertNotIn(ENGINE_USED_HEADER, response.headers)

        self.assertEqual(len(self.client.requests), 2)
        self.assertIn({"in_stock": "desc"}, self.client.requests[0]["sort"])  # the default engine

    def test_engine_switch_ignored_when_no_key_is_configured(self):
        self.patch(controller, "load_test_key", lambda environ: "")
        self.rank(self.alpha)

        response = self.shop(WORD, headers={ENGINE_HEADER: "odoo", KEY_HEADER: KEY})

        self.assertEqual(self.shown(response), [self.alpha.id])
        self.assertEqual(len(self.client.requests), 1)

    def test_engine_switch_with_the_key(self):
        self.rank(self.alpha)

        odoo = self.shop(WORD, headers={ENGINE_HEADER: "odoo", KEY_HEADER: KEY})
        plain = self.shop(WORD, headers={ENGINE_HEADER: "es_plain", KEY_HEADER: KEY})

        self.assertEqual(set(self.shown(odoo)), self.native())
        self.assertEqual(odoo.headers.get(ENGINE_USED_HEADER), "odoo")
        self.assertEqual(self.shown(plain), [self.alpha.id])
        self.assertEqual(plain.headers.get(ENGINE_USED_HEADER), "es_plain")
        self.assertEqual(len(self.client.requests), 1)  # only es_plain asked Elasticsearch
        fields = self.client.requests[0]["query"]["bool"]["must"][0]["multi_match"]["fields"]
        self.assertEqual(fields, ["name.std", "description.std", "brand.std"])
