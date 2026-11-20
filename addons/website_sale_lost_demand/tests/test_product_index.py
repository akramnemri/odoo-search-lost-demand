"""Product index (Task 3.1): values read from Odoo, index status in settings, access to the rebuild.

No Elasticsearch here (a fake service); the real rebuild is in test_product_index_es.py (tag `es`).
"""

from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models import res_config_settings as settings_module
from ..services.config import ConfigError
from ..services.product_index import IndexStatus, load_definition
from .fake_es import HEALTHY, FakeEsService


def _with_service(service):
    return patch.object(settings_module, "get_es_service", return_value=service)


@tagged("post_install", "-at_install")
class TestProductValues(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.index = cls.env["lost_demand.product.index"]
        cls.category = cls.env["product.public.category"].create({"name": "Automotive"})
        cls.product = cls.env["product.template"].create(
            {
                "name": "Throttle cable",
                "default_code": "B000TEST01",
                "brand": "Acme",
                "description_sale": "Fits most mowers.",
                "list_price": 12.5,
                "type": "consu",
                "is_storable": True,
                "is_published": True,
                "public_categ_ids": [(6, 0, cls.category.ids)],
            }
        )
        stock = cls.env.ref("stock.stock_location_stock")
        cls.env["stock.quant"]._update_available_quantity(cls.product.product_variant_id, stock, 7.0)

    def test_values_of_a_product(self):
        (values,) = self.index._product_values(self.product)
        self.assertEqual(values.template_id, self.product.id)
        self.assertEqual((values.name, values.ref, values.brand), ("Throttle cable", "B000TEST01", "Acme"))
        self.assertEqual(values.description, "Fits most mowers.")
        self.assertEqual(values.categories, [(self.category.id, "Automotive")])
        self.assertEqual((values.price, values.free_qty, values.published), (12.5, 7.0, True))
        self.assertIsNone(values.website_id)
        self.assertTrue(values.updated_at)

    def test_unpublished_and_unsellable_products(self):
        hidden = self.env["product.template"].create({"name": "Not on the shop", "is_published": False})
        not_for_sale = self.env["product.template"].create({"name": "Internal part", "sale_ok": False})
        archived = self.env["product.template"].create({"name": "Old model", "active": False})
        ids = self.index._templates().search(self.index._indexable_domain()).ids

        self.assertIn(hidden.id, ids)  # indexed with published=false
        self.assertNotIn(not_for_sale.id, ids)
        self.assertNotIn(archived.id, ids)
        self.assertEqual(self.index._indexable_count(), len(ids))
        (values,) = self.index._product_values(hidden)
        self.assertEqual((values.published, values.free_qty, values.brand), (False, 0.0, None))

    def test_batches_cover_every_product_once(self):
        ids = self.index._templates().search(self.index._indexable_domain(), order="id").ids
        with patch.object(type(self.index), "_product_values", lambda _self, templates: list(templates.ids)):
            seen = [template_id for batch in self.index._batches(ids) for template_id in batch]
        self.assertEqual(seen, ids)


@tagged("post_install", "-at_install")
class TestIndexStatusAndAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login="ld_index_admin", groups="base.group_system")
        cls.product_manager = new_test_user(
            cls.env, login="ld_index_manager", groups="base.group_user,product.group_product_manager"
        )

    def _settings(self):
        return self.env["res.config.settings"].with_user(self.admin).create({})

    def _products(self):
        return self.env["lost_demand.product.index"]._indexable_count()

    def test_in_sync(self):
        status = IndexStatus(("shop-products-v3",), self._products(), "", load_definition().version)
        with _with_service(FakeEsService(HEALTHY, status)):
            settings = self._settings()
            self.assertTrue(settings.lost_demand_index_in_sync)
            self.assertEqual(settings.lost_demand_index_name, "shop-products-v3")
            self.assertEqual(settings.lost_demand_index_documents, self._products())
            self.assertIn("In sync", settings.lost_demand_index_message)

    def test_out_of_sync_missing_and_unknown(self):
        cases = [
            (
                IndexStatus(("shop-products-v3",), self._products() + 1, "", load_definition().version),
                "Out of sync",
            ),
            (IndexStatus(("shop-products-v3",), self._products()), "older index definition"),
            (IndexStatus(), "No product index yet"),
            (IndexStatus(error="ConnectionError: refused"), "Unknown: ConnectionError: refused"),
        ]
        for status, message in cases:
            with self.subTest(message=message), _with_service(FakeEsService(HEALTHY, status)):
                settings = self._settings()
                self.assertFalse(settings.lost_demand_index_in_sync)
                self.assertIn(message, settings.lost_demand_index_message)

    def test_missing_configuration_is_shown(self):
        error = ConfigError("LOST_DEMAND_ES_URL is not set")
        with patch.object(settings_module, "get_es_service", side_effect=error):
            self.assertIn("LOST_DEMAND_ES_URL", self._settings().lost_demand_index_message)

    def test_only_administrators_rebuild(self):
        with _with_service(FakeEsService()), self.assertRaises(AccessError):
            self.env["lost_demand.product.index"].with_user(self.product_manager)._rebuild()

    def test_rebuild_without_configuration_is_a_clear_error(self):
        error = ConfigError("LOST_DEMAND_ES_URL is not set")
        with (
            patch.object(settings_module, "get_es_service", side_effect=error),
            self.assertRaisesRegex(UserError, "not configured: LOST_DEMAND_ES_URL"),
        ):
            self._settings().action_lost_demand_rebuild_index()

    def test_button_is_on_the_settings_form(self):
        with _with_service(FakeEsService()):
            arch = (
                self.env["res.config.settings"]
                .with_user(self.admin)
                .get_views([(False, "form")])["views"]["form"]
            )["arch"]
        self.assertIn('name="action_lost_demand_rebuild_index"', arch)
        self.assertIn('name="lost_demand_index_message"', arch)
