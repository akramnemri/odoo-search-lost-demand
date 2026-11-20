"""Elasticsearch status and the product index in Website settings (docs/ai/01_ARCHITECTURE.md §6.2).

Extends res.config.settings (odoo/addons/base/models/res_config.py, ResConfigSettings) with computed,
non-stored fields only: nothing is saved by `execute()`/`set_values()`, which are not overridden.
Task 3.1 adds the product index status (alias, documents vs. products) and the "Rebuild product index" button;
Task 3.2 the outbox backlog (changes waiting, products refused, oldest change) and the definition check.
Access stays the standard one of res.config.settings: Settings administrators (base.group_system) only.
"""

from datetime import UTC, datetime

from odoo import api, fields, models

from ..services.config import ConfigError
from ..services.es_client import ClusterStatus, EsService, shared_service
from ..services.index_sync import FAILING_AFTER_ATTEMPTS
from ..services.product_index import PRODUCTS, IndexStatus, load_definition


def get_es_service() -> EsService:
    """The process-wide service; tests patch this function with a fake (tests/fake_es.py)."""
    return shared_service()


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    lost_demand_es_reachable = fields.Boolean(
        string="Elasticsearch reachable", compute="_compute_lost_demand_es_status"
    )
    lost_demand_es_message = fields.Char(
        string="Elasticsearch status", compute="_compute_lost_demand_es_status"
    )
    lost_demand_es_version = fields.Char(
        string="Elasticsearch version", compute="_compute_lost_demand_es_status"
    )
    lost_demand_es_license = fields.Char(
        string="Elasticsearch license", compute="_compute_lost_demand_es_status"
    )
    lost_demand_es_health = fields.Char(string="Cluster health", compute="_compute_lost_demand_es_status")
    lost_demand_es_circuit = fields.Char(string="Search circuit", compute="_compute_lost_demand_es_status")
    lost_demand_es_checked_at = fields.Datetime(
        string="Status checked at", compute="_compute_lost_demand_es_status"
    )

    lost_demand_index_message = fields.Char(
        string="Product index status", compute="_compute_lost_demand_index_status"
    )
    lost_demand_index_name = fields.Char(string="Index", compute="_compute_lost_demand_index_status")
    lost_demand_index_documents = fields.Integer(
        string="Documents", compute="_compute_lost_demand_index_status"
    )
    lost_demand_index_products = fields.Integer(
        string="Products to index", compute="_compute_lost_demand_index_status"
    )
    lost_demand_index_in_sync = fields.Boolean(string="In sync", compute="_compute_lost_demand_index_status")

    # Task 3.2: the outbox of product changes waiting to be sent (lost_demand.index.queue).
    lost_demand_queue_message = fields.Char(
        string="Product changes", compute="_compute_lost_demand_queue_status"
    )
    lost_demand_queue_waiting = fields.Integer(
        string="Changes waiting", compute="_compute_lost_demand_queue_status"
    )
    lost_demand_queue_failing = fields.Integer(
        string="Products refused", compute="_compute_lost_demand_queue_status"
    )
    lost_demand_queue_oldest = fields.Datetime(
        string="Oldest change", compute="_compute_lost_demand_queue_status"
    )

    @api.model
    def _lost_demand_es_status(self) -> tuple[ClusterStatus, str]:
        """The cluster status and a one-line message for the administrator; never raises for an outage."""
        try:
            service = get_es_service()
        except ConfigError as error:
            status = ClusterStatus(reachable=False, error=str(error))
            return status, self.env._("Not configured: %(problem)s", problem=status.error)
        status = service.cluster_status()
        if status.reachable:
            return status, self.env._("Reachable")
        return status, self.env._(
            "Unreachable: %(error)s. The shop keeps working with Odoo's own search.", error=status.error
        )

    def _compute_lost_demand_es_status(self):
        # No @api.depends: the value comes from outside the database and is recomputed on every read
        # (EsClient caches it for a few seconds).
        status, message = self._lost_demand_es_status()
        checked_at = (
            datetime.fromtimestamp(status.checked_at, UTC).replace(tzinfo=None)
            if status.checked_at
            else False
        )
        license_text = f"{status.license_type} ({status.license_status})" if status.license_type else False
        for settings in self:
            settings.lost_demand_es_reachable = status.reachable
            settings.lost_demand_es_message = message
            settings.lost_demand_es_version = status.version or False
            settings.lost_demand_es_license = license_text
            settings.lost_demand_es_health = status.health or False
            settings.lost_demand_es_circuit = status.breaker or False
            settings.lost_demand_es_checked_at = checked_at

    def _compute_lost_demand_index_status(self):
        products = self.env["lost_demand.product.index"]._indexable_count()
        try:
            status = get_es_service().product_index_status()
        except ConfigError as error:
            status = IndexStatus(error=str(error))
        current = load_definition().version
        outdated = status.exists and status.definition_version != current
        in_sync = status.exists and not outdated and status.documents == products
        if status.error:
            message = self.env._("Unknown: %(error)s", error=status.error)
        elif not status.exists:
            message = self.env._("No product index yet: rebuild it.")
        elif outdated:
            message = self.env._(
                "Built from an older index definition (%(found)s, the module has %(current)s): rebuild the "
                "product index. Product changes wait until then.",
                found=status.definition_version or 1,
                current=current,
            )
        elif in_sync:
            message = self.env._("In sync: %(alias)s holds one document per product.", alias=PRODUCTS.alias)
        elif self.env["lost_demand.index.queue"].sudo().search_count([], limit=1):
            message = self.env._("Catching up: product changes are waiting to be sent (see below).")
        else:
            message = self.env._("Out of sync: rebuild the product index.")
        for settings in self:
            settings.lost_demand_index_message = message
            settings.lost_demand_index_name = ", ".join(status.indices) or False
            settings.lost_demand_index_documents = status.documents or 0
            settings.lost_demand_index_products = products
            settings.lost_demand_index_in_sync = in_sync

    def _compute_lost_demand_queue_status(self):
        waiting, failing, oldest = self.env["lost_demand.index.queue"]._backlog()
        if not waiting:
            message = self.env._("Up to date: no product change is waiting.")
        elif failing:
            message = self.env._(
                "%(failing)s products refused %(times)s times or more by Elasticsearch: see the server log. "
                "They are retried every hour.",
                failing=failing,
                times=FAILING_AFTER_ATTEMPTS,
            )
        else:
            message = self.env._("%(waiting)s product changes waiting to be sent.", waiting=waiting)
        for settings in self:
            settings.lost_demand_queue_message = message
            settings.lost_demand_queue_waiting = waiting
            settings.lost_demand_queue_failing = failing
            settings.lost_demand_queue_oldest = oldest or False

    def action_lost_demand_rebuild_index(self):
        """Settings button (administrators only): full rebuild, then a notification and a page reload."""
        result = self.env["lost_demand.product.index"]._rebuild()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": self.env._("Product index rebuilt"),
                "message": result.summary(),
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
