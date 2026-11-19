"""Product index rebuild (Task 3.1): the Odoo glue around services/product_index.py.

Reads every product template the shop can sell, in batches, and hands plain values to the service, which
builds the documents, loads a new versioned index and moves the alias (docs/ai/01_ARCHITECTURE.md §8).
Odoo 19.0 fields read (checked in .odoo-src/odoo/addons):
- stock/models/product.py, ProductTemplate.qty_available (computed by `_compute_quantities`, per batch);
- website/models/mixins.py, WebsitePublishedMultiMixin.is_published and website_id;
- website_sale/models/product_template.py, ProductTemplate.public_categ_ids.
Nothing is overridden. Callers: the settings button (administrators) and `uv run shop index rebuild`
(`odoo shell`, superuser). The method is private, so it cannot be called over JSON-2.
"""

import logging

from odoo import api, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import split_every

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
    def _product_values(self, templates):
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
                qty_available=template.qty_available,
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
