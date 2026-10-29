# 01 — Project Context & Architecture

Act as the senior engineer responsible for keeping this architecture coherent.

This document is the authoritative description of what we build and how it is structured.
Read the sections relevant to the current task. If a task seems to require breaking a rule written here,
STOP and explain the conflict to the supervisor instead of working around it.

---

## 1. The project in one page

Final-year project (PFE), type ERP + Big Data. Source: *Project Specification: Search and Lost-Demand Analysis
for an Odoo Online Shop* (25 October 2026), stored in `docs/sources/`.

**Problem.** Small online shops lose sales in two ways their sales reports never show:
customers do not find what the shop has (typos, other words, poor ranking), and customers want what the shop
does not have (failed searches never reach the sales data, so restocking ignores them).

**Users.**

| User | Works in | Main need |
|---|---|---|
| Shopper | Shop website | Find products fast, even with typos |
| Shop manager | Kibana dashboards, Odoo reports | See what customers search for and do |
| Buyer | Odoo Purchase and Inventory | Know what to restock or add |
| Administrator | Odoo settings | Manage synonyms, indexing and the module |

**Objectives.** Search (Elasticsearch replaces the shop search) → Capture (every search, click, add-to-cart and purchase
becomes an event in Elasticsearch, visible in Kibana within seconds) → Detect (zero-result searches, high-demand
out-of-stock products) → Act (restock proposals, draft purchase orders, a "customers asked for" list) →
Prove (measured against the targets in §14 and `04_DATA_SEARCH_EVALUATION.md`).

**Functional requirements** (IDs are used everywhere: branches, commits, tests, docs).

| ID | Requirement | Priority |
|---|---|---|
| FR1 | Index Odoo products (name, description, category, brand, price, stock); a change shows in search within 1 minute | Must |
| FR2 | Rank results by relevance, tolerate typos, understand synonyms | Must |
| FR3 | Rank in-stock products above out-of-stock ones | Must |
| FR4 | Suggest searches and products while the shopper types | Should |
| FR5 | Filter results by category, brand, price range and stock | Should |
| FR6 | Log every search (query, number of results), click, add-to-cart and purchase to Elasticsearch | Must |
| FR7 | Kibana dashboards: live activity, purchase funnel, top searches, zero-result searches, demand by category | Must |
| FR8 | A scheduled job finds lost demand: repeated zero-result searches, high-demand products with no stock | Must |
| FR9 | Lost demand creates restock proposals or draft purchase orders in Odoo, approved by the buyer | Must |
| FR10 | A "customers asked for" list in Odoo, with search counts and trend; the buyer marks each item as handled | Should |
| FR11 | Virtual shoppers replay real ESCI queries against the shop | Must |
| FR12 | REES46 events stream into Elasticsearch at an adjustable speed | Must |
| FR13 | Semantic search with embeddings, as an option beside keyword search | Could |

**Non-functional requirements.**

| Area | Requirement |
|---|---|
| Speed | Search page under 1 s for 95 % of requests with 50 virtual shoppers; Elasticsearch query under 100 ms |
| Freshness | An event shows in Kibana less than 10 s after it happens |
| Volume | At least 10 million events on one laptop; dashboards load in under 5 s |
| Hardware | 16 GB RAM recommended; 8 GB works with reduced memory settings |
| Cost | Free tools only; Elasticsearch stays on its free Basic license |
| Reliability | If Elasticsearch is down, the shop falls back to Odoo's own search |
| Security and privacy | Only the Odoo server talks to Elasticsearch, with a password; events carry anonymous session IDs, no personal data |
| Setup | The whole stack starts with one Docker Compose command; code and setup guide live on GitHub |

---

## 2. Source documents and precedence

Precedence, highest first:

1. ADRs in `docs/decisions/` (most recent wins).
2. This file.
3. The specification PDF in `docs/sources/`.

The specification fixes the stack (Odoo 19 Community, PostgreSQL, Elasticsearch, Kibana, Python, PyCharm, Locust,
Docker Compose, Git/GitHub, optional sentence-transformers) and the order of work. Do not swap a tool without an ADR
approved by the supervisor.

---

## 3. Decisions (summary)

Each decision gets an ADR in `docs/decisions/ADR-XXX-short-title.md` during Milestone 0
(format: context, decision, consequences, revisit when).

