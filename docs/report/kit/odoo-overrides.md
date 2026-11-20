# Odoo extension points: what we inherit, what Odoo does, what we add

For the report and the presentation. Odoo 19.0 Community core is never modified (hard rule): everything
below lives in `addons/website_sale_lost_demand/` and works through Odoo's inheritance (`_inherit` on a model,
`inherit_id` on a view). Each Odoo method was read in `.odoo-src/odoo/` (Odoo `19.0.post20261015`) before it was
overridden; the path and line are given so a reader can check the original.

Two patterns only:

- **Extend and call `super()` first.** Every override lets Odoo do its full job, then adds one small step.
  If our step were removed, Odoo would behave exactly as before.
- **Add, don't replace.** New fields, new models, new view blocks; no Odoo method is replaced or skipped.

Updated at every task that adds or changes an extension point (rule in `CLAUDE.md`).

## Summary

| Task | Odoo model or view | Odoo method or element | Kind | What we add |
|---|---|---|---|---|
| 1.3 | `res.config.settings` | form view of the Website settings | view inheritance (`xpath`) | read-only Elasticsearch status block |
| 1.3 | `res.config.settings` | — (new computed fields, no method overridden) | fields | cluster reachable, version, license, health, circuit state |
| 2.4a | `product.template` | — (new field) | field | `brand` |
| 2.4a | `product.template` form view | `categ_id` field | view inheritance | `brand` next to the category |
| 3.1 | `res.config.settings` | — (new fields and a button action) | fields + action | product index status, "Rebuild product index" |
| 3.2 | `product.template` | `create`, `write`, `unlink` | override (`super()` first) | changed product IDs go to the outbox |
| 3.2 | `product.product` | `create`, `write`, `unlink` | override (`super()` first) | variant changes reach their template's document |
| 3.2 | `product.public.category` | `write`, `unlink` | override (`super()` first) | a renamed or deleted category reindexes its products |
| 3.2 | `stock.quant` | `_update_available_quantity` | override (`super()` first) | every stock or reservation change reindexes the product |
| 3.2 | `ir.cron` | — (new record) | data | scheduled action "sync product changes to Elasticsearch" |
| 3.2 | `res.config.settings` | — (new fields) | fields | outbox backlog: waiting, refused, oldest |

New models (ours, not inherited): `lost_demand.product.index` (abstract: reads products, full rebuild) and
`lost_demand.index.queue` (the outbox).

## Task 3.2 — incremental product sync (FR1)

Goal: a product, price, publication or stock change is searchable within 60 s. Odoo has no "product changed"
event, so the module hooks the few methods every such change goes through and writes the product's ID to an
outbox table **in the same transaction** (if Odoo rolls the change back, the outbox row disappears with it).

### `product.template.create` / `write` / `unlink`

- Odoo: `odoo/addons/product/models/product_template.py`, `ProductTemplate.create` (line 568) creates the
  templates and their variants; `write` (line 585) saves field values and keeps variants consistent. `unlink` is
  the ORM's generic delete. Publishing a product is a `write` of `is_published`
  (`odoo/addons/website/models/mixins.py`, `WebsitePublishedMixin.write`, line 246); archiving is a `write` of
  `active`.
- We add (`models/product_template.py`):

```python
def write(self, vals):
    result = super().write(vals)                       # Odoo saves the product as usual
    if INDEXED_TEMPLATE_FIELDS.intersection(vals):     # name, price, brand, categories, published, active, ...
        self.env["lost_demand.index.queue"]._enqueue(self.ids)
    return result
```

`create` enqueues the new IDs; `unlink` reads the IDs *before* `super()` (they are gone afterwards) and enqueues
them, so the sync deletes their documents. A write that touches no indexed field (an internal note, a weight)
queues nothing.

### `product.product.create` / `write` / `unlink`

- Odoo: `odoo/addons/product/models/product_product.py`; `unlink` (line 714) also deletes the template when its
  last variant goes (then our template `unlink` runs too).
- We add: the variant's template ID goes to the outbox on create, on unlink, and on a write of `active`,
  `default_code` or `product_tmpl_id`.

### `product.public.category.write` / `unlink`

- Odoo: `odoo/addons/website_sale/models/product_public_category.py` (ORM `write` / `unlink`).
- We add: the index stores category names, so renaming or deleting a category enqueues every product in it.

### `stock.quant._update_available_quantity` — the stock funnel

- Odoo: `odoo/addons/stock/models/stock_quant.py`, line 1038. It is the single place where a quant's on-hand or
  reserved quantity changes. Checked call paths:
  - inventory adjustment: `stock.quant._apply_inventory` (line 996) → `stock.move._action_done` →
    `stock.move.line._action_done` → `_update_available_quantity` (`stock_move_line.py`, lines 416 and 424);
  - delivery or receipt validated: the same `_action_done` path;
  - edit of a done move line: `stock.move.line._synchronize_quant` (line 733) → `_update_available_quantity`;
  - reservation (a confirmed sale order): `_update_reserved_quantity` (line 1108) → `_update_available_quantity`.
- We add (`models/stock_quant.py`):

```python
@api.model
def _update_available_quantity(self, product_id, location_id, *args, **kwargs):
    result = super()._update_available_quantity(product_id, location_id, *args, **kwargs)
    self.env["lost_demand.index.queue"]._enqueue(product_id.product_tmpl_id.ids)
    return result
```

Why reservations count: the shop decides "Out of Stock" from the **free** quantity (on hand minus reserved) in
the website's warehouse (`odoo/addons/website_sale_stock/models/website.py`, `_get_product_available_qty`), not
from the on-hand quantity. The index therefore stores `free_qty` (definition version 2); version 1 (Task 3.1)
stored `qty_available` and would have kept a product "in stock" after customers had reserved all of it.

### What `_enqueue` does (and why it is safe in a shopper's request)

`_enqueue` only adds IDs to a Python set kept on the transaction (`cr.precommit.data`). One pre-commit callback
(`odoo/sql_db.py`, `BaseCursor.flush` runs `precommit` before every commit) writes one outbox row per product and
calls `ir.cron._trigger()` (`odoo/addons/base/models/ir_cron.py`, line 735), which creates a trigger row and,
after the commit, wakes a cron worker with PostgreSQL `NOTIFY`. Nothing in a hook calls Elasticsearch, waits,
or can raise: a checkout that reserves stock never depends on the search engine.

### Odoo APIs we use without overriding them

| API | Where | Used for |
|---|---|---|
| `ir.cron._trigger()` | `base/models/ir_cron.py:735` | run the sync job now, not at its next minute |
| `ir.cron._commit_progress()` | `base/models/ir_cron.py:846` | commit after each batch of 500; "remaining" makes Odoo run the job again at once |
| `ProductProduct.free_qty` with context `warehouse_id` | `stock/models/product.py:77` | the quantity the shop sells from |
| `cr.precommit` | `odoo/sql_db.py:176` | write outbox rows in the same transaction, once per product |
| `Registry.cursor()` | `odoo/orm/registry.py:1193` | the rebuild's lock and reading transactions |

### A trap found by the tests

The sync job's method was first called `_flush`. Every Odoo model already has `BaseModel._flush()` (it writes
pending ORM changes to SQL), so the outbox model's searches started the sync job recursively. The method is now
`_send_to_index`. Lesson for the report: in an inheritance-based framework, a new private method name must be
checked against the base classes (`odoo/orm/models.py`) as well.
