"""Elasticsearch status and the product index in Website settings (docs/ai/01_ARCHITECTURE.md §6.2).

Extends res.config.settings (odoo/addons/base/models/res_config.py, ResConfigSettings) with computed,
non-stored fields only: nothing is saved by `execute()`/`set_values()`, which are not overridden.
Task 3.1 adds the product index status (alias, documents vs. products) and the "Rebuild product index" button.
Access stays the standard one of res.config.settings: Settings administrators (base.group_system) only.
"""

from datetime import UTC, datetime

from odoo import api, fields, models

from ..services.config import ConfigError
from ..services.es_client import ClusterStatus, EsService, shared_service
from ..services.product_index import PRODUCTS, IndexStatus


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
        in_sync = status.exists and status.documents == products
        if status.error:
            message = self.env._("Unknown: %(error)s", error=status.error)
        elif not status.exists:
            message = self.env._("No product index yet: rebuild it.")
        elif in_sync:
            message = self.env._("In sync: %(alias)s holds one document per product.", alias=PRODUCTS.alias)
        else:
            message = self.env._("Out of sync: rebuild the product index.")
        for settings in self:
            settings.lost_demand_index_message = message
            settings.lost_demand_index_name = ", ".join(status.indices) or False
            settings.lost_demand_index_documents = status.documents or 0
            settings.lost_demand_index_products = products
            settings.lost_demand_index_in_sync = in_sync

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