| ADR | Decision | Main reason | Revisit when |
|---|---|---|---|
| 001 | All Odoo-side changes live in one module, `website_sale_lost_demand` | Spec: reusable add-on, no core changes, easy upgrade | Never likely |
| 002 | Odoo 19 Community, pinned to a dated official image tag; no move to Odoo 20 during the project | Spec: a year of fixes and tutorials; website code changes between versions | After the defense |
| 003 | One Docker Compose stack (PostgreSQL, Elasticsearch, a one-shot `es-setup`, Kibana, Odoo) used for development, demo and evaluation; settings per RAM profile | Spec: one command; one environment to debug | — |
| 004 | Elasticsearch and Kibana pinned to the same 9.x version; Basic license enforced and checked; security on (passwords); plain HTTP inside the Docker network; published ports bound to `127.0.0.1` | Spec: free, password-protected, laptop-only | Never during the project |
| 005 | Elasticsearch decides the **order**; Odoo decides the **truth** (visibility, price, stock). Search returns ranked IDs that Odoo re-filters | The index can be stale; Odoo access rules must always apply | — |
| 006 | Fallback: short timeouts + a per-process circuit breaker; on failure the shop uses Odoo's native search | Spec reliability requirement | — |
| 007 | Product index sync: transactional outbox in Odoo + near-real-time flush by cron trigger + bulk API; full rebuild into a versioned index with alias swap | FR1 (< 1 min), no lost updates, zero-downtime rebuild | If the spike in Task 3.2 shows trigger latency is too high |
| 008 | Event pipeline: same outbox pattern, flushed within seconds; final choice confirmed by the spike in Task 4.2 | FR6 + freshness < 10 s, never block the shopper | After the spike |
| 009 | One canonical event schema for every source (shop traffic, virtual shoppers, REES46 replay) in one data stream with a strict mapping; `source` and `traffic` fields separate them | Spec: same dashboards for both sources; clean analysis | — |
| 010 | The lost-demand job is an Odoo scheduled action that reads Elasticsearch aggregations and stores results as Odoo records; purchase documents are only created as drafts and need buyer approval | FR8/FR9; the buyer stays in control | — |
| 011 | Python tools form one `uv` project (`shoptools`, CLI `shop`); host Python pinned to the Odoo image's Python minor version | Reproducible versions on Windows, macOS and Linux; one entry point | — |
| 012 | Datasets: Amazon ESCI (Apache-2.0) for catalog, queries and relevance labels; REES46 (Kaggle) for volume; seeded synthetic enrichment; data never committed, manifest + checksums committed | Spec section 9 | — |
| 013 | Evaluation: separate dev (tuning) and test (reporting) query sets; NDCG@10 with ESCI gains; hidden-catalog protocol; every run recorded with metadata | Spec section 11; scientific validity | Protocol approval (Task 2.2) |
| 014 | Development: Odoo runs in Docker; debugging through PyCharm's Docker Compose interpreter; fallback = Odoo from source on the host with the rest in Docker (decided in Task 1.4) | One environment; spec requires PyCharm debugging | Task 1.4 result |
| 015 | Git: `feat/*` → `develop` → `main`, where `main` is always demo-ready and each accepted milestone is tagged | Protects supervisor meetings and the defense demo | — |
| 016 | Semantic search (FR13, Could): a small embedding service + `dense_vector`/kNN; hybrid fusion done in the module (RRF and linear retrievers are Enterprise-only) | Free license; laptop CPU | If FR13 is cut |
| 017 | No Kafka, Spark, Hadoop or cloud services | Spec: not needed at this volume on one machine | — |

---

## 4. Repository layout

