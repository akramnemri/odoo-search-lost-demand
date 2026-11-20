"""Stock changes that reach the product index (Task 3.2).

One funnel in Odoo 19.0 (checked in .odoo-src/odoo/addons/stock/models): every change of a quant's on-hand or
reserved quantity goes through `stock.quant._update_available_quantity` (stock_quant.py):
- inventory adjustments: `_apply_inventory` creates moves, `stock.move._action_done` → `stock.move.line.
  _action_done` → `_update_available_quantity` (stock_move_line.py);
- deliveries and receipts: the same `_action_done` path;
- edits of done move lines: `_synchronize_quant` → `_update_available_quantity`;
- reservations (a confirmed sale order): `_update_reserved_quantity` → `_update_available_quantity`.
The index holds the free quantity the shop sells from (on hand minus reserved), so reservations count too.
"""

from odoo import api, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def _update_available_quantity(self, product_id, location_id, *args, **kwargs):
        result = super()._update_available_quantity(product_id, location_id, *args, **kwargs)
        # Only an ID added to a set: cheap enough for every move line of a big delivery.
        self.env["lost_demand.index.queue"]._enqueue(product_id.product_tmpl_id.ids)
        return result
