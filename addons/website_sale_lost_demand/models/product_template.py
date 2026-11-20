"""Product brand (Task 2.4a) and the product changes that reach the index (Task 3.2).

Brand: Odoo 19.0 Community has no brand field on products (checked in .odoo-src/odoo/addons/product and
website_sale). The ESCI catalog has one, and the product index searches and boosts it, so the module adds
a plain text field. The catalog importer (`uv run shop import catalog`) fills it; shop managers can edit it on
the product form.

Index hooks (Task 3.2): every override calls `super()` first and then only adds template IDs to the outbox
(`lost_demand.index.queue._enqueue`); nothing here talks to Elasticsearch or can fail a save.
- product.template `create`, `write` (odoo/addons/product/models/product_template.py; publishing is a
  `write` of `is_published`, odoo/addons/website/models/mixins.py), `unlink` (also reached when the last
  variant is deleted, product/models/product_product.py `unlink`);
- product.product `create`, `write`, `unlink`: variant changes the template does not see;
- product.public.category `write` (name) and `unlink`: the index stores category names and IDs.
"""

from odoo import api, fields, models

# Template fields that change a document (services/product_index.py, build_document) or whether the product
# is indexed at all (`lost_demand.product.index._indexable_domain`, plus `active`).
INDEXED_TEMPLATE_FIELDS = frozenset(
    {
        "name",
        "default_code",
        "description_sale",
        "brand",
        "public_categ_ids",
        "list_price",
        "is_published",
        "website_published",
        "website_id",
        "active",
        "sale_ok",
        "type",
        "is_storable",
    }
)
INDEXED_VARIANT_FIELDS = frozenset({"active", "default_code", "product_tmpl_id"})


def _queue(env):
    return env["lost_demand.index.queue"]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    brand = fields.Char(
        string="Brand", help="Brand of the product, as in the source catalog (ESCI for the demo shop)."
    )

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        _queue(self.env)._enqueue(templates.ids)
        return templates

    def write(self, vals):
        result = super().write(vals)
        if INDEXED_TEMPLATE_FIELDS.intersection(vals):
            _queue(self.env)._enqueue(self.ids)
        return result

    def unlink(self):
        template_ids = self.ids
        result = super().unlink()
        _queue(self.env)._enqueue(template_ids)  # the flush deletes their documents
        return result


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model_create_multi
    def create(self, vals_list):
        variants = super().create(vals_list)
        _queue(self.env)._enqueue(variants.product_tmpl_id.ids)
        return variants

    def write(self, vals):
        before = self.product_tmpl_id.ids if "product_tmpl_id" in vals else []
        result = super().write(vals)
        if INDEXED_VARIANT_FIELDS.intersection(vals):
            _queue(self.env)._enqueue(before + self.product_tmpl_id.ids)
        return result

    def unlink(self):
        template_ids = self.with_context(active_test=False).product_tmpl_id.ids
        result = super().unlink()
        _queue(self.env)._enqueue(template_ids)
        return result


class ProductPublicCategory(models.Model):
    _inherit = "product.public.category"

    def _indexed_template_ids(self):
        templates = self.env["product.template"].sudo().with_context(active_test=False)
        return templates.search([("public_categ_ids", "in", self.ids)]).ids

    def write(self, vals):
        result = super().write(vals)
        if "name" in vals:
            _queue(self.env)._enqueue(self._indexed_template_ids())
        return result

    def unlink(self):
        template_ids = self._indexed_template_ids()
        result = super().unlink()
        _queue(self.env)._enqueue(template_ids)
        return result