```text
<repo>/
├─ CLAUDE.md
├─ README.md                        quick start (5 commands) + links to docs/setup
├─ compose.yaml                     the one-command stack
├─ .env.example                     every variable, no values that matter (passwords generated by `shop env init`)
├─ docker/
│  ├─ odoo/Dockerfile               FROM the pinned odoo:19.0 dated tag + pinned `elasticsearch` client
│  ├─ odoo/odoo.conf                development config (no secrets; secrets injected from env at start)
│  └─ es-setup/                     one-shot setup: passwords, roles/users, license check, templates
├─ addons/
│  └─ website_sale_lost_demand/     THE Odoo module (see §6)
├─ elastic/                         index templates, mappings, analyzers, ingest pipelines, ILM, synonyms seed (JSON, as code)
├─ kibana/                          data views and dashboards as saved-object NDJSON
├─ tools/shoptools/                 Python package: cli, doctor, data, importer, replay, eval
├─ tools/tests/                     pytest suite for the tools
├─ loadtest/                        Locust virtual shoppers + shopper model config
├─ scripts/bootstrap.ps1, bootstrap.sh   install uv if missing, then run the doctor
├─ data/                            git-ignored except README.md and manifest.toml (sources, versions, checksums, licenses)
├─ results/                         git-ignored raw runs; `results/summary/` (small CSV/MD/PNG) is committed
├─ docs/
│  ├─ ai/                           these prompts
│  ├─ decisions/                    ADRs
│  ├─ progress/STATUS.md, CHANGELOG.md
│  ├─ setup/                        VERSIONS.md, ENVIRONMENT.md, PYCHARM.md, TROUBLESHOOTING.md
│  ├─ evaluation/                   protocol.md, experiments.md, results.md
│  ├─ pilot/                        interview guides, consent text, anonymised notes
│  ├─ report/                       outline, milestone notes, figures list, drafts
│  ├─ sources/                      specification PDF (human)
│  └─ glossary.md
├─ .github/workflows/ci.yml
├─ pyproject.toml, uv.lock, .python-version
├─ .pre-commit-config.yaml, .gitignore, .gitattributes, .editorconfig
├─ .odoo-src/                       git-ignored shallow clone of Odoo 19.0, for reading and IDE navigation
└─ local/                           git-ignored machine report and scratch files
```

---

## 5. Runtime topology

### 5.1 Services (`compose.yaml`)

| Service | Image | Purpose | Published port | Notes |
|---|---|---|---|---|
| `db` | PostgreSQL (major supported by Odoo 19, pinned) | Odoo database | none | Not published: avoids clashes with a local PostgreSQL; tools never need it |
| `elasticsearch` | Elasticsearch 9.x (pinned) | Product index, event data stream | `127.0.0.1:9200` | Single node, security on, HTTP TLS off, `xpack.license.self_generated.type=basic`, heap from `.env`, replicas 0 |
| `es-setup` | Same image as Elasticsearch, or a small curl image | One-shot: wait for health, set `kibana_system` password, create roles and users, assert license = basic, apply `elastic/` templates and pipelines | none | Exits 0 when done; Kibana and Odoo depend on its success |
| `kibana` | Kibana, same version as Elasticsearch | Dashboards | `127.0.0.1:5601` | Can be skipped on 8 GB machines (`shop up --no-kibana`) |
| `odoo` | Our image `FROM` the pinned `odoo:19.0` dated tag | Shop, backend, module, scheduled jobs | `127.0.0.1:8069` | Addons bind-mounted for development; DB settings and secrets from env |
| `embedder` (profile `semantic`) | Small Python service | Query embeddings for FR13 | none | Only if FR13 is built |

Locust, the replay script and the evaluation harness run on the host through `uv run shop ...` and reach
Odoo on `127.0.0.1:8069` and Elasticsearch on `127.0.0.1:9200`.

Startup order: `db` and `elasticsearch` healthy → `es-setup` completed successfully → `kibana` and `odoo`.
Every long-running service has a healthcheck and `restart: unless-stopped`. Named volumes hold PostgreSQL data,
the Odoo filestore and Elasticsearch data.

### 5.2 Elasticsearch users and roles

| User | Used by | Privileges |
|---|---|---|
| `elastic` | `es-setup` only | Superuser. Password in `.env`, never used by the app |
| `kibana_system` | Kibana | Built-in |
| `odoo_app` | The Odoo module | Read/write on `shop-products*` and `shop-events*`, alias management for products, synonyms management if the API is used (verify required privileges) |
| `shop_tools` | Host tools (replay, evaluation) | Write on `shop-events*`, read on `shop-*` |
| Your own login | Kibana in the browser | A personal user created by `es-setup` (name in `.env`) with the built-in `editor` role: all Kibana features, read-only on data, so dashboards can be built in the UI (Task 4.5). Never `elastic` |

Spec rule: only the Odoo server talks to Elasticsearch on behalf of shoppers. The browser never calls Elasticsearch.

### 5.3 RAM profiles

Starting values, to be measured and corrected in Task 1.1. The doctor recommends a profile from the memory Docker can use.

| Setting | `lowmem` (8 GB laptop) | `standard` (16 GB laptop) |
|---|---|---|
| Memory available to Docker | 5–6 GB | 8–10 GB |
| Elasticsearch heap | 1 GB (512 MB minimum for tests) | 2 GB |
| Kibana | Started only when needed | Always on |
| Odoo workers | 0 (threaded) for development, 2 for load tests | 0 for development, 4 for load tests |
| Work on | Data slices, one week of REES46 | Full slice, one month of REES46 |

