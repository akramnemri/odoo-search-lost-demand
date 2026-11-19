# Changelog

Milestone releases promoted from `develop` to `main` (`docs/ai/03_GIT_TESTING_PIPELINE.md` §2, §13). Details in the
milestone notes (`docs/report/notes/`).

## m2-catalog — 2026-11-19

### What works now
- `uv run shop data fetch esci` downloads Amazon ESCI (Apache-2.0) at a pinned commit, every file checked against its
  official SHA-256; `shop data build-slice` builds, from a fixed seed, 300 dev and 700 test queries, their 20,117
  relevance judgments and a 19,869-product catalog, byte-identical on every run.
- Prices, stock, categories (22 + Other) and 20 vendors are **synthetic** (ESCI has none), generated from the same
  seed and labelled synthetic in every report. Hidden products for the lost-demand test (protocol v1.1).
- The evaluation protocol is fixed by git tags before any result: `protocol-v1`, then `protocol-v1.1` (hidden sets).
- `uv run shop import catalog` imports the catalog into Odoo over JSON-2 (442 s for 19,869 products), with stock from
  real inventory adjustments, cost = vendor price, no sales tax, availability shown and out-of-stock orders refused;
  a second run changes nothing. `shop import verify` compares random products with their source rows. Module
  19.0.0.2.0 adds a Brand field. Snapshot `baseline-catalog` holds this shop.
- `uv run shop eval baseline-search` measures Odoo's own shop search: no result for 73 of 300 dev queries (24 %).
- Tests: 410 tools tests, 15 module tests including Elasticsearch.

### Known limitations
- Shop search still uses Odoo's own search (Elasticsearch from M3); no events, dashboards or lost-demand logic yet.
- Synthetic categories come from keywords: right for about 13 of 18 products in a manual review. No product images
  (ESCI has none).
- The search listing shows no "Out of stock" badge (Odoo's sold-out ribbon is not configured; product pages show it).
- Data and snapshots are local only (git-ignored); a new machine rebuilds them with `shop data fetch`, `build-slice`
  and `import catalog`.
- A clean start took 387 s at the M2 regression check (over the 5-minute target) while other projects' containers
  shared the Docker engine; on a fresh stack the cluster health is yellow (a Kibana 9.5 index asks for a replica).
- Shop-owner interview #1 (Task 1.6) not done yet; academic approval of protocol v1.1 not asked yet.

## m1-stack — 2026-11-14

### What works now
- The whole stack starts with one command (`uv run shop up`): Odoo 19 Community, PostgreSQL 16, Elasticsearch and
  Kibana 9.5.5 on the free Basic license, security on, ports on localhost only. Clean start healthy in 93 s.
- `uv run shop db create` builds the shop database (website, guest checkout, Demo payment provider, integration user
  with a JSON-2 API key); `shop snapshot save / restore` brings a state back in under a minute.
- Module `website_sale_lost_demand` 19.0.0.1.0 installs from Apps; Settings › Website shows the Elasticsearch status
  (reachable, version, license, health, circuit) and keeps working when Elasticsearch is down.
- `uv run shop doctor` checks the machine, the stack, Elasticsearch, Kibana and Odoo.
- Tests: 266 tools tests (`shop test tools`), 13 module tests including Elasticsearch (`shop test module --es`).
- CI on every pull request: lint, tools tests on Ubuntu and Windows, compose validation, and the module installed and
  tested on a fresh database against the real stack; all required on `develop` and `main`.
- Odoo can be debugged in Docker from PyCharm (`docs/setup/PYCHARM.md`, run configurations in `.run/`).

### Known limitations
- Shop search does not use Elasticsearch yet (M3); no events, dashboards or lost-demand logic yet (M4–M6); the catalog
  is empty until the ESCI import (M2).
- Python changes need an Odoo restart: the repository is on the Windows drive, so the container gets no file-change
  events (ADR-014).
- Docker debugging needs PyCharm Professional (trial until 2026-11-14 or 15; free JetBrains student license chosen,
  application by the supervisor).
- The doctor does not honour `COMPOSE_PROJECT_NAME`: with a second Compose project its port checks fail.
- Shop-owner interview #1 (Task 1.6) not done yet.
