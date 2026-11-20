"""Product index rebuild (Task 3.1) and the product values both the rebuild and the sync send (Task 3.2).

Reads every product template the shop can sell, in batches, and hands plain values to the service, which
builds the documents, loads a new versioned index and moves the alias (docs/ai/01_ARCHITECTURE.md §8).
Odoo 19.0 fields read (checked in .odoo-src/odoo/addons):
- stock/models/product.py, ProductProduct.free_qty (on hand minus reserved, `_compute_quantities`), read
  with the `warehouse_id` of the website, as website_sale_stock does (`website._get_product_available_qty`),
  and summed over the template's variants; ProductTemplate.is_storable;
- website/models/mixins.py, WebsitePublishedMultiMixin.is_published and website_id;
- website_sale/models/product_template.py, ProductTemplate.public_categ_ids.
Nothing is overridden. Callers: the settings button (administrators) and `uv run shop index rebuild`
(`odoo shell`, superuser). The method is private, so it cannot be called over JSON-2.

Rebuild and incremental sync (Task 3.2) never run together: the rebuild holds the advisory lock
`index_queue.REBUILD_LOCK` and the sync skips while it is taken. The lock is taken on a cursor of its own
*before* the products are read on another new cursor: Odoo transactions are REPEATABLE READ, so reading on
the caller's cursor could use a snapshot older than a change the sync has just sent and deleted from the
outbox, and the new index would silently miss it. Changes made during the rebuild wait in the outbox and
are sent to the new index right after the alias moves.
"""

import logging
from collections import defaultdict

from odoo import api, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, split_every

from ..services.config import ConfigError
from ..services.es_client import describe_error
from ..services.product_index import (
    PRODUCTS,
    IndexNames,
    ProductValues,
    RebuildError,
    RebuildResult,
    load_definition,
    rebuild,
)
from . import res_config_settings
from .index_queue import REBUILD_LOCK

_logger = logging.getLogger(__name__)
BATCH_SIZE = 500  # templates read, computed (stock) and sent per bulk request
LOG_EVERY = 5000


class LostDemandProductIndex(models.AbstractModel):
    _name = "lost_demand.product.index"
    _description = "Lost-demand product index"

    @api.model
    def _indexable_domain(self):
        """Every active product the shop can sell, published or not: unpublished ones are indexed with
        `published=false` (the lost-demand matcher may need them); shop queries filter on it."""
        return [("sale_ok", "=", True)]

    @api.model
    def _templates(self):
        # sudo: the index describes the shop, not what the user who clicks the button may read.
        return self.env["product.template"].sudo().with_context(active_test=True)

    @api.model
    def _indexable_count(self):
        return self._templates().search_count(self._indexable_domain())

    @api.model
    def _free_quantities(self, templates):
        """Template ID -> free quantity the shop can sell, in the warehouse of the product's website (or of
        the first website when the product is on every website; no warehouse set = every warehouse)."""
        default_website = self.env["website"].sudo().search([], order="sequence, id", limit=1)
        by_warehouse = defaultdict(lambda: self.env["product.template"])
        for template in templates:
            website = template.website_id or default_website
            by_warehouse[website.warehouse_id.id] |= template
        free = {}
        for warehouse_id, group in by_warehouse.items():
            variants = group.product_variant_ids.with_context(warehouse_id=warehouse_id or False)
            for variant in variants:
                # A variant sold out (free <= 0) adds nothing: the shop sells from the others.
                free[variant.product_tmpl_id.id] = free.get(variant.product_tmpl_id.id, 0.0) + max(
                    variant.free_qty, 0.0
                )
        return free

    @api.model
    def _product_values(self, templates):
        free = self._free_quantities(templates)
        return [
            ProductValues(
                template_id=template.id,
                name=template.name or "",
                ref=template.default_code or None,
                description=template.description_sale or None,
                brand=template.brand or None,
                categories=[
                    (category.id, category.name) for category in template.public_categ_ids.sorted("id")
                ],
                price=template.list_price,
                free_qty=free.get(template.id, 0.0),
                is_storable=template.is_storable,
                published=template.is_published,
                website_id=template.website_id.id or None,
                updated_at=template.write_date,
            )
            for template in templates
        ]

    @api.model
    def _batches(self, template_ids):
        templates = self._templates()
        for chunk in split_every(BATCH_SIZE, template_ids):
            yield self._product_values(templates.browse(chunk))
            # Nothing was written: drop the cache so 20,000 products never sit in memory at once.
            self.env.invalidate_all(flush=False)

    @api.model
    def _rebuild(self, names: IndexNames = PRODUCTS) -> RebuildResult:
        """Full rebuild into a new index, count check, atomic alias swap. Raises UserError with the reason."""
        if not (self.env.is_superuser() or self.env.user.has_group("base.group_system")):
            raise AccessError(self.env._("Only administrators can rebuild the product index."))
        try:
            service = res_config_settings.get_es_service()  # module attribute: tests patch it
        except ConfigError as error:
            raise UserError(
                self.env._("Elasticsearch is not configured: %(problem)s", problem=str(error))
            ) from error
        registry = self.env.registry
        with registry.cursor() as lock_cr:
            # Waits for a running sync batch (seconds); then the sync skips until this transaction ends.
            lock_cr.execute(SQL("SELECT pg_advisory_xact_lock(%s)", REBUILD_LOCK))
            with registry.cursor() as read_cr:
                result = self.with_env(self.env(cr=read_cr))._rebuild_locked(service, names)
            # Committed with lock_cr (an `odoo shell` rolls back its own cursor at the end).
            self.env(cr=lock_cr)["lost_demand.index.queue"]._after_rebuild()
        return result

    @api.model
    def _rebuild_locked(self, service, names: IndexNames) -> RebuildResult:
        template_ids = self._templates().search(self._indexable_domain(), order="id").ids
        _logger.info(
            "Product index rebuild started: %s products into %s", len(template_ids), names.prefix + "<N>"
        )

        def progress(sent):
            if sent % LOG_EVERY < BATCH_SIZE:
                _logger.info("Product index rebuild: %s of %s products sent", sent, len(template_ids))

        try:
            result = rebuild(
                service.admin_client(),
                load_definition(),
                self._batches(template_ids),
                expected=len(template_ids),
                names=names,
                progress=progress,
            )
        except RebuildError as error:
            _logger.warning("Product index rebuild failed: %s", error)
            raise UserError(str(error)) from error
        except service.client_errors() as error:
            _logger.warning("Product index rebuild failed: %s", describe_error(error))
            raise UserError(
                self.env._(
                    "Elasticsearch error during the rebuild: %(error)s. The alias %(alias)s was not moved.",
                    error=describe_error(error),
                    alias=names.alias,
                )
            ) from error
        _logger.info("Product index rebuild done: %s", result.summary(names))
        return result
