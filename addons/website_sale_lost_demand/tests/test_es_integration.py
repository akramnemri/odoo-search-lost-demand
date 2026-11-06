"""Integration with the running Elasticsearch (tag `es`): run with `uv run shop test module --es`.

Read-only cluster calls with the module's own user (odoo_app): no index is created.
"""

import os

from odoo.tests import TransactionCase, tagged

from ..services.config import load_config
from ..services.es_client import EsClient, EsUnavailable


@tagged("post_install", "-at_install", "es")
class TestRealCluster(TransactionCase):
    def setUp(self):
        super().setUp()
        self.service = EsClient(load_config(os.environ))  # a private client: no shared cache or breaker

    def test_status_from_the_running_cluster(self):
        status = self.service.cluster_status(refresh=True)
        self.assertTrue(status.reachable, status.error)
        self.assertTrue(status.version.startswith("9."))
        self.assertEqual((status.license_type, status.license_status), ("basic", "active"))
        self.assertIn(status.health, ("green", "yellow"))

    def test_unreachable_host_is_a_status(self):
        config = load_config(
            {
                "LOST_DEMAND_ES_URL": "http://unreachable.invalid:9200",
                "LOST_DEMAND_ES_USERNAME": "nobody",
                "LOST_DEMAND_ES_PASSWORD": "unused",  # pragma: allowlist secret
                "LOST_DEMAND_ES_STATUS_TIMEOUT_MS": "500",
            }
        )
        status = EsClient(config).cluster_status()
        self.assertFalse(status.reachable)
        self.assertTrue(status.error)

    def test_wrong_password_opens_the_circuit(self):
        environ = dict(os.environ, LOST_DEMAND_ES_PASSWORD="wrong-value")  # pragma: allowlist secret
        service = EsClient(load_config(environ))
        for _ in range(service.config.breaker_failures):
            with self.assertRaises(EsUnavailable):
                service.guarded(lambda client: client.info())
        self.assertEqual(service.breaker.state.value, "open")
