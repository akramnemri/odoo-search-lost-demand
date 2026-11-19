"""The full rebuild against the running Elasticsearch (tag `es`): run with `uv run shop test module --es`.

It uses its own alias and indices (`shop-products-test`, `shop-products-test-v<N>`), never the shop's
`shop-products`, and deletes them at the end: only test indices are ever deleted. The `odoo_app` user may
manage `shop-products*` (docker/es-setup/setup.sh).
"""

import os

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models import res_config_settings as settings_module
from ..services.config import load_config
from ..services.es_client import EsClient
from ..services.product_index import SYNONYMS_SET, IndexNames, read_status

TEST_NAMES = IndexNames(alias="shop-products-test", prefix="shop-products-test-v")


@tagged("post_install", "-at_install", "es")
class TestRebuildOnTheRealCluster(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = EsClient(load_config(os.environ))
        cls.client = cls.service.admin_client(timeout=30)
        cls.product = cls.env["product.template"].create(
            {"name": "Rebuild probe sneaker", "brand": "Acme", "type": "consu", "is_storable": True}
        )

    def setUp(self):
        super().setUp()
        # Each test starts from no test index (numbering from v1) and leaves none behind.
        self._drop_test_indices()
        self.addCleanup(self._drop_test_indices)

    @classmethod
    def _drop_test_indices(cls):
        for index in cls.client.indices.get_alias(index=TEST_NAMES.prefix + "*").body:
            if TEST_NAMES.version_of(index) is not None:
                cls.client.indices.delete(index=index)

    def _rebuild(self):
        self.patch(settings_module, "get_es_service", lambda: self.service)
        return self.env["lost_demand.product.index"]._rebuild(names=TEST_NAMES)

    def test_rebuild_twice_moves_the_alias(self):
        products = self.env["lost_demand.product.index"]._indexable_count()

        first = self._rebuild()
        second = self._rebuild()

        self.assertEqual((first.index, first.previous), ("shop-products-test-v1", ()))
        self.assertEqual(
            (second.index, second.previous), ("shop-products-test-v2", ("shop-products-test-v1",))
        )
        self.assertEqual(second.documents, products)
        status = read_status(self.client, TEST_NAMES)
        self.assertEqual((status.indices, status.documents), (("shop-products-test-v2",), products))
        self.assertTrue(self.client.indices.exists(index="shop-products-test-v1"))  # kept, not deleted
        document = self.client.get(index=TEST_NAMES.alias, id=str(self.product.id)).body["_source"]
        self.assertEqual((document["brand"], document["in_stock"]), ("Acme", False))
        sets = self.client.synonyms.get_synonyms_sets(size=1000).body["results"]
        self.assertIn(SYNONYMS_SET, [entry["synonyms_set"] for entry in sets])

    def test_analyzers_stem_and_fold(self):
        self._rebuild()
        tokens = self.client.indices.analyze(
            index=TEST_NAMES.alias, analyzer="shop_search", text="Café's Bedspreads"
        ).body["tokens"]
        self.assertEqual([token["token"] for token in tokens], ["cafe", "bedspread"])

    def test_a_missing_document_stops_the_swap(self):
        self._rebuild()
        model = type(self.env["lost_demand.product.index"])
        real_batches = model._batches

        def all_but_the_last(index, template_ids):
            yield from real_batches(index, template_ids[:-1])

        self.patch(model, "_batches", all_but_the_last)
        with self.assertRaisesRegex(UserError, "was not moved"):
            self._rebuild()
        self.assertEqual(read_status(self.client, TEST_NAMES).indices, ("shop-products-test-v1",))
        self.assertTrue(self.client.indices.exists(index="shop-products-test-v2"))  # kept for inspection
