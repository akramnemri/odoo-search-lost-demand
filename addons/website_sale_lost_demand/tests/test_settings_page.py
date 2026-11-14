"""The Elasticsearch status block of Website settings: content, outage, misconfiguration and access."""

from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException

from ..models import res_config_settings as settings_module
from ..services.config import ConfigError
from .fake_es import DOWN, HEALTHY, FakeEsService

STATUS_FIELDS = (
    "lost_demand_es_reachable",
    "lost_demand_es_message",
    "lost_demand_es_version",
    "lost_demand_es_license",
    "lost_demand_es_health",
    "lost_demand_es_circuit",
    "lost_demand_es_checked_at",
)


def _with_service(service):
    return patch.object(settings_module, "get_es_service", return_value=service)


@tagged("post_install", "-at_install")
class TestSettingsStatus(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login="ld_settings_admin", groups="base.group_system")
        # A website designer sees the Website app of Settings in the menu but is not a Settings administrator.
        cls.designer = new_test_user(
            cls.env, login="ld_designer", groups="base.group_user,website.group_website_designer"
        )

    def _settings(self, user):
        return self.env["res.config.settings"].with_user(user).create({})

    def test_healthy_cluster(self):
        fake = FakeEsService(HEALTHY)
        with _with_service(fake):
            settings = self._settings(self.admin)
            self.assertTrue(settings.lost_demand_es_reachable)
            self.assertEqual(settings.lost_demand_es_message, "Reachable")
            self.assertEqual(settings.lost_demand_es_version, "9.5.5")
            self.assertEqual(settings.lost_demand_es_license, "basic (active)")
            self.assertEqual(settings.lost_demand_es_health, "green")
            self.assertEqual(settings.lost_demand_es_circuit, "closed")
            self.assertTrue(settings.lost_demand_es_checked_at)
        self.assertGreaterEqual(fake.calls, 1)

    def test_cluster_down_is_a_status_not_an_error(self):
        with _with_service(FakeEsService(DOWN)):
            settings = self._settings(self.admin)
            self.assertFalse(settings.lost_demand_es_reachable)
            self.assertIn("Unreachable: ConnectionError", settings.lost_demand_es_message)
            self.assertIn("Odoo's own search", settings.lost_demand_es_message)
            self.assertFalse(settings.lost_demand_es_version)
            self.assertEqual(settings.lost_demand_es_circuit, "open")

    def test_missing_configuration_is_shown(self):
        error = ConfigError("LOST_DEMAND_ES_PASSWORD is not set")
        with patch.object(settings_module, "get_es_service", side_effect=error):
            settings = self._settings(self.admin)
            self.assertFalse(settings.lost_demand_es_reachable)
            self.assertEqual(
                settings.lost_demand_es_message, "Not configured: LOST_DEMAND_ES_PASSWORD is not set"
            )

    def test_saving_settings_still_works(self):
        with _with_service(FakeEsService(DOWN)):
            self._settings(self.admin).execute()

    def test_form_view_shows_the_status_block_to_admin(self):
        arch = self.env["res.config.settings"].with_user(self.admin).get_views([(False, "form")])
        form = arch["views"]["form"]["arch"]
        self.assertIn('id="lost_demand_es_settings"', form)
        for name in STATUS_FIELDS:
            self.assertIn(f'name="{name}"', form)

    def test_non_admin_cannot_open_settings(self):
        with _with_service(FakeEsService(HEALTHY)), self.assertRaises(AccessError):
            self._settings(self.designer)

    def test_shop_manager_group(self):
        group = self.env.ref("website_sale_lost_demand.group_lost_demand_manager")
        self.assertEqual(group.privilege_id.name, "Lost Demand")
        self.assertIn(self.env.ref("base.user_admin"), group.user_ids)


@tagged("post_install", "-at_install")
class TestSettingsPageHttp(HttpCase):
    """The calls the web client makes when it opens Settings, over HTTP like a browser."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        new_test_user(cls.env, login="ld_settings_admin", groups="base.group_system")
        new_test_user(cls.env, login="ld_designer", groups="base.group_user,website.group_website_designer")

    def _open_settings(self):
        spec = {name: {} for name in STATUS_FIELDS}
        return self.make_jsonrpc_request(
            "/web/dataset/call_kw/res.config.settings/onchange",
            {
                "model": "res.config.settings",
                "method": "onchange",
                # onchange is not an @api.model method: the first argument is the record ids
                # (odoo/service/model.py::call_kw); none for a new settings record.
                "args": [[], {}, [], spec],
                "kwargs": {},
            },
        )

    def test_page_renders_for_admin(self):
        self.authenticate("ld_settings_admin", "ld_settings_admin")
        with _with_service(FakeEsService(HEALTHY)):
            values = self._open_settings()["value"]
        self.assertTrue(values["lost_demand_es_reachable"])
        self.assertEqual(values["lost_demand_es_license"], "basic (active)")

    def test_page_renders_for_admin_when_es_is_down(self):
        self.authenticate("ld_settings_admin", "ld_settings_admin")
        with _with_service(FakeEsService(DOWN)):
            values = self._open_settings()["value"]
        self.assertFalse(values["lost_demand_es_reachable"])
        self.assertIn("Unreachable", values["lost_demand_es_message"])

    def test_page_forbidden_for_others(self):
        self.authenticate("ld_designer", "ld_designer")
        with _with_service(FakeEsService(HEALTHY)), self.assertRaises(JsonRpcException) as caught:
            self._open_settings()
        self.assertEqual(str(caught.exception), "odoo.exceptions.AccessError")
