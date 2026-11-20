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
from ..services.index_sync import send_changes
from ..services.product_index import SYNONYMS_SET, IndexNames, load_definition, read_status

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
        # The rebuild reads products on new cursors (Task 3.2): test mode makes them see this test's data.
        with self.enter_registry_test_mode():
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

    def test_incremental_sync_on_the_real_cluster(self):
        """Task 3.2: a price and stock change reaches the test alias through the outbox and one bulk."""
        self._rebuild()
        queue = self.env["lost_demand.index.queue"]
        self.env.cr.flush()
        queue.search([]).unlink()
        self.product.write({"list_price": 42.0})
        stock = self.env.ref("stock.stock_location_stock")
        self.env["stock.quant"]._update_available_quantity(self.product.product_variant_id, stock, 3.0)
        self.env.cr.flush()

        result = queue._send_to_index(names=TEST_NAMES)

        self.assertEqual((result.sent, result.failed, result.waiting), (1, 0, ""))
        document = self.client.get(index=TEST_NAMES.alias, id=str(self.product.id)).body["_source"]
        self.assertEqual((document["price"], document["free_qty"], document["in_stock"]), (42.0, 3.0, True))
        self.assertEqual(queue.search_count([]), 0)
        mapping = self.client.indices.get_mapping(index=TEST_NAMES.alias).body
        (index_mapping,) = mapping.values()
        self.assertEqual(index_mapping["mappings"]["_meta"]["definition_version"], load_definition().version)

    def test_require_alias_refuses_a_missing_alias(self):
        """Without an index behind the alias, a sync write fails instead of creating a plain index."""
        self.addCleanup(self._drop_plain_alias_index)
        outcome = send_changes(self.client, [{"template_id": 1, "name": "x"}], [], TEST_NAMES)
        self.assertEqual(outcome.done, set())
        self.assertIn("alias", outcome.failed[1])
        self.assertFalse(self.client.indices.exists(index=TEST_NAMES.alias))

    def _drop_plain_alias_index(self):
        # Only if the check above failed: a concrete test index named like the alias.
        if self.client.indices.exists(index=TEST_NAMES.alias) and not self.client.indices.exists_alias(
            name=TEST_NAMES.alias
        ):
            self.client.indices.delete(index=TEST_NAMES.alias)
