# Odoo extension points: what we inherit, what Odoo does, what we add

For the report and the presentation. Odoo 19.0 Community core is never modified (hard rule): everything
below lives in `addons/website_sale_lost_demand/` and works through Odoo's inheritance (`_inherit` on a model,
`inherit_id` on a view). Each Odoo method was read in `.odoo-src/odoo/` (Odoo `19.0.post20261015`) before it was
overridden; the path and line are given so a reader can check the original.

Three patterns only:

- **Extend and call `super()` first.** Every override lets Odoo do its full job, then adds one small step.
  If our step were removed, Odoo would behave exactly as before.
- **Add, don't replace.** New fields, new models, new view blocks.
- **Replace with Odoo as the fallback** (Task 3.3 only, the shop search): our code answers instead of Odoo's,
  and `super()` — Odoo's own search — runs whenever ours cannot (Elasticsearch down, slow, refusing). The only
  place where an Odoo method is deliberately not called on the normal path; the reason is written in the code.

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
| 3.3 | `WebsiteSale` controller (`/shop`) | `_shop_lookup_products` | replace, `super()` as fallback | Elasticsearch ranks; Odoo filters with its own domain and keeps the order |
| 3.3 | `WebsiteSale` controller (`/shop`) | `_get_shop_domain` | override (`super()` called, then narrowed) | categories, attributes and price range describe the products Elasticsearch found |
| 3.6 | `lost_demand.synonym` (new model) | — (new model, views, menu under Website › Configuration) | model + views | search synonyms managed by administrators; changes trigger the sync job |
| 3.6 | `res.config.settings` | — (new fields and an action button) | fields + view block | synonym rule count, sync state, "Manage synonyms" |

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

## Task 3.3 — shop search through Elasticsearch, with fallback (FR1–FR3)

Goal: `/shop?search=...` is answered by Elasticsearch (stemming, synonyms, typo tolerance, relevance order,
in-stock first), while everything else on the page — what a shopper may see, pages, totals, the category and
attribute filters, prices — stays Odoo's. Code: `controllers/main.py` (class `WebsiteSaleLostDemand`, inherits
`odoo.addons.website_sale.controllers.main.WebsiteSale`), `services/query_builder.py`, `services/shop_search.py`.

### How Odoo 19 builds a shop search page

`WebsiteSale.shop()` (`website_sale/controllers/main.py:285`) calls, in this order:

1. `_shop_lookup_products()` (line 239) → `website._search_with_fuzzy("products_only", ...)`
   (`website/models/website.py:2052`) → `product.template._search_get_detail()`
   (`website_sale/models/product_template.py:873`) gives the base domain (`website.sale_product_domain()`:
   sellable, website, company, and for visitors published; plus category, tags, price, attributes), and
   `_search_fetch()` (`website/models/mixins.py:380`) adds "every word `ilike` the name, reference or
   descriptions" and sorts by the shop order (`_get_search_order()`, line 149). If nothing matches, one similar
   word is tried. It returns `(similar word, count, products)`.
2. `_get_shop_domain()` (line 158) — the same filters (without tags and price) with the words — for the price
   range (line 383), the category list (line 426) and the attribute filters (line 478).
3. The pager slices the products **in their order** (`search_product[offset:offset + ppg]`, line 467).

### `_shop_lookup_products` — replaced, with Odoo as the fallback

```python
def _shop_lookup_products(self, options, post, search, website):
    choice = choose_engine(request.httprequest.headers, load_test_key(os.environ))
    text = clean_query(search)
    if not text or choice.engine == ODOO:
        return self._lost_demand_native(...)            # super(): category browsing stays Odoo's
    try:
        hits = search_template_ids(es_service(), "shop-products", choice.engine, text, filters, 1000)
    except (EsUnavailable, ConfigError, MalformedResponse):
        return self._lost_demand_native(...)            # super(): Odoo's native search
    products = self._lost_demand_products(hits.ids, options, post, website)
    return False, len(products), products               # no "similar word": Elasticsearch's answer is final
```

