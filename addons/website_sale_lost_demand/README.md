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
(Task 3.3), and product changes reach it only through a rebuild until Task 3.2. The module now depends on
`website_sale_stock` (stock quantities).

## Layout

| Path | Content |
|---|---|
| `services/config.py` | Connection settings from the container environment (below), validated |
| `services/es_client.py` | `EsClient`: `cluster_status()` and `product_index_status()` for the settings page, `admin_client()` for the rebuild, `guarded()` for shopper calls |
| `services/breaker.py` | Circuit breaker: closed → open after N failures → half-open trial → closed |
| `services/product_index.py` | Index definition loader, documents, versioned names, rebuild with count check and alias swap |
| `elastic/products/` | Index settings and analyzers, mapping, synonyms seed (JSON; the index is built from these) |
| `models/product_index.py` | `lost_demand.product.index`: reads products in batches of 500 and runs the rebuild |
| `models/res_config_settings.py` | Computed, non-stored status fields on `res.config.settings` |
| `models/product_template.py`, `views/product_template_views.xml` | The `brand` field and its place on the form |
| `views/res_config_settings_views.xml` | The status block in the Website app of Settings, product index status and rebuild button |
| `security/` | Groups; `ir.model.access.csv` (header only until the first model, M3) |
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

Timeouts are hard deadlines: each call runs in a small worker pool (4 threads) and the caller stops waiting
when the deadline passes. The client's own `request_timeout` does not cover the DNS lookup, which takes ~8 s
when the `elasticsearch` container is stopped.
| `LOST_DEMAND_ES_HEALTH_CACHE_SECONDS` | 10 | reuse of the last status |
| `LOST_DEMAND_ES_BREAKER_FAILURES` | 3 | consecutive failures that open the circuit |
| `LOST_DEMAND_ES_BREAKER_RESET_SECONDS` | 30 | wait before one trial call |

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
