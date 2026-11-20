# website_sale_lost_demand

The project's only Odoo module (ADR-001): Elasticsearch-powered shop search with a fallback to Odoo's own
search, event capture, and restocking decisions from lost demand. Odoo 19.0 Community, LGPL-3.
Odoo core is never modified: everything here extends it by inheritance.

Version `19.0.0.1.0` (Task 1.3) is the skeleton:

- **Elasticsearch status** in *Settings > Website > Lost-demand search (Elasticsearch)*, read-only:
  reachable, version, license (must be `basic`), cluster health, search circuit state, time of the check.
  The status is reused for 10 seconds. When Elasticsearch is down the page still opens and says so.
  Only Settings administrators (`base.group_system`) can open Settings.
- **Security group** *Lost Demand / Shop manager* (read access to signals and runs from M6). Buyers reuse
  *Purchase / User*; administrators reuse *Settings* (`docs/ai/01_ARCHITECTURE.md` §6.4).
- **Services** (`services/`, pure Python, no `odoo` import): configuration, Elasticsearch client with
  timeouts and a status cache, circuit breaker.

Version `19.0.0.2.0` (Task 2.4a) adds a **Brand** field on products (`product.template.brand`, shown after the
product category on the product form). Odoo 19.0 Community has none; the catalog importer fills it.

Version `19.0.0.3.0` (Task 3.1) adds the **product index**: every product the shop can sell (active,
`sale_ok`, published or not) becomes a document in Elasticsearch behind the alias `shop-products`. A full
rebuild loads a new index `shop-products-v<N+1>`, checks that it holds one document per product, then moves
the alias in one atomic call; the previous index is kept (delete old ones yourself when no longer needed).
Run it with `uv run shop index rebuild` or *Settings › Website › Rebuild product index* (administrators);
`uv run shop index rebuild --check` and the doctor compare the counts. Shop search does not use the index yet
(Task 3.3). The module now depends on `website_sale_stock` (stock quantities).