`_lost_demand_products` re-filters Elasticsearch's IDs with **Odoo's own base domain**, taken from
`product.template._search_get_detail()` — the very filters the native search uses — as the shopper (same access
rules), then restores Elasticsearch's order (or applies the sort the shopper picked in the sort menu):

```python
domain = Domain.AND(detail["base_domain"]) & Domain("id", "in", ranked_ids)
allowed = Product.search(domain)
return allowed.sorted(key=lambda product: rank[product.id])
```

So Elasticsearch decides the **order**, Odoo decides what **may be shown**: a product unpublished in Odoo but
still marked published in the index (for up to the sync delay) is never shown.

### `_get_shop_domain` — `super()` without the words, limited to the products found

```python
without_words = super()._get_shop_domain("", category, attribute_value_dict, search_in_description)
return without_words & Domain("id", "in", list(outcome.hit_ids))
```

Without it, a query Odoo's words cannot match (a typo, a plural, a brand) would show products but an empty
category list and no attribute filters. Used only when Elasticsearch answered this request's search.

### Fallback and timeouts

`EsClient.guarded()` (Task 1.3): a hard 500 ms deadline that includes the DNS lookup (calls run in a worker
pool; shopper searches have their own 8 workers since Task 3.3), and a circuit breaker (3 failures → open for
30 s → one trial). Elasticsearch down, slow, refusing, the circuit open, missing settings or an answer of the
wrong shape: `super()` answers. A warning is logged once per breaker opening.

### Odoo APIs we use without overriding them

| API | Where | Used for |
|---|---|---|
| `product.template._search_get_detail()` | `website_sale/models/product_template.py:873` | Odoo's own shop filters for the re-filter |
| `WebsiteSale._get_search_order()` | `website_sale/controllers/main.py:149` | the sort the shopper picked |
| `request.future_response.headers` | `odoo/http.py:1777`, injected at line 2456 | `X-Lost-Demand-Engine-Used` (evaluation requests only) |
| `child_of` on `product.public.category` | ORM | the selected category's subcategories, for Elasticsearch's filter |

Not changed: the search-bar autocomplete (`/website/snippet/autocomplete`, FR4 later) and category pages without
search text stay Odoo's.

## Task 3.6 — synonyms managed in Odoo (FR2)

No Odoo method is overridden: Task 3.6 **adds** a model and plugs into Odoo's own mechanisms.

- **New model `lost_demand.synonym`** (`models/synonym.py`): `terms`, `rule_type` (same meaning / one-way),
  `targets`, `active`, `note`, computed `search_line` (the exact line sent). Validation with `@api.constrains`
  raising `ValidationError` (Odoo's standard way to refuse a save with a message). `create`, `write` and `unlink`
  call `super()` first, then register a **pre-commit callback** (`cr.precommit`, `odoo/sql_db.py`) that triggers the
  product sync job (`ir.cron._trigger()`, `base/models/ir_cron.py:735`) — the same pattern as the product outbox of
  Task 3.2, so nothing calls Elasticsearch inside the administrator's save, and a rolled-back save triggers nothing.
- **The sync** runs inside our existing scheduled action (`lost_demand.index.queue._cron_send_to_index`): synonyms
  first (they do not depend on the product index), then product changes. It never raises (Odoo deactivates a cron
  job that keeps failing) and stores its last state in an `ir.config_parameter`.
- **Views**: list, form and search views, an `ir.actions.act_window` and a `menuitem` under
  `website.menu_website_global_configuration` (`website/views/res_config_settings_views.xml:251`), restricted to
  `base.group_system`; access rights in `ir.model.access.csv`.
- **Data**: 20 starting rules in `data/lost_demand_synonym_data.xml` with `noupdate="1"`, so a module upgrade never
  overwrites the administrator's edits.
- **Settings**: two computed fields on `res.config.settings` and a button of type `action` to the synonyms list.

The ranking side (typed words before synonym-only matches) is in our query code, not in Odoo: see
`services/query_builder.py` (`literal_boost`) and ADR-021.
