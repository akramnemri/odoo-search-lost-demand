"""Integration with the running Elasticsearch (tag `es`): run with `uv run shop test module --es`.

Read-only cluster calls with the module's own user (odoo_app): no index is created.
"""

import os
import time

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

    def test_unknown_host_answers_within_the_timeout(self):
        # The DNS lookup of a name unknown to Docker takes ~3 s in the container (8 s for a stopped
        # `elasticsearch` container; measured 2026-11-06), longer than any client timeout; the hard
        # deadline must still answer in time.
        config = load_config(
            {
                "LOST_DEMAND_ES_URL": "http://lost-demand-no-such-host:9200",
                "LOST_DEMAND_ES_USERNAME": "nobody",
                "LOST_DEMAND_ES_PASSWORD": "unused",  # pragma: allowlist secret
                "LOST_DEMAND_ES_STATUS_TIMEOUT_MS": "500",
            }
        )
        started = time.monotonic()
        status = EsClient(config).cluster_status()
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertFalse(status.reachable)
        self.assertTrue(status.error)

    def test_wrong_password_opens_the_circuit(self):
        environ = dict(os.environ, LOST_DEMAND_ES_PASSWORD="wrong-value")  # pragma: allowlist secret
        service = EsClient(load_config(environ))
        for _ in range(service.config.breaker_failures):
            with self.assertRaises(EsUnavailable):
                service.guarded(lambda client: client.info())
        self.assertEqual(service.breaker.state.value, "open")
