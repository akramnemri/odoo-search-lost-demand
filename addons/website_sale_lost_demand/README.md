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

## Layout

| Path | Content |
|---|---|
| `services/config.py` | Connection settings from the container environment (below), validated |
| `services/es_client.py` | `EsClient`: `cluster_status()` for the settings page, `guarded()` for shopper calls |
| `services/breaker.py` | Circuit breaker: closed → open after N failures → half-open trial → closed |
| `models/res_config_settings.py` | Computed, non-stored status fields on `res.config.settings` |
| `views/res_config_settings_views.xml` | The status block in the Website app of Settings |
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
| `LOST_DEMAND_ES_SEARCH_TIMEOUT_MS` | 500 | timeout of a shopper call, then fallback |
| `LOST_DEMAND_ES_STATUS_TIMEOUT_MS` | 2000 | timeout of each status request of the settings page |
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