---

## 6. The Odoo module: `website_sale_lost_demand`

### 6.1 Structure

```text
website_sale_lost_demand/
  __manifest__.py        version 19.0.x.y.z; minimal depends (verify names in 19.0: website_sale, website_sale_stock, purchase_stock);
                         external_dependencies: {"python": ["elasticsearch"]}; license chosen by the supervisor
  services/              PURE PYTHON, no `odoo` import: config, ES client wrapper, circuit breaker, query builder,
                         event builder, query normalization, PII masking, demand scoring, fusion (FR13)
  models/                Odoo glue: product/stock triggers, outboxes, signals, proposals, synonyms, settings
  controllers/           overrides of website_sale routes (search, product page click, cart) — thin
  views/                 backend views and menus (signals, proposals, asked-for list, synonyms, index status)
  templates/             website QWeb inheritance (click tracking parameters, facets later)
  data/                  scheduled actions, default parameters (no secrets)
  security/              groups, ir.model.access.csv, record rules
  static/src/            minimal frontend code, only if a server-side solution is impossible
  tests/                 Odoo tests (unit with a fake ES service; integration tagged `es`)
```

Rule: anything that can be tested without Odoo goes into `services/` and is covered by fast pytest tests on the host.
Models and controllers stay thin and call services.

### 6.2 Configuration

- Connection settings and secrets come from the container environment (`.env` → compose → Odoo), read in one place
  (`services/config.py`). They are never stored in the Odoo database.
- Business settings (thresholds, windows, weights, schedule) are Odoo settings or `ir.config_parameter` values with
  defaults in `data/`, editable by the Administrator.
- The settings page shows read-only status: Elasticsearch reachable, version, license, product index alias and document
  count vs Odoo product count, outbox backlog, last lost-demand run.

### 6.3 Models (first version; names may be refined in the task plan)

| Model | Purpose | Key points |
|---|---|---|
| `product.template` (inherit) | Add `brand` (ESCI brand), index triggers | Write triggers enqueue reindex for changed templates only when indexed fields change |
| `stock.quant` / stock moves (inherit, verify the right hook in 19.0) | Stock changes enqueue reindex | Stock is the most frequent change; batch per template |
| `lost_demand.index.queue` | Product outbox | Template ID + operation; collapsed per template; flushed in bulk |
| `lost_demand.event.outbox` | Event outbox | Serialized event + attempts; flushed in bulk; bounded retention if Elasticsearch stays down |
| `lost_demand.run` | One execution of the lost-demand job | Window, thresholds, counts, duration, status: an audit trail and evaluation evidence |
| `lost_demand.signal` | A detected gap | Kind (`zero_result_query`, `unsatisfied_query` if approved, `out_of_stock_demand`), normalized query or product, counts, distinct sessions, trend, first/last seen, state |
| `lost_demand.proposal` | Restock proposal | Product, vendor, suggested quantity, reason (signals), state `draft → approved → ordered`, or `dismissed`; link to the draft RFQ |
| `lost_demand.asked_for` (FR10) | "Customers asked for" entry | Normalized query, counts, trend, candidate products, state `new → handled` or `ignored`, action taken |
| `lost_demand.synonym` | Synonym rule | Terms, type (equivalent / one-way), active; synced to the Elasticsearch synonyms set |

### 6.4 Security groups

- Buyer: Purchase user group (reuse the standard group) — proposals and asked-for list.
- Shop manager: read access to signals and runs.
- Administrator: settings, synonyms, index rebuild (reuse the settings/system group).
- Every model has access rights in `ir.model.access.csv`; record rules where data must be restricted.

---

## 7. Search flow (FR1–FR3, reliability)

```text
GET /shop?search=<q> (+ category/attributes/page)
 -> our override of the website_sale lookup (verify the exact method in 19.0 source)
 -> services: normalize + mask query, build ES query (tuned config), short timeout
 -> Elasticsearch: ranked product template IDs + total (+ aggregations later for FR5)
 -> Odoo re-filters the IDs with the standard website domain (published, website, company, active, sale_ok)
    and keeps Elasticsearch's order
 -> standard rendering (pagination, product grid) + search_id for click tracking
 -> search event written to the outbox (never blocking)

On ES error / timeout / circuit open:
 -> super() = Odoo's native search; event records engine = "odoo_fallback"; a warning is logged once per breaker opening
```

Integration points to locate in `.odoo-src/` before Task 3.3 (names differ between versions, so search, do not assume):