Version `19.0.0.4.0` (Task 3.2) keeps the index **in sync within a minute** (FR1). Product, variant, category
and stock changes (inventory adjustments, deliveries, reservations) write the product's ID to an outbox
(`lost_demand.index.queue`) in the same transaction; the scheduled action *Lost-demand search: sync product
changes to Elasticsearch* runs at once (cron trigger) and every minute, sends one bulk request per 500 products
through the alias, and deletes the rows that went through. While Elasticsearch is down, rows wait and are sent
after it recovers; a product Elasticsearch refuses is retried later (30 s, doubling, at most hourly), never
dropped. *Settings › Website › Product changes* shows the backlog. The index now holds the **free** quantity
(on hand minus reserved, the shop's own rule) in `free_qty`: index definition version 2, so an index built by
19.0.0.3.0 must be rebuilt once (changes wait until then). Which Odoo methods are extended, and why:
`docs/report/kit/odoo-overrides.md`. Measure the delay with `uv run shop probe products`.

Version `19.0.0.5.0` (Task 3.3) makes the **shop search run on Elasticsearch** (`/shop?search=...`).
Elasticsearch ranks the products (at most 1,000 per search); Odoo keeps only those its own shop rules allow
(published, website, company, category, tags, price, attributes) and shows them in Elasticsearch's order, or
in the sort the shopper picked; pages, totals and the category and attribute filters follow. Engines
(`services/query_builder.py`): `es_plain` (out of the box), `es_tuned` (v0: stemming, synonyms, weights,
typo tolerance; tuned in Task 3.5) and `es_tuned_stock` (the same, in-stock products first: the default).
Any Elasticsearch problem — error, no answer within 500 ms, open circuit — gives Odoo's own search results
instead; shoppers never see an error. Searches without text (category pages) stay Odoo's.

## Layout

| Path | Content |
|---|---|
| `services/config.py` | Connection settings from the container environment (below), validated |
| `services/es_client.py` | `EsClient`: `cluster_status()` and `product_index_status()` for the settings page, `admin_client()` for the rebuild, `guarded()` for shopper calls |
| `services/breaker.py` | Circuit breaker: closed → open after N failures → half-open trial → closed |
| `services/product_index.py` | Index definition loader, documents, versioned names, rebuild with count check and alias swap |
| `services/query_builder.py` | Shop search queries per engine (pure functions), query cleaning, response parsing |
| `services/shop_search.py` | One shop search through `guarded()`; the evaluation's engine switch (load-test key) |
| `controllers/main.py` | `/shop` search override: Elasticsearch ranks, Odoo filters and keeps the order, fallback to `super()` |
| `services/index_sync.py` | Incremental sync: bulk index/delete through the alias (`require_alias`), per-item errors, retry delays, "index ready?" check |
| `elastic/products/` | Index settings and analyzers, mapping, synonyms seed (JSON; the index is built from these) |
| `models/product_index.py` | `lost_demand.product.index`: reads products (free quantity per website warehouse) in batches of 500 and runs the rebuild under the sync lock |
| `models/index_queue.py`, `data/ir_cron_data.xml` | `lost_demand.index.queue` (the outbox) and the sync job |
| `models/stock_quant.py` | Stock and reservation changes enqueue the product (`_update_available_quantity`) |
| `models/res_config_settings.py` | Computed, non-stored status fields on `res.config.settings` |
| `models/product_template.py`, `views/product_template_views.xml` | The `brand` field and its place on the form; product, variant and category changes enqueue products |
| `views/res_config_settings_views.xml` | The status block in the Website app of Settings, product index status and rebuild button |
| `security/` | Groups; `ir.model.access.csv` (the outbox: read for administrators; the module writes it as superuser) |
| `tests/` | Odoo tests; `fake_es.py` replaces Elasticsearch; tests tagged `es` use the real cluster |

## Configuration

Read only from the environment of the `odoo` container (`compose.yaml` fills it from `.env`); nothing is
stored in the Odoo database.

| Variable | Default | Meaning |
|---|---|---|
| `LOST_DEMAND_ES_URL` | required | e.g. `http://elasticsearch:9200`, no login inside |
| `LOST_DEMAND_ES_USERNAME` | required | `odoo_app` (role in `docker/es-setup/setup.sh`) |
| `LOST_DEMAND_ES_PASSWORD` | required | `ODOO_APP_ES_PASSWORD` of `.env` |
| `LOST_DEMAND_ES_SEARCH_TIMEOUT_MS` | 500 | deadline of a shopper call, then fallback |
| `LOST_DEMAND_ES_STATUS_TIMEOUT_MS` | 2000 | deadline of the whole status check of the settings page |
| `LOST_DEMAND_ES_HEALTH_CACHE_SECONDS` | 10 | reuse of the last status |
| `LOST_DEMAND_ES_BREAKER_FAILURES` | 3 | consecutive failures that open the circuit |
| `LOST_DEMAND_ES_BREAKER_RESET_SECONDS` | 30 | wait before one trial call |
| `LOST_DEMAND_ES_SEARCH_MAX_HITS` | 1000 | ranked products asked per shop search (at most 10,000) |
| `LOST_DEMAND_LOAD_TEST_KEY` | empty | `LOAD_TEST_KEY` of `.env`; with it, a request sending `X-Lost-Demand-Key` may choose the engine with `X-Lost-Demand-Engine` (`odoo`, `es_plain`, `es_tuned`, `es_tuned_stock`) and gets `X-Lost-Demand-Engine-Used` back (`odoo_fallback` when Elasticsearch failed). Empty or shorter than 16 characters: headers ignored |

Timeouts are hard deadlines: each call runs in a small worker pool (4 threads; shopper searches have their own
8) and the caller stops waiting when the deadline passes. The client's own `request_timeout` does not cover
the DNS lookup, which takes ~8 s when the `elasticsearch` container is stopped.

## Tests

```bash
uv run shop test tools          # host: services/ (and the tools), no Odoo, no Elasticsearch
uv run shop test module         # container: Odoo tests on a throwaway database shop_test
uv run shop test module --es    # + the tests tagged `es`, against the running Elasticsearch
```

`shop test module` drops `shop_test` before and after each run (`--keep-db` keeps it); it never touches
the shop database. Odoo's output goes to `local/logs/test-module.log`.

After a Python change, restart Odoo (`docker compose restart odoo`): the repository is on the Windows
drive, so the server does not reload by itself (ADR-014).
