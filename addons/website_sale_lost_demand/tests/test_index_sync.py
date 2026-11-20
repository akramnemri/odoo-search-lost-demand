"""Incremental product sync (Task 3.2): hooks fill the outbox, the flush job empties it into the index.

No Elasticsearch here: a fake cluster keeps documents in a dict (tests/fake_es.py). The real cluster is in
test_product_index_es.py (tag `es`). `self.env.cr.flush()` runs the pre-commit callbacks, as a commit would.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

from ..models import res_config_settings as settings_module
from ..models.index_queue import CRON_XMLID, REBUILD_LOCK
from ..services.index_sync import FIRST_RETRY_SECONDS
from ..services.product_index import load_definition
from .fake_es import FakeCluster, FakeEsService


class SyncCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.queue = cls.env["lost_demand.index.queue"]
        cls.stock = cls.env.ref("stock.stock_location_stock")
        cls.category = cls.env["product.public.category"].create({"name": "Garden"})
        cls.product = cls._storable("Hose reel", 19.99)

    @classmethod
    def _storable(cls, name, price=10.0, **vals):
        return cls.env["product.template"].create(
            {
                "name": name,
                "list_price": price,
                "type": "consu",
                "is_storable": True,
                "is_published": True,
                "public_categ_ids": [Command.set(cls.category.ids)],
                **vals,
            }
        )

    def setUp(self):
        super().setUp()
        self.env.cr.flush()  # rows of setUpClass
        self.queue.search([]).unlink()
        self.cluster = FakeCluster(version=load_definition().version)
        self.service = FakeEsService(cluster=self.cluster)
        patcher = patch.object(settings_module, "get_es_service", return_value=self.service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def queued(self):
        """Template IDs in the outbox once this transaction would commit."""
        self.env.cr.flush()
        return sorted(set(self.queue.search([]).mapped("template_id")))

    def set_stock(self, template, quantity):
        quant = (
            self.env["stock.quant"]
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": template.product_variant_id.id,
                    "location_id": self.stock.id,
                    "inventory_quantity": quantity,
                }
            )
        )
        quant.action_apply_inventory()

    def flush(self):
        self.env.cr.flush()
        return self.queue._send_to_index()

    def document(self, template):
        return self.cluster.documents.get(str(template.id))


@tagged("post_install", "-at_install")
class TestHooks(SyncCase):
    def test_create_write_unlink(self):
        new = self._storable("Watering can")
        self.assertEqual(self.queued(), [new.id])

        self.queue.search([]).unlink()
        self.product.write({"list_price": 24.5})
        self.assertEqual(self.queued(), [self.product.id])

        self.queue.search([]).unlink()
        new_id = new.id
        new.unlink()
        self.assertEqual(self.queued(), [new_id])  # a plain ID: the row outlives the product

    def test_publish_and_archive_are_writes(self):
        self.product.website_publish_button()  # published -> unpublished
        self.assertEqual(self.queued(), [self.product.id])
        self.queue.search([]).unlink()
        self.product.action_archive()
        self.assertEqual(self.queued(), [self.product.id])

    def test_a_field_the_index_ignores_queues_nothing(self):
        self.product.write({"description": "Internal note", "weight": 2.5})
        self.assertEqual(self.queued(), [])

    def test_one_row_per_product_per_transaction(self):
        self.product.write({"list_price": 1.0})
        self.product.write({"name": "Hose reel XL"})
        self.set_stock(self.product, 4)
        self.env.cr.flush()
        self.assertEqual(self.queue.search_count([("template_id", "=", self.product.id)]), 1)

    def test_inventory_adjustment_and_reservation(self):
        self.set_stock(self.product, 6)
        self.assertEqual(self.queued(), [self.product.id])

        self.queue.search([]).unlink()
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.out_type_id.id,
                "location_id": self.stock.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.product_variant_id.id,
                            "product_uom_qty": 2,
                            "location_id": self.stock.id,
                            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()  # reservation: free quantity 6 -> 4, on hand unchanged
        self.assertEqual(self.queued(), [self.product.id])
        self.flush()
        self.assertEqual(self.document(self.product)["free_qty"], 4.0)

        picking.button_validate()  # delivery done: on hand 6 -> 4, free stays 4
        self.assertEqual(self.queued(), [self.product.id])
        self.assertEqual(picking.state, "done")

    def test_category_rename_and_variant_changes(self):
        self.category.write({"name": "Garden tools"})
        self.assertEqual(self.queued(), [self.product.id])
        self.queue.search([]).unlink()
        self.product.product_variant_id.write({"default_code": "B0VARIANT1"})
        self.assertEqual(self.queued(), [self.product.id])

    def test_commit_asks_the_flush_job_to_run_now(self):
        cron = self.env.ref(CRON_XMLID)
        triggers = self.env["ir.cron.trigger"].sudo()
        before = triggers.search_count([("cron_id", "=", cron.id)])
        self.product.write({"list_price": 3.0})
        self.env.cr.flush()
        self.assertEqual(triggers.search_count([("cron_id", "=", cron.id)]), before + 1)


@tagged("post_install", "-at_install")
class TestFlush(SyncCase):
    def test_changes_reach_the_index(self):
        self.set_stock(self.product, 5)
        result = self.flush()
        document = self.document(self.product)
        self.assertEqual((result.sent, result.failed, result.waiting), (1, 0, ""))
        self.assertEqual((document["free_qty"], document["in_stock"], document["price"]), (5.0, True, 19.99))
        self.assertEqual(document["categories"], ["Garden"])
        self.assertEqual(self.queue.search_count([]), 0)

        self.set_stock(self.product, 0)
        self.product.write({"is_published": False})
        self.flush()
        document = self.document(self.product)
        self.assertEqual((document["in_stock"], document["published"]), (False, False))

    def test_products_that_do_not_track_stock_are_in_stock(self):
        service = self._storable("Gift card", is_storable=False)
        self.flush()
        self.assertTrue(self.document(service)["in_stock"])

    def test_archived_unsellable_and_deleted_products_leave_the_index(self):
        gone = [self._storable(name) for name in ("Old model", "Internal part", "Deleted item")]
        self.flush()
        self.assertTrue(all(self.document(template) for template in gone))
        ids = [template.id for template in gone]
        gone[0].action_archive()
        gone[1].write({"sale_ok": False})
        gone[2].unlink()
        result = self.flush()
        self.assertEqual(result.sent, 3)
        self.assertEqual([self.cluster.documents.get(str(i)) for i in ids], [None, None, None])

    def test_duplicates_become_one_bulk_item(self):
        for price in (1.0, 2.0, 3.0):
            self.product.write({"list_price": price})
            self.env.cr.flush()  # three transactions -> three rows
        self.assertEqual(self.queue.search_count([]), 3)
        self.flush()
        (operations,) = self.cluster.bulk_calls
        self.assertEqual(len(operations), 2)  # one action + one document
        self.assertEqual(self.document(self.product)["price"], 3.0)

    def test_outage_keeps_rows_until_recovery(self):
        self.product.write({"list_price": 7.0})
        self.cluster.down = True
        result = self.flush()
        self.assertIn("unreachable", result.waiting)
        row = self.queue.search([])
        self.assertEqual((len(row), row.attempts), (1, 0))  # an outage is not the product's fault

        self.cluster.down = False
        result = self.flush()
        self.assertEqual((result.sent, self.queue.search_count([])), (1, 0))
        self.assertEqual(self.document(self.product)["price"], 7.0)

    def test_a_refused_product_is_retried_later_and_others_go_through(self):
        other = self._storable("Rain gauge")
        self.product.write({"list_price": 8.0})
        self.cluster.refuse[self.product.id] = "failed to parse field [price]"
        result = self.flush()
        self.assertEqual((result.sent, result.failed), (1, 1))
        self.assertTrue(self.document(other))
        row = self.queue.search([])
        self.assertEqual((row.template_id, row.attempts), (self.product.id, 1))
        self.assertIn("failed to parse", row.last_error)
        self.assertGreaterEqual(
            row.next_attempt_at, fields.Datetime.now() + timedelta(seconds=FIRST_RETRY_SECONDS - 1)
        )

        self.cluster.refuse.clear()
        self.assertEqual(self.flush().sent, 0)  # not due yet
        self.queue._after_rebuild()  # due again at once
        self.assertEqual(self.flush().sent, 1)
        self.assertEqual(self.queue.search_count([]), 0)

    def test_an_outdated_or_missing_index_makes_changes_wait(self):
        self.product.write({"list_price": 9.0})
        self.cluster.version = None  # an index built before Task 3.2
        self.assertIn("rebuild the product index", self.flush().waiting)
        self.cluster.index = None
        self.assertIn("no index behind the alias", self.flush().waiting)
        self.assertEqual((self.cluster.bulk_calls, self.queue.search_count([])), ([], 1))

    def test_a_running_rebuild_makes_the_flush_skip(self):
        self.product.write({"list_price": 11.0})
        self.env.cr.flush()
        # A real second connection holds the lock, as a rebuild in another worker would.
        with self.registry.cursor() as other:
            other.execute("SELECT pg_advisory_xact_lock(%s)", [REBUILD_LOCK])
            result = self.queue._send_to_index()
            other.rollback()
        self.assertEqual(result.waiting, "a product index rebuild is running")
        self.assertEqual(self.queue.search_count([]), 1)


@tagged("post_install", "-at_install")
class TestBacklogOnSettings(SyncCase):
    def test_backlog_is_shown(self):
        self.product.write({"list_price": 4.0})
        self.env.cr.flush()
        admin = self.env.ref("base.user_admin")
        settings = self.env["res.config.settings"].with_user(admin).create({})
        self.assertEqual(settings.lost_demand_queue_waiting, 1)
        self.assertIn("1 product changes waiting", settings.lost_demand_queue_message)
        self.queue.search([]).write({"attempts": 10})
        settings = self.env["res.config.settings"].with_user(admin).create({})
        self.assertEqual(settings.lost_demand_queue_failing, 1)