- the `/shop` route and the method that turns `search` into a product list (search for `def shop(`, `_search_with_fuzzy`,
  `_shop_lookup_products`, `_get_search_domain`);
- whether these routes are declared `readonly=True` in 19.0 (search for `readonly=`): a read-only request must not write
  to its own cursor, which matters for event logging;
- the search-bar autocomplete route used by the website (search for `autocomplete`), for FR4;
- the cart update methods and the order confirmation path (search for `cart_update`, `_cart_`, `action_confirm`), for events;
- how product types and storable products are modelled in 19.0 (e.g. a `type` + storable flag), for the importer and stock.

Evaluation hook: a request may choose the engine (`odoo`, `es_plain`, `es_tuned`, …) **only** when it carries the
load-test key header from `.env`; otherwise the parameter is ignored. This lets one harness compare engines through
the real rendering path (see `04_DATA_SEARCH_EVALUATION.md`).

---

## 8. Product indexing (FR1)

- Indexed fields: template ID, reference (ESCI product ID), name, description and bullet text, brand, color, public
  categories (names and IDs), list price, available quantity, `in_stock`, published flag, website IDs, update timestamp;
  later `popularity` (from events) and `embedding` (FR13).
- Index name `shop-products-v<N>` behind alias `shop-products`; mapping and analyzers from `elastic/`.
- **Incremental:** model triggers write template IDs to `lost_demand.index.queue` in the same transaction as the change,
  then request an immediate run of the flush scheduled action (cron trigger). The flush job collapses duplicates,
  reads current data from Odoo, sends one bulk request, deletes processed rows, and retries failures with backoff.
  Unpublished products stay in the index with `published=false` (the lost-demand matcher may need them); shop queries filter on it.
- **Full rebuild:** create `shop-products-v<N+1>`, bulk-load all templates, verify counts, swap the alias atomically,
  keep the previous index until the supervisor deletes it. Triggered by an admin button and by `uv run shop index rebuild`.
- **Consistency check:** settings page and doctor compare Odoo's indexable product count with the alias document count.
- Target: a product or stock change is visible in shop search within 60 s (measured, `04` §11.4).

---

## 9. Event capture (FR6)

| Event | Captured where | Key fields |
|---|---|---|
| `search` | Search override | `search.id`, raw query (masked, capped), normalized query, result count, page, filters, `took_ms`, engine |
| `click` | Product page request carrying `sid` (search ID) and `pos` (position) parameters added to result links | `search.id`, product, position |
| `product_view` | Product page without search context | product |
| `add_to_cart` | Cart update override | product, quantity |
| `purchase` | Order confirmation, inside the same transaction | order reference, product lines, amounts |

Rules:

- Events are built by `services/` and written to `lost_demand.event.outbox`; the flush job sends them with
  `op_type=create` and a fixed `_id` (event UUID) so retries never duplicate. Final mechanism confirmed in Task 4.2.
- If a route is read-only in 19.0, do not write to its cursor: use a short-lived separate cursor or another mechanism
  validated by the spike. Purchase events stay transactional (no order, no event).
- A shopper request never waits for Elasticsearch and never fails because event logging failed.
- `session.id` = HMAC-SHA256 of the Odoo session identifier with `EVENT_HASH_SECRET`; raw session IDs are never stored.
- Queries are capped (200 characters) and patterns that look like emails or phone numbers are masked before storage.
- `traffic` = `human` by default; `virtual` (Locust), `eval` (harness) or `probe` (freshness probes) only when the
  load-test key header is present. Lost-demand detection and default dashboards exclude `eval` and `probe`.
- If Elasticsearch is down, events wait in the outbox; rows older than a configurable retention (default 24 h) are dropped
  with a logged counter so the database cannot grow without limit.

---

## 10. Lost-demand detection and actions (FR8–FR10)

**Signals** (exact definitions, defaults and formulas in `04` §8; thresholds are settings):

1. **Zero-result queries:** normalized queries with result count 0, at least N searches and M distinct sessions in the window.
2. **Out-of-stock demand:** products with weighted demand (views, clicks, add-to-cart attempts) above a threshold while
   their current Odoo stock is zero or below.
3. **Unsatisfied queries** (proposed extension, needs supervisor approval in Task 2.2): queries whose searches returned
   results but got no click within a time limit. Needed for a meaningful hidden-catalog detection score.

**Job.** An Odoo scheduled action (default hourly, plus a "Run now" button) queries Elasticsearch aggregations on
`source = shop` events only (REES46 products are not in the Odoo catalog), upserts `lost_demand.signal` records keyed by
kind + normalized query or product, computes the trend (current window vs previous window), and records a `lost_demand.run`.
Re-running the job with the same window gives the same result (idempotent).

