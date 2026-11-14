"""Product brand (Task 2.4a).

Odoo 19.0 Community has no brand field on products (checked in .odoo-src/odoo/addons/product and
website_sale). The ESCI catalog has one, and the product index (M3) searches and boosts it, so the module adds
a plain text field. The catalog importer (`uv run shop import catalog`) fills it; shop managers can edit it on
the product form.
"""

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    brand = fields.Char(
        string="Brand", help="Brand of the product, as in the source catalog (ESCI for the demo shop)."
    )
