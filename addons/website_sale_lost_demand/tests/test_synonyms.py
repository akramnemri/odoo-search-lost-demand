"""Search synonyms in Odoo (Task 3.6): validation, the starting list, the sync to a fake Elasticsearch, the
scheduled job, the settings line and access rights."""

from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models import res_config_settings as settings_module
from ..models.index_queue import CRON_XMLID
from ..models.synonym import STATE_PARAM
from ..services.product_index import SYNONYMS_SET, load_definition
from .fake_es import FakeCluster, FakeEsService

SEED_RULES = 20


@tagged("post_install", "-at_install")
class TestSynonyms(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Synonym = self.env["lost_demand.synonym"]
        self.cluster = FakeCluster(version=load_definition().version)
        self.service = FakeEsService(cluster=self.cluster)
        patcher = patch.object(settings_module, "get_es_service", return_value=self.service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pushed(self):
        return {entry["id"]: entry["synonyms"] for entry in self.cluster.synonyms.sets.get(SYNONYMS_SET, [])}

    # --- rules ---

    def test_starting_list_is_installed_and_valid(self):
        seed = self.Synonym.search([("note", "like", "Seed (Task 3.6)")])

        self.assertEqual(len(seed), SEED_RULES)
        self.assertTrue(all(seed.mapped("search_line")))  # every seed rule parses
        torch = self.env.ref("website_sale_lost_demand.synonym_seed_torch")
        self.assertEqual(torch.search_line, "torch, torches => torch, torches, flashlight, flashlights")

    def test_invalid_rule_is_refused_with_a_clear_message(self):
        with self.assertRaisesRegex(ValidationError, "at least two terms"):
            self.Synonym.create({"terms": "sofa"})
        with self.assertRaisesRegex(ValidationError, "reserves"):
            self.Synonym.create({"terms": "sofa => couch, settee"})
        with self.assertRaisesRegex(ValidationError, "needs the words"):
            self.Synonym.create({"terms": "torch", "rule_type": "one_way"})

    def test_line_sent_to_search_shows_the_word_forms(self):
        rule = self.Synonym.create({"terms": "Zqx Sneakers, zqxtrainers"})

        self.assertEqual(rule.search_line, "zqx sneakers, zqx sneaker, zqxtrainers, zqxtrainer")

    # --- every change asks the sync job to run ---

    def test_create_write_unlink_trigger_the_sync_job(self):
        cron = self.env.ref(CRON_XMLID)
        triggers = self.env["ir.cron.trigger"].sudo()
        for change in (
            lambda: self.Synonym.create({"terms": "zqxa, zqxb"}),
            lambda: self.Synonym.search([("terms", "=", "zqxa, zqxb")]).write({"terms": "zqxa, zqxc"}),
            lambda: self.Synonym.search([("terms", "=", "zqxa, zqxc")]).unlink(),
        ):
            before = triggers.search_count([("cron_id", "=", cron.id)])
            change()
            self.env.cr.flush()  # runs the pre-commit callback, as a commit would
            self.assertEqual(triggers.search_count([("cron_id", "=", cron.id)]), before + 1)

    # --- the sync ---

    def test_sync_sends_the_active_rules_once(self):
        rule = self.Synonym.create({"terms": "zqxsofa, zqxcouch"})
        archived = self.Synonym.create({"terms": "zqxold, zqxgone", "active": False})

        state = self.Synonym._sync_to_search()
        self.Synonym._sync_to_search()

        self.assertEqual(state, f"in sync: {SEED_RULES + 1} rules")
        self.assertEqual(self.pushed()[f"ld-{rule.id}"], "zqxsofa, zqxcouch")
        self.assertNotIn(f"ld-{archived.id}", self.pushed())
        self.assertEqual(len(self.cluster.synonyms.puts), 1)  # the second sync found nothing to change
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param(STATE_PARAM), state)

    def test_sync_follows_edits_and_deletions(self):
        rule = self.Synonym.create({"terms": "zqxsofa, zqxcouch"})
        self.Synonym._sync_to_search()

        rule.write({"terms": "zqxsofa, zqxsettee"})
        self.Synonym._sync_to_search()
        self.assertEqual(self.pushed()[f"ld-{rule.id}"], "zqxsofa, zqxsettee")

        rule.unlink()
        self.Synonym._sync_to_search()
        self.assertNotIn(f"ld-{rule.id}", self.pushed())

    def test_lost_set_is_repaired(self):
        self.Synonym._sync_to_search()
        self.cluster.synonyms.sets.clear()  # the cluster lost its data

        self.Synonym._sync_to_search()

        self.assertEqual(len(self.pushed()), SEED_RULES)

    def test_elasticsearch_down_never_raises_and_shows_in_settings(self):
        self.cluster.down = True

        state = self.Synonym._sync_to_search()

        self.assertTrue(state.startswith("error: "))
        settings = self.env["res.config.settings"].create({})
        self.assertIn("Not sent to search yet", settings.lost_demand_synonyms_message)
        self.assertEqual(settings.lost_demand_synonyms_count, SEED_RULES)

    def test_scheduled_job_sends_synonyms_even_when_products_wait(self):
        self.cluster.version = 1  # an index of an older definition: product changes wait for a rebuild
        self.env["lost_demand.index.queue"]._cron_send_to_index()

        self.assertEqual(len(self.pushed()), SEED_RULES)

    def test_settings_line_when_in_sync(self):
        self.Synonym._sync_to_search()

        settings = self.env["res.config.settings"].create({})

        self.assertEqual(settings.lost_demand_synonyms_message, f"{SEED_RULES} active rules, sent to search.")

    # --- access ---

    def test_only_administrators_manage_synonyms(self):
        user = new_test_user(self.env, login="ld_synonym_user", groups="base.group_user")

        with self.assertRaises(AccessError):
            self.Synonym.with_user(user).search([])