**Actions.**

- Out-of-stock demand for a product with a vendor → `lost_demand.proposal` with a suggested quantity from a documented
  heuristic (demand, vendor minimum quantity). The buyer approves → the module creates or extends a **draft** RFQ for that
  vendor. Nothing is confirmed automatically.
- Zero-result or unsatisfied query → `lost_demand.asked_for` entry, with candidate products from the full catalog
  (including unpublished ones) when a match exists. The buyer marks it handled: add a synonym, publish or restock a product,
  create a product, or ignore.
- Synonym added → synced to the Elasticsearch synonyms set → the next search finds the product without reindexing.

**The loop closes** when stock arrives in Odoo: the stock change reindexes the product, and the next search shows it in stock.

---

## 11. Data and tools pipeline (overview; details in `04`)

```text
ESCI (official repo, Git LFS) -> data/raw -> slice builder (seeded) -> catalog + dev/test/traffic query sets + qrels + hidden set
   -> synthetic enrichment (categories, prices, stock, vendors) -> importer -> Odoo -> product index
REES46 (Kaggle, human token) -> data/raw -> streaming reader -> canonical events (source=rees46) -> replay at chosen speed -> shop-events
Locust virtual shoppers (traffic query pool, shopper model) -> Odoo shop -> events (traffic=virtual)
Evaluation harness -> NDCG@10, detection, speed, freshness, volume -> results/<run-id>/ -> docs/evaluation/results.md
```

---

## 12. Security and privacy

- Passwords and keys are generated into `.env` by `uv run shop env init`; `.env` is git-ignored; `.env.example` lists names only.
- All published ports are bound to `127.0.0.1`. PostgreSQL is not published.
- The Odoo master password is set from `.env` (no default), database listing is disabled, the database name is fixed.
- Elasticsearch users follow least privilege (§5.2). The app never uses `elastic`.
- No personal data in events (§9). Synthetic accounts only. Real shop-owner material: consent + anonymisation.
- Dataset licenses are recorded in `data/manifest.toml` and respected (attribution in README and report).

---

## 13. Reliability and degradation

| Failure | What happens |
|---|---|
| Elasticsearch down or slow | Shop search uses Odoo's native search; events and index updates wait in the outboxes; settings page shows the outage |
| Kibana down | Dashboards unavailable; shop and module unaffected |
| Flush job failing | Outbox backlog grows; doctor and settings page show it; retries with backoff; bounded retention for events |
| Lost-demand job failing | `lost_demand.run` marked failed with a safe error; previous signals kept |
| Odoo restart | Outboxes persist in PostgreSQL; nothing lost |
| Disk almost full | Doctor warns before long jobs; replay and imports refuse to start below a free-space threshold |

---

## 14. Performance targets

| Target | Value | Measured by |
|---|---|---|
| Search page p95 with 50 virtual shoppers | < 1 s | Locust (`04` §11.3) |
| Elasticsearch search `took` p95 | < 100 ms | `took_ms` in search events (`04` §11.3) |
| Event to Kibana | < 10 s | Freshness probes (`04` §11.4) |
| Product change to shop search | < 60 s | FR1 probes (`04` §11.4) |
| Events stored | ≥ 10 million | REES46 replay (`04` §11.5) |
| Dashboard load | < 5 s | Volume protocol (`04` §11.5) |

Levers, in order: measure first; fix the slowest step (Odoo workers, query complexity, `_source` filtering, page size,
heap); never trade correctness or fallback for speed.

---

## 15. Out of scope / later

Real payments and customer data; recommendations ("customers also bought"); other languages (Elasticsearch supports them,
left for later); multi-server, cloud, Kafka, Spark, Hadoop; Elastic paid features; Odoo 20 migration.

---

## 16. Open questions for the supervisor (track answers in ADRs)

1. Team: one developer or a pair (binôme)? Who reviews pull requests?
2. GitHub repository URL and visibility; license for the code (an Odoo-compatible license such as LGPL-3 is usual for modules).
3. Hidden-catalog detection definition and the "unsatisfied query" signal (Task 2.2).
4. Default thresholds and windows for lost demand (after the first shop-owner interview).
5. Report language and template required by the university; key dates (milestone reviews, report deadline, defense).
6. Which laptop is the demo machine, and its RAM profile.
7. Shop owner(s) available for the two interviews and the pilot demo.
