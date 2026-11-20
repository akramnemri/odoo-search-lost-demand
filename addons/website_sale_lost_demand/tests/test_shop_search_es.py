"""Shop search queries against the running Elasticsearch (tag `es`): `uv run shop test module --es`.

Builds the test alias `shop-products-test` (never the shop's `shop-products`) with the real rebuild, then
sends the engines' real queries through `search_template_ids()`: stemming, typo tolerance, the published
filter and the in-stock rule. Only test indices are deleted, at the start and end of each test.
"""

import os

from odoo.tests import TransactionCase, tagged

from ..models import res_config_settings as settings_module
from ..services.config import load_config
from ..services.es_client import EsClient
from ..services.query_builder import ES_PLAIN, ES_TUNED, ES_TUNED_STOCK, SearchFilters
from ..services.shop_search import search_template_ids
from .test_product_index_es import TEST_NAMES


@tagged("post_install", "-at_install", "es")
class TestShopSearchOnTheRealCluster(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = EsClient(load_config(os.environ))
        cls.client = cls.service.admin_client(timeout=30)
        Product = cls.env["product.template"]
        # Sold out (stock-tracked, nothing on hand) but the most relevant for "zqxes bedspread" (shortest).
        cls.sold_out = Product.create(
            {"name": "Zqxes bedspread", "type": "consu", "is_storable": True, "is_published": True}
        )
        # In stock: a product without stock tracking is never sold out.
        cls.in_stock = Product.create(
            {"name": "Zqxes bedspread velvet quilted king size", "type": "consu", "is_published": True}
        )
        cls.hidden = Product.create(
            {"name": "Zqxes bedspread hidden", "type": "consu", "is_published": False}
        )
        cls.website = cls.env["website"].get_current_website()

    def setUp(self):
        super().setUp()
        self._drop_test_indices()
        self.addCleanup(self._drop_test_indices)
        self.patch(settings_module, "get_es_service", lambda: self.service)
        with self.enter_registry_test_mode():
            self.env["lost_demand.product.index"]._rebuild(names=TEST_NAMES)

    @classmethod
    def _drop_test_indices(cls):
        for index in cls.client.indices.get_alias(index=TEST_NAMES.prefix + "*").body:
            if TEST_NAMES.version_of(index) is not None:
                cls.client.indices.delete(index=index)

    def search(self, engine, text):
        filters = SearchFilters(website_id=self.website.id)
        hits = search_template_ids(self.service, TEST_NAMES.alias, engine, text, filters, 100)
        self.assertIsInstance(hits.took_ms, int)
        ours = (self.sold_out.id, self.in_stock.id, self.hidden.id)
        return [template_id for template_id in hits.ids if template_id in ours]

    def test_published_filter_and_stemming(self):
        found = self.search(ES_TUNED, "bedspreads")

        self.assertEqual(set(found), {self.sold_out.id, self.in_stock.id})  # plural matched, hidden left out

    def test_typo_tolerance_of_the_tuned_engine_only(self):
        self.assertEqual(set(self.search(ES_TUNED, "bedsperad")), {self.sold_out.id, self.in_stock.id})
        self.assertEqual(self.search(ES_PLAIN, "bedsperad"), [])  # out of the box: no fuzziness

    def test_in_stock_rule_puts_sold_out_products_last(self):
        self.assertEqual(self.search(ES_TUNED, "zqxes bedspread"), [self.sold_out.id, self.in_stock.id])
        self.assertEqual(self.search(ES_TUNED_STOCK, "zqxes bedspread"), [self.in_stock.id, self.sold_out.id])
