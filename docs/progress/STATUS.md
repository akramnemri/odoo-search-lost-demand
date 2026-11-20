# STATUS

Updated: 2026-11-20 by agent session 9 — Task 3.3 (shop search through Elasticsearch, with fallback) implemented, PR open

## Current position
- Milestone: M3 — Search engine (FR1–FR3, fallback, synonyms). M2 released 2026-11-19 (PR #32 4f62925, release PR
  #33 merge commit 8c7558a, tag `m2-catalog`); M1 released 2026-11-14 (PR #22, f3926a1, tag `m1-stack`)
- M3 order: 3.1 → 3.2 → **3.3** → 3.4 → 3.5 → 3.6 → 3.7. Task 1.6 (interview) still open, in parallel
- Task: **3.3 — shop search through Elasticsearch, with fallback** — state: **implemented, automated checks
  passed; waiting for the supervisor's manual test** (plan accepted 2026-11-20: "go as the recommendations",
  after a second in-depth review)
- Branch / PR: `feat/es-shop-search` (from `develop` 85102c8) — PR to `develop` (number in the task report)
- Local checkout: on `feat/es-shop-search`; ESCI in `data/raw/esci/` (3 files, verified)
- Repository: https://github.com/akramnemri/odoo-search-lost-demand (public, default branch `develop`)

## Milestone 0 exit check (2026-10-28)
- `uv run shop doctor` (M0 sections): 30 OK, 5 WARN, 0 FAIL — WARN = 4 stack images not pulled, `.odoo-src/` missing
  (both expected before M1)
- `docs/setup/VERSIONS.md` approved by the supervisor (ADR-018 accepted)
- Scaffold, `shop` CLI, doctor and CI merged into `develop` (PRs #1–#5); CI green on `develop` after the merge
- CI green on PR #5: `lint`, `tools (ubuntu-24.04)`, `tools (windows-2025)`; failure demonstrated on PR #6 (closed)
- `main` still holds only the prompt pack: the first promotion `develop` → `main` is Task 1.7 (tag `m1-stack`)

## Environment
- Doctor: 55 OK, 1 WARN (free disk 33.6 GB), 0 FAIL, 2 SKIP — 2026-11-20 after the Task 3.3 live checks (one run
  about 2 min after restarting Elasticsearch showed 3 FAIL "no answer" on its Elasticsearch checks; the next run
  was clean, cluster healthy); 55 OK after the Task 3.2 manual test (new check `product
  changes waiting`) (54 OK earlier that day; 52 OK, 1 WARN, 3 SKIP on 2026-11-19) (72 GB on 2026-11-14 after the supervisor freed
  space)
- Stack: `uv run shop up|down|status|logs`; `compose.yaml` (project `odoo-search-lost-demand`); clean start from empty
  volumes healthy in 94 s; `shop up` from stopped 66–82 s; images pulled 2026-10-29 (2.34 GB compressed)
- Memory measured 2026-10-29 (no data yet), table in `01_ARCHITECTURE.md` §5.3: standard stack ≈ 3.9 GiB peak
  (Elasticsearch 2.7/3 GiB, Kibana 1.16/1.5 GiB); lowmem ≈ 2.7 GiB (Kibana 0.9/1 GiB); lowmem without Kibana ≈ 1.6 GiB
- RAM profile: `standard` — 16.9 GB RAM; Docker 8.3 GB / 4 CPUs (`.wslconfig` memory=8GB, decimal GB as in the docs),
  shared with another project's running stack (≈ 0.45 GiB used)
- Stack versions (approved): Odoo `19.0-20261015` (Python 3.12.3, confirmed 2026-10-29), PostgreSQL `16.15-trixie`, Elasticsearch/Kibana `9.5.5`,
  client `elasticsearch==9.5.1`, host Python 3.12 — `docs/setup/VERSIONS.md`
- Tools: Git 2.51, Git LFS 3.7, gh 2.102 (logged in), uv 0.13.6, Docker Desktop 4.60.1 (kept, no update), Compose v5.0.2,
  WSL 2.6.3, PyCharm 2026.2.3 (Pro **trial until 2026-11-14**). `vm.max_map_count` = 1048576. Ports 8069/8072/9200/5601/8089
  free (native Odoo 17 service stopped, start type Manual)
- Repository: Windows drive, path with spaces (`...\Lost Demand (ERP+ Big Data)\odoo-search-lost-demand`), kept by
  supervisor decision; repository-local git `core.autocrlf=false`, `core.longpaths=true`; `.gitattributes` forces LF
- Agent note: the Claude desktop app redirects its writes under `%APPDATA%`/`%LOCALAPPDATA%` to a private folder
  (MSIX). Anything that must be visible outside the app (managed Python, global tool installs) is installed by the
  supervisor from a normal terminal (`docs/setup/TROUBLESHOOTING.md`)

## Data state
- ESCI: in `data/raw/esci/` (1,161,827,075 bytes, Apache-2.0, `amazon-science/esci-data@7916cdf`), size and SHA-256
  verified against the pins, recorded in `data/manifest.toml` (2026-11-14; the download took 86 min at 0.1–0.5 MB/s).
  Profile `results/summary/esci-profile.md`: `us`/`small_version = 1` = 20,888 train + 8,956 test queries, 601,354
  judgments (median 16 per query), 482,105 distinct judged products; all small_version cells: 48,300 queries,
  1,118,011 judgments (matches ESCI's published figures). Profile: 8 s, peak 277 MiB working set
- Slice (Task 2.3a, 2026-11-14): `data/processed/` holds dev 300, test 700, test-typo 700 (17 unchanged), qrels
  20,117, catalog **19,869 products**; 0 test candidates removed as duplicates of dev; every query has an E judgment.
  Two runs gave identical SHA-256 (`results/summary/slice-report.md`); 12–21 s, peak 639 MiB working set.
  Shop catalog (Task 2.3b, same command): `products.parquet` 19,869 with SYNTHETIC category (91.5 % not "Other"),
  price (median $23.99), stock, 20 vendors; hidden-test 140 test queries → 1,081 products (5.4 %), hidden-dev 60 dev
  queries → 508 (2.6 %), out-of-stock 1,828; `results/summary/enrichment-report.md`. Full build 16–24 s, peak
  687–754 MiB; two runs identical, 2.3a hashes unchanged
- REES46: not yet (13.67 GB; usage rules in ADR-012)
- Odoo source copy: `.odoo-src/odoo/` from `odoo:19.0-20261015` (Odoo `19.0.post20261015`), 38,948 files, 409 MB,
  translations (`*.po`) excluded, 19 font symlinks skipped; copied in 320 s; provenance in `.odoo-src/SOURCE.toml`
- Odoo database: `shop`, recreated 2026-11-06 by `shop db reset` in 87 s (supervisor-approved, to give the integration
  user the "Products / Create" group); 86 modules, no demo data, company and website "Lost Demand Demo Shop", USD,
  generic chart of accounts, en_US, Demo payment provider (test), guest checkout on; integration user
  `shop_integration` with a JSON-2 API key in `.env`; 0 sale orders. **Full catalog (Tasks 2.4a–b, 2026-11-15):
  19,869 products** (all of `products.parquet`), published, no tax, cost = vendor price, one vendor price line each;
  23 public + 23 internal categories under "Shop catalog"; 20 synthetic vendors; **stock**: 18,041 products in stock
  (3–150 units, 18,041 done inventory moves and quants in WH/Stock), 1,828 at 0 (the out-of-stock set); 0 journal
  entries (periodic valuation). Every product: `show_availability=True`, `allow_out_of_stock_order=False`
  (out-of-stock products show "Out of Stock" and cannot be added to a cart; ≤ 5 units show "N Units in stock")
- Snapshots (`local/snapshots/`): **`baseline-catalog`** (2026-11-15, re-saved with `--force` after the
  availability follow-up, 31.9 MB, saved in 12 s: the full catalog
  above — **the baseline every campaign restores**, protocol §8); `before-2-4a` (2026-11-14, 19.8 MB: module
  19.0.0.1.0, no catalog); `baseline-empty` (2026-11-06, 6.9 MB: 1 product, module not installed);
  `after-1-2a-manual-test` (2026-11-06, older: its integration user cannot create products)
- Module `website_sale_lost_demand` **19.0.0.5.0** in `shop` (Task 3.3 branch, upgraded 2026-11-20 after
  `uv run shop env init` added `LOAD_TEST_KEY` to `.env` and `docker compose up -d odoo` recreated the container
  so it reads `LOST_DEMAND_LOAD_TEST_KEY`; then `docker compose restart odoo`). 19.0.0.4.0 (upgraded 2026-11-20 with `odoo module upgrade`, 10 s,
  then `docker compose restart odoo`; 19.0.0.3.0 earlier that day, 19.0.0.2.0 since 2026-11-14). The upgrade logs
  three "Missing not-null constraint on lost_demand.index.queue.*" warnings from its first registry load (code
  ahead of the table); the columns are NOT NULL afterwards and a fresh install logs none. Snapshot `baseline-catalog` still holds
  19.0.0.2.0: after restoring it, upgrade the module again (same catalog data; not re-saved without the supervisor); 19.0.0.1.0 was installed from Apps on 2026-11-06 (browser re-test of 1.3);
  snapshot `baseline-empty` is the state without it. `shop` also holds an archived throwaway user `ld_tester`
  (internal, Website designer) from that test. `shop test module` uses a throwaway `shop_test`, dropped after
  each run
- Elasticsearch: users `odoo_app`, `shop_tools`, personal Kibana user `supervisor` (built-in `editor` role)
- Product index (Tasks 3.1–3.2, 2026-11-20): alias `shop-products` → **`shop-products-v5`** (definition version 2:
  `free_qty`), 19,869 documents (= Odoo's 19,869 products to index: active, `sale_ok`), 1,828 with
  `in_stock=false`; kept in sync by the outbox (empty after the probe run). Old indices `shop-products-v1..v4`
  (~70 MB each; v1–v4 are definition 1) kept — delete them only on the supervisor's instruction. Rebuilds: v1 17 s,
  v2 14 s, v3 21 s (CLI), v4 28 s (Settings button), v5 17 s (CLI). Synonyms set `shop-synonyms`: created empty
  by the first rebuild. The probe runs and the manual test left 64 inventory moves in `shop` on 2026-11-20
  (each stock change undone by a second adjustment); every price and quantity is back to its value
- Events stored: 0

## Last completed tasks
- 0.1 — Machine inventory (read-only) — confirmed 2026-10-28 (no PR: before the repository existed)
- 0.2 — Version matrix, ADR-001…018, STATUS, glossary — merged 2026-10-28 (PR #1)
- 0.3 — uv, Python 3.12, ENVIRONMENT.md — merged 2026-10-28 (PR #2)
- 0.4 — Repository scaffold, uv project, `shop` CLI skeleton, pre-commit, LGPL-3.0, spec PDF — merged 2026-10-28 (PR #3)
- 0.5 — `shop doctor`, bootstrap scripts, TROUBLESHOOTING.md — merged 2026-10-28 (PR #4)
- 0.6 — CI (`lint`, `tools` on Ubuntu + Windows), `shop lint`, repository settings — merged 2026-10-28 (PR #5)
- PRs #1–#5 were merged by the agent on the supervisor's explicit instruction
- 1.1a — Compose stack, Odoo image, es-setup, `shop env init` — merged 2026-10-29 (PR #8, agent on the supervisor's
  instruction, after CI and SonarCloud were green)
- 1.1b — `shop up/down/status/logs`, doctor `stack`/`elastic`/`kibana`, memory measurement, Kibana limits raised —
  merged 2026-10-29 (PR #9, agent on the supervisor's instruction, after CI and SonarCloud were green)
- 1.4a — `shop odoo-src` (tar stream from the pinned image, stamp, doctor check) — merged 2026-10-29 (PR #11, agent on
  the supervisor's instruction, after CI and SonarCloud were green)
- 1.2a — `shop db create|reset` (Odoo `db init`, `module install`, configure script in `odoo shell`, JSON-2 check),
  `db_name` removed from `odoo.conf` — merged 2026-11-06 (PR #12, agent on the supervisor's instruction after the
  manual test passed and CI and SonarCloud were green)
- 1.2b — `shop snapshot save|restore|list` (pg_dump/pg_restore 16 in the `db` container, filestore tar, checksums,
  restore into a temporary database then swap) — merged 2026-11-06 (PR #13, agent on the supervisor's instruction
  after the manual test passed and CI and SonarCloud were green)
- 1.2a follow-up — integration user gets `product.group_product_manager`; `shop db create` checks create rights on
  `product.template` and `product.supplierinfo` over JSON-2 (`has_access`) — merged 2026-11-06 (PR #14, 85ec82a)
- 1.3 — module skeleton: `services/` (config, ES client with status cache, circuit breaker), read-only Elasticsearch
  status in Website settings, group "Lost Demand / Shop manager", `shop test tools|module [--es]`, doctor `odoo` —
  manual test passed 2026-11-06; squash-merged 2026-11-06 (PR #15, 6da9cab). Browser re-test (2026-11-06, built-in browser): the module was
  not yet in `shop`'s Apps list (the running server had cached "manifest not found"); after `docker compose restart odoo`
  it installed from Apps; status block correct with Elasticsearch up, stopped (Unreachable, page still opens) and
  started again; a non-admin user (throwaway `ld_tester`, archived afterwards) gets Access Error on Settings.
  It found a timeout gap, fixed in PR #15 (supervisor, 2026-11-07): with the `elasticsearch` container stopped,
  resolving its name takes 8 s in the `odoo` container (Docker DNS times out) and the client's `request_timeout`
  does not cover DNS, so a status check took 7.7 s. Every call now runs in a 4-thread pool with a hard deadline
  (`EsClient._within`): the stopped-container check takes 2.09 s (status timeout 2 s), recovery 0.31 s

- 1.4b — merged 2026-11-14 (PR #16, 067b772); manual test passed 2026-11-13 — `docs/setup/PYCHARM.md`, `.run/` (`Odoo (debug)`, `Odoo module tests`, `tools tests`);
  ADR-014 findings. A PyCharm run replaces the `odoo` service container (`docker compose up` + PyCharm's generated
  override; entrypoint kept, 8069 published; `uv run shop up` afterwards); its helper containers use `docker compose
  run` with the entrypoint cleared, and the debug parameters also work that way (`--entrypoint ""` check). Supervisor's
  setup (2026-11-07, PyCharm log): interpreter `Odoo 19 (Docker Compose: odoo)` created 01:19, Python 3.12, helpers
  image 163 MB, also the project interpreter; first Run (not Debug) of `Odoo (debug)` at 01:53 started Odoo in 5 s.
  PyCharm had dropped that interpreter from the `.run/` Odoo configurations (loaded at 00:59, before it existed) and
  turned on "debug just my code": both restored/turned off. Scripted `pdb` check in a throwaway container: breakpoint
  at `res_config_settings.py:60` and step into `orm/environments.py::Environment._` work. Path mappings and the PyCharm
  breakpoint itself not verified yet. First Debug (02:11): no stop, although the compute ran (its Elasticsearch
  calls are in the log): PyCharm maps only `<repo>` ↔ `/opt/project` (`IDE_PROJECT_ROOTS`), the module ran from
  `/mnt/extra-addons`. Fix: both Odoo configurations load it with `--addons-path=/opt/project/addons`. Debug parameters: `--limit-time-real=0` (threaded
  Odoo reloads the server when a paused request passes 120 s, `odoo/service/server.py`, `ThreadedServer.process_limit`),
  `--max-cron-threads=0`

- 1.4b follow-up — merged 2026-11-14 (PR #18, 7661b5f): PyCharm `Odoo module tests` run passed (10 tests, 0 failed, exit code 0). Then
  `shop test module` refused to start ("service odoo is not running and healthy") although `odoo-1` was healthy:
  `parse_ps` kept one container per service and PyCharm's exited `docker compose run` helpers (service `odoo`, label
  `com.docker.compose.oneoff=True`) replaced it. `parse_ps` now skips one-off containers (`shop status`, doctor and
  `shop test module` all use it)

- 1.5 — merged 2026-11-14 (PR #19, 290ccef) — CI jobs `compose` (`shop env init --profile lowmem`, `docker compose config --quiet`) and
  `module` (pull + build, `shop up --no-kibana`, `shop test module --es`; logs printed on failure). Real compose stack,
  not service containers (supervisor, 2026-11-14). Odoo 19 exits non-zero when a test fails
  (`odoo/service/server.py::preload_registries`, `rc += 1`); `shop test module` also checks the summary line.
  Locally: `shop test module --es` 13 tests in 108 s. First CI run failed: BuildKit did not tag the Odoo base image, so
  `shop up` reported it missing (the job now pulls it by name from the Dockerfile); SonarCloud S8541/S8544 on `uv`
  calls (all now `--locked --no-build`). Then green: `module` 3 min 16 s (13 tests in 76 s). Manual test, draft PR #20
  (closed, not merged): a wrong assertion made `module` fail ("1 failed … of 13 tests", `test_healthy_cluster`, run
  43536647116); the revert passed (run 43537104351)
- Doctor fix — merged 2026-11-14 (PR #25, 0e71571): `stack.project_name` honours `COMPOSE_PROJECT_NAME`
  (environment, then `.env`), so the doctor recognises our containers under another project name
- 1.7 — released 2026-11-14 (PR #21 7a95a54, release PR #22 f3926a1, tag `m1-stack`) — regression gate items 1–2 on `develop` 290ccef, 2026-11-14, in an isolated worktree with its own
  `.env` and Compose project `odoo-search-lost-demand-regress` (empty volumes, removed afterwards with `down -v`,
  supervisor-approved; the shop database untouched): clean start healthy in 93 s; license basic; `shop db create` 89 s;
  module install 7 s (19.0.0.1.0); `shop test module --es` 13 passed in 97 s; snapshot restore 38 s. Doctor on the
  regress stack: 3 port FAILs only because the doctor ignores `COMPOSE_PROJECT_NAME`; on the real stack afterwards
  50 OK, 0 WARN, 0 FAIL. Guest checkout not repeated (last checked in 1.2a). `docs/report/notes/M1.md`,
  `docs/progress/CHANGELOG.md`
- 2.1 — merged 2026-11-14 (PR #23, 29c3563); manual test passed (supervisor) — `shop data fetch esci [--dry-run] [--yes]` (`tools/shoptools/data/`): files from the repository's
  Git LFS storage (media.githubusercontent.com) and raw files at the pinned commit, no git clone in `data/`; resumable
  `.part` + Range, size and SHA-256 checked against the pin before the rename; `data/manifest.toml` written atomically
  (sorted, first download date kept). `shop data profile esci` → `results/summary/esci-profile.md` (aggregates only,
  column batches). Doctor section `data` (was a placeholder): size, Parquet markers, LFS pointer detection, manifest;
  WARN before the fetch. New dependency `pyarrow==26.0.0` in a default `data` uv group. detect-secrets flags SHA-256
  values: marked `pragma: allowlist secret` (pins, manifest lines, tests)

- 2.2 — merged 2026-11-14 (PR #24, 5689f1e), tag **`protocol-v1`** (annotated, on 5689f1e): `docs/evaluation/protocol.md`
  approved by the supervisor (decisions D1–D11, all as recommended) after a review that added: dev/test hidden sets
  (thresholds chosen on dev), a negative-control campaign, seed and noisy-shopper robustness runs, a time-to-detection
  curve, a test-typo set, breakdowns incl. a vocabulary-mismatch (synonym) subset, condensed NDCG, effect sizes, Holm
  correction, dev/test duplicate removal, E7 resilience, interview ratings, pre-registration. ADR-013 Accepted.
  Academic supervisor's approval: not asked yet (the supervisor's call, D11)

- 2.3a — merged 2026-11-14 (PR #26, 506ae13, squash, by the agent on the supervisor's instruction after all
  required checks and the SonarCloud gate were green); manual test passed 2026-11-14, run by the agent at the supervisor's request: dry run, two real
  builds with identical output SHA-256 (also equal to `sha256sum` and the manifest; the committed report unchanged),
  and 11 protocol checks recomputed from the raw ESCI file without the builder's code (sizes, splits, texts, dev/test
  disjoint by id and normalized text, qrels = all judgments, gains, catalog = judged products, titles, typo
  coverage), all PASS; 15 random typo rows look plausible. SonarCloud's gate failed on the first push (7 new
  findings: redundant exception, typo-map complexity, composite test assertions); fixed, output hashes unchanged —
  `shop data build-slice [--dry-run]` (`tools/shoptools/data/slice_builder.py`, config `slice.toml`), shared
  `normalize_query` (`normalize.py`, 04 §8.1) and typo model (`typos.py`, protocol §6.3, reused by Locust in M5).
  Seed streams = SHA-256(`<seed>:<label>`) → `random.Random`. Inputs checked against the pinned SHA-256; the manifest
  is deleted first and written last. Fix during the task: pyarrow pre-buffers a whole row group (ESCI files have one),
  1.57 GiB peak; `pre_buffer=False` + 8 MiB buffered stream → 639 MiB, same output hashes. 40 new tests (325 total)

- 2.3b — merged 2026-11-14 (PR #27, 27640d6, squash, by the agent on the supervisor's instruction after all checks
  and the SonarCloud gate were green); annotated tag `protocol-v1.1` on 27640d6 (supervisor's go); manual test passed 2026-11-14, run by the agent at the supervisor's request: dry run, two real
  builds with identical SHA-256 for all 10 outputs (also equal to the build before the SonarCloud fixes; committed
  reports unchanged); 18 random products reviewed: prices, stock and vendor terms plausible, categories right for
  about 13 of 18 (misses from ambiguous bullet-point words: barstools → Beauty, a pillow → Electronics, a jersey →
  Party, a plant pot → Kitchen). SonarCloud's gate failed on the first push (3 findings: a lambda in a loop,
  `dict.fromkeys`, a self-comparing test assertion); fixed, hashes unchanged — step 5 of `shop data build-slice`:
  `enrichment.py` (keyword categories from `categories.toml`, 22 + Other, keyword lists written from dev products
  only, 92.5 % coverage on dev; log-normal prices per category in cents ending .99; log-uniform stock 3–150; vendor
  from a hash of the normalized brand; vendor terms; HTML-free descriptions capped at 2,000 characters),
  `hidden_sets.py` (protocol v1.1 §4, B2: hidden queries stratified by the majority category of their E products,
  largest remainder; hidden-dev excludes dev queries sharing an E product with hidden-test; out-of-stock among E
  products of non-hidden queries), `shop_catalog.py` (tables, statistics, report). Protocol v1.1 written (§4, §10,
  D12, "Changes"), ADR-013 and `04` §3–4 updated. Speed-up during the task: keyword index + cached word folding +
  no HTML parser on plain text, step 23 s → 8 s, same hashes. 41 new tests (366 total). Independent check on the
  real outputs (pyarrow only): 11 rules PASS

- 2.4a — merged 2026-11-14 (PR #28, 53b3958, squash, by the agent on the supervisor's instruction after all checks
  and the SonarCloud gate were green). Manual test passed 2026-11-14, run by the agent at the supervisor's request:
  built-in browser — `/shop?search=windex` (2 results, prices, descriptions), a product page ($36.99, no tax, Add to
  cart, category in the breadcrumb), a category page; backend over JSON-2 — `brand` stored and on the form, 2,000
  published, 0 with a tax, 1,809 with a brand (191 brandless in the source), 2,000 vendor lines, 20 vendors, 23 + 23
  categories; the only other referenced product is Odoo's unpublished "Standard delivery"; re-run 0 created, 0
  updated. No product images (ESCI has none). SonarCloud: gate OK, 4 code smells left for 2.4b — module 19.0.0.2.0 (`brand` on
  `product.template`, on the form after the category; 2 new Odoo tests, `shop test module --es` 15 passed in 164 s);
  `uv run shop import catalog [--limit N] [--dry-run] [--batch-size N]` (`tools/shoptools/catalog_import.py`,
  ADR-019): JSON-2 as the integration user, lookups by `default_code`/`ref`/name with `active_test=False`, only
  missing records created and only differing fields written; `odoo_id_map.parquet`. `json2_call` now has a timeout
  parameter and keeps Odoo's error message; `shop db create` checks create rights on 6 models. Real runs on `shop`:
  200 products in 1.5 s, 2,000 in 16 s (8 ms per product → full catalog ≈ 2.5 min, far under the 30-minute switch
  condition); second runs 0 created, 0 updated; 10 random products match their source rows; `/shop?search=`, a
  product page and a category page answer 200, price shown without tax. Bug found and fixed on the real run: Odoo's
  HTML sanitizer stores `'` and `"` unescaped, so 7 of 200 products were rewritten on every run; quotes are no longer
  escaped and HTML descriptions are compared by their decoded text. 12 new tool tests (378 total)

- 2.4b — merged 2026-11-15 (PR #29, cb00eaa, squash, by the agent on the supervisor's instruction after all checks
  and the SonarCloud gate were green, 0 open findings). Manual test passed 2026-11-15, run by the agent at the
  supervisor's request: built-in browser — "running shoes" 93 results with category filters, the Shoes filter
  (4 pages), a product page with Add to cart; backend over JSON-2 — Nike Air Max 95 price, cost, stock 13 and brand
  equal the source, one done inventory move of 13 into WH/Stock; `shop import verify` 10/10 and 50/50 (seed 7); full
  re-run 35 s with nothing created, updated or adjusted — `shop import catalog` adds cost
  (`standard_price` = vendor price) and stock by a real inventory adjustment per batch (`stock.quant.create` in
  `inventory_mode`, then `action_apply_inventory`; only products whose quantity differs; a conflict answer stops the
  run); `uv run shop import verify [--sample N] [--seed S]` (seeded stream `import-check`, all fields + stock);
  `results/summary/catalog-import.md` per real run (committed: the full import's record); SonarCloud's 4 code smells
  from 2.4a fixed (model-name constants, `product_changes` split); `snapshot.git_sha` made public. Real runs on
  `shop`: the 2,000 existing products updated with cost + stock in 151 s (individual writes: 75 ms per product);
  1,000 new products with stock ≈ 31 ms per product; **full import 442 s** (16,869 created, 15,287 stock
  adjustments, 21.9 ms per product, batch median 5.0 s, max 7.4 s); **second full run 40 s, 0 created, 0 updated,
  0 adjusted**; `shop import verify` 10 of 10 match; counts in Odoo match (18,041 in stock = moves = quants, 1,828 at
  0, cost on all, tax on none, 0 journal entries); snapshot `baseline-catalog` 31.9 MB. 9 new tool tests (387 total)
- 2.4b follow-up — merged 2026-11-15 (PR #30, 6ac56a6, squash, by the agent on the supervisor's instruction after all
  checks and the SonarCloud gate were green, 0 findings). Manual test passed 2026-11-15, run by the agent: built-in
  browser — the out-of-stock Giftgarden shelf is findable in search, its page shows "Out of Stock" and "Get notified
  when back in stock" with Add to cart hidden (the search listing shows no badge: Odoo's sold-out ribbon is not
  configured, possible FR3 work in M3); 19,869 published, all with availability shown and out-of-stock orders refused,
  1,828 at 0; `shop import verify` 20/20 (seed 11); full dry run: nothing to change — importer sets
  `show_availability=True` and `allow_out_of_stock_order=False` (website_sale_stock) on every product; identical
  changes in a batch go out as one `write` (all 19,869 products updated in 122 s instead of one call each); the
  record `results/summary/catalog-import.md` is written only by a run that changed something (it now holds this
  update run; the first full creation is in cb00eaa). Real runs: dry run listed only the two new fields (600-product
  sample), update 122 s, second run 66 s with 0 changes and the record untouched, `shop import verify` 10/10; built-in
  browser: an out-of-stock product shows "Out of Stock" with Add to cart hidden, an in-stock one (13) keeps Add to
  cart, one with 4 units shows "4 Units in stock". `baseline-catalog` re-saved. 3 new tool tests (390 total)
- 2.6 — merged 2026-11-19 (PR #32, 4f62925, squash, after the supervisor's manual test); M2 released the same day:
  release PR #33 (`develop → main`, merge commit 8c7558a), annotated tag `m2-catalog` on it — `baseline_search.py`: the
  5 SonarCloud findings of 2.5 fixed (regex without backtracking, outcome constants, `load_hand_picked` split, plain
  `if` for length buckets); `--no-dev` writes its run folder only and leaves `results/summary/baseline-search.md`
  unchanged. `shop import verify --limit N` draws from the first N products like `import catalog --limit N` (the
  gate found that verify failed 0/10 after a partial import), with a hint when products are missing. 6 new tool
  tests (410 total). Regression gate items 1–3 on 2026-11-19 in an isolated worktree (Compose project
  `odoo-search-lost-demand-regress`, `down -v` afterwards, supervisor-approved; the shop database untouched): clean
  start 387 s (over the 5-minute target; ~17 containers of other projects on the engine, Elasticsearch 2 min 43 s);
  license basic; doctor 48 OK, 5 WARN (disk 37 GB, cluster yellow, ESCI raw files absent in the worktree), 0 FAIL;
  `shop db create` 267 s; module install 8 s (19.0.0.2.0); `shop test module --es` 15 passed in 185 s; snapshot
  save 11 s, restore 113 s then 40 s; `import catalog --limit 500` twice (second: no change); `verify --limit 500`
  10/10. Extra: full import 682 s, second run 38 s with no change, `verify --sample 50` 50/50; `shop eval
  baseline-search` on the clean stack: every table row identical to the committed run. Real stack afterwards:
  healthy in 104 s, doctor 52 OK, 1 WARN (disk), 0 FAIL, 19,869 products published. Details in
  `docs/report/notes/M2.md`
- 2.5 — merged 2026-11-15 (PR #31, d15bebd, squash, by the agent on the supervisor's instruction after all checks
  and the SonarCloud gate were green; 5 code smells left for 2.6). Manual test passed 2026-11-15, run by the agent:
  note and table consistent; built-in browser — "royal blue bedspreads" no result, "royal blue bedspread" 3 results,
  "squritle" shows Odoo's "Showing results for"; re-run of the 20 queries (27 s) identical to the committed rows (the
  `--no-dev` re-run replaced the table, restored by hand; fixed in 2.6) — `uv run shop eval baseline-search
  [--no-dev]` (`tools/shoptools/eval/baseline_search.py`): real `/shop?search=` pages (http mode), result count,
  Odoo's similar-word fallback, page-1 products mapped to ESCI ids; 20 hand-picked queries with controls
  (`docs/report/notes/baseline-queries.toml`, typo / vocabulary / plural / brand / long, dev data only, test queries
  and test-judged products refused by the script) + all 300 dev queries; run folder with `run.json`; generated table
  `results/summary/baseline-search.md`; note `docs/report/notes/baseline-search.md` (how Odoo 19 search works, with
  code references; findings; screenshot list; limits). Published run from a clean checkout at 5bb9e2f (a first run
  on uncommitted code was discarded; the table keeps a "-dirty" mark when that happens). 14 new tool tests (404)

- 3.1 — merged 2026-11-20 (PR #34, squash 7a393ca); manual test passed 2026-11-20, run by the agent: CLI rebuild
  into v3 in 21 s; alias and count checked through the API as `shop_tools` (Kibana sign-in not used); Settings ›
  Website block "In sync" 19,869/19,869 and its "Rebuild product index" button built v4 in 28 s; doctor
  `product index alias` and `product index count` OK. What was built: index definition as
  JSON in the module (`addons/website_sale_lost_demand/elastic/products/`: settings and analyzers of `04` §5,
  strict mapping without `color` — Odoo has no colour field —, empty synonyms seed); `services/product_index.py`
  (pure: definition loader, documents, versioned names, rebuild = synonyms set if missing → `shop-products-v<N+1>`
  → bulk 500 per request → refresh → count must equal both the documents sent and Odoo's count → one `_aliases`
  call; on any failure the alias stays, the half-built index is kept); `models/product_index.py`
  (`lost_demand.product.index`, abstract: reads active `sale_ok` templates in batches of 500, stock from
  `qty_available`, private `_rebuild()` for administrators/superuser); Settings › Website: index status (alias,
  documents vs. products) and "Rebuild product index" button; `uv run shop index rebuild [--check]` (`odoo shell`
  in the container; `--check` = the doctor's count check); doctor: `product index alias` (elastic) and
  `product index count` (odoo, psql count vs. alias count); module 19.0.0.3.0 depends on `website_sale_stock`.
  Synonym sets verified on the basic cluster (empty set accepted; a rule added later applied without reindex),
  recorded in `docs/setup/VERSIONS.md`. Tests: 441 tools (+31), 27 module (+12, 3 of them `es`, on test-only
  `shop-products-test*` indices removed after each test)

- 3.2 — merged 2026-11-20 (PR #35, squash 85102c8, on the supervisor's "merge" after CI). **Manual test passed
  2026-11-20, run by the agent** on the
  supervisor's request ("do the manual test for me"); the Odoo backend sign-in was not used (the agent enters no
  passwords), so backend steps ran through the same server code: (1) product 4242 set to 0 on hand by an
  inventory adjustment over JSON-2 (what "On Hand › Apply" calls) → index `free_qty 0`, `in_stock false` after
  0.63 s; the shop's own availability route `/website_sale/get_combination_info` gave `free_qty 0`, not orderable;
  (2) Settings fields read in `odoo shell` as the admin user: "Reachable", "basic (active)", "In sync" on
  `shop-products-v5` 19,869/19,869, "Up to date"; scheduled action active, every 1 minute; the form view holds
  the new block; (3) Elasticsearch stopped: price saved in 0.11 s, Settings computed in 2.1 s with
  "Unreachable … the shop keeps working" and "1 product changes waiting"; started again: searchable 51.4 s
  later, block back to "Up to date"; (4) probe reproduction (below) and doctor OK; product 4242 restored (price
  35.99, 6 on hand). Screenshots S3.1–S3.3 (`docs/report/kit/figures.md`) still need a signed-in browser.
  Built: outbox
  `lost_demand.index.queue` (template ID as a plain integer, rows written by a pre-commit callback, one per product
  per transaction, then `ir.cron._trigger()`); hooks (all `super()` first): `product.template` and `product.product`
  create/write/unlink (indexed fields only), `product.public.category` write(name)/unlink,
  `stock.quant._update_available_quantity` (the one funnel of inventory adjustments, deliveries, receipts and
  reservations); job *Lost-demand search: sync product changes to Elasticsearch* (every minute + trigger):
  `FOR UPDATE SKIP LOCKED`, merge per product, bulk 500 through the alias with `require_alias=true`, delete
  sent rows, refused items retried after 30 s doubling to 1 h (never dropped; "refused" after 10), outage =
  rows untouched, never raises (Odoo deactivates failing cron jobs), 50 s budget then "partially done";
  index stores the shop's **free quantity** (`free_qty`, website warehouse, `in_stock` also true for products
  without stock tracking) — mapping `_meta.definition_version` 2, the sync waits for a rebuild when the alias
  holds another version; rebuild and sync serialised by a PostgreSQL advisory lock (rebuild locks on its own
  cursor, then reads on a new one: REPEATABLE READ snapshot after the lock), waiting rows due again after a
  rebuild; Settings › Website block "Product changes" (waiting, refused, oldest); doctor `product changes
  waiting` (odoo); `uv run shop probe products [--count 30] [--timeout] [--seed]`; module 19.0.0.4.0.
  Found by tests: the job was first named `_flush`, which overrides the ORM's `BaseModel._flush()` (renamed
  `_send_to_index`). Report kit `docs/report/kit/` created (supervisor's request) and its rule added to
  `CLAUDE.md`. Tests: 462 tools (+21), 45 module (+18, 5 of them `es`)

- 3.3 — implemented 2026-11-20 on `feat/es-shop-search`, PR open, **waiting for the supervisor's manual test**.
  Built: `controllers/main.py` (`WebsiteSaleLostDemand`): `_shop_lookup_products` (website_sale/controllers/
  main.py:239) — Elasticsearch ranks at most 1,000 template IDs (published, website, selected category and its
  subcategories), Odoo re-filters them with `product.template._search_get_detail()`'s base domain as the shopper
  and keeps Elasticsearch's order (or the sort the shopper picked); no text or engine `odoo` → `super()`; any
  `EsUnavailable` / `ConfigError` / `MalformedResponse` → `super()` (native results). `_get_shop_domain`
  (line 158): `super()` without the words AND id in the hits, so categories, attributes and price range follow.
  `services/query_builder.py` (pure, snapshot-tested): `es_plain`, `es_tuned` v0 (untuned: shop analyzers,
  name^3 brand^2 description, `fuzziness AUTO`, `prefix_length 1`), `es_tuned_stock` (in-stock first, rule (a),
  default); ties by `template_id`, `_source: false`, `track_total_hits: false`. `services/shop_search.py`: engine
  switch (`X-Lost-Demand-Key` = `LOAD_TEST_KEY`, `X-Lost-Demand-Engine`; with the key only, response header
  `X-Lost-Demand-Engine-Used`, `odoo_fallback` on failure), one search through `guarded()`. `EsClient`: shopper
  searches on their own 8-thread pool. Config `LOST_DEMAND_ES_SEARCH_MAX_HITS` (1,000, ≤ 10,000) and
  `LOST_DEMAND_LOAD_TEST_KEY` (`.env.example`, compose, optional). Module 19.0.0.5.0. Design review findings
  (category filter pushed to Elasticsearch, price kept Odoo-only, separate pool, `_get_shop_domain`) and the
  test finding (category-page product links) in `docs/report/kit/engineering-log.md`. Tests: 505 tools (+43),
  62 module (+17: 14 `HttpCase` on real `/shop` pages with a fake low-level client — order kept, unpublished
  never shown, pages, category, chosen sort, typo with categories, no-hit, down, circuit, slow within budget,
  switch with/without key —, 3 `es` on the real cluster: stemming, typo, in-stock rule). Live checks
  (agent, 2026-11-20, observations, not recorded runs): `royal blue bedspreads` 0 results with `odoo`, 1,000 with
  the Elasticsearch engines; `theottle cable` 0 → 768, throttle cables on top; warm pages median 246 ms
  (`es_tuned_stock`) vs 453 ms (`odoo`), 18 requests each; Elasticsearch stopped: every page 200 with Odoo's
  results (`odoo_fallback`), ~0.9 s for the first 3, then circuit open (one warning logged) ~0.3 s; started
  again: Elasticsearch results 54 s later

## Latest results
- **Product change → searchable in the index (FR1, target < 60 s)** (run `probe-products-20261120T174549Z`,
  commit 55767d6, `results/summary/freshness-products.md`): 30 changes (15 price, 15 stock), **30 visible, 0
  timeouts, p50 1.12 s, p95 2.19 s, max 4.38 s**. Index level only: the shop page searches Elasticsearch from
  Task 3.3. Reproduced in the manual test from clean commit c8641c9 (run `probe-products-20261120T184703Z`,
  not committed as the table): 30/30, p50 1.01 s, p95 1.19 s, max 1.21 s, 0 timeouts. Not a protocol result yet (04 §11.4 is measured again at the M8 campaign). Live outage check
  (agent, 2026-11-20, not a recorded run): with Elasticsearch stopped a price write took 0.06 s and waited in
  the outbox (0 refusals); visible 64.4 s after `docker compose start elasticsearch` (startup + next minute run)
- **Baseline, Odoo's native shop search, dev queries** (run `baseline-search-20261115T022019Z`, commit 5bb9e2f,
  `results/summary/baseline-search.md`): of 300 dev queries, **73 (24 %) show no result** although every wanted
  product is in the shop (15 % for 1–2 words, 23 % for 3–4, 33 % for 5+, 46 % with a negation word); Odoo's
  similar-word fallback changed 2 queries; 188 (63 %) show an exact product on page 1 (optimistic: median 4 results
  in our judged-only catalog). Hand-picked: 17 of 20 find nothing while their controls find the product. Dev data
  only; not a test-set result. **Reproduced 2026-11-19** from a clean stack and a fresh full import (run
  `baseline-search-20261119T154209Z`, git bc36eb3): every table row identical

## Decisions since last milestone
- Task 3.3 plan accepted 2026-11-20 ("go as the recommendations", after the supervisor asked for a second,
  deeper review): engines `es_plain`, `es_tuned` (v0, untuned) and `es_tuned_stock` (shoppers' default, in-stock
  first by rule (a)); at most 1,000 hits per search; an explicit sort order sorts the hits with Odoo's order;
  Elasticsearch shows published products only, also to internal users
- Task 3.2 plan accepted 2026-11-20 ("go as the recommendations", after a deeper review): index the free
  quantity (definition version 2, rebuild once), the probe measures change → searchable in the index until
  Task 3.3 adds the shop page, refused rows kept and retried hourly (never dropped)
- Report kit (supervisor, 2026-11-20): `docs/report/kit/` is updated at the end of every task (Odoo overrides,
  engineering log, figures, results index, outline); rule in `CLAUDE.md` and the task report template (03 §14)
- Task 3.1 plan accepted 2026-11-19 ("Go, as recommended"): index files inside the module (the Odoo container mounts
  only `addons/`; `elastic/README.md` points there); `shop index rebuild` runs the rebuild in `odoo shell`, no
  administrator rights for the API user; empty synonyms seed until Tasks 3.5/3.6 (chosen on dev queries); no `color`
  field; old indices kept until the supervisor deletes them
- Repository `odoo-search-lost-demand`, public; code license LGPL-3.0-only (`LICENSE` + `COPYING`)
- Repository stays on the Windows drive (consequence in ADR-014: restart Odoo after Python changes)
- Version table approved (ADR-018); PostgreSQL 16 kept; Docker Desktop stays at 4.60.1
- REES46: academic use, attribution, raw data local and never redistributed (ADR-012)
- No global git changes and no `.wslconfig` change (protect other repositories and the other Docker stack)
- Tooling: uv project `shoptools` (uv_build, `module-root = "tools"`), argparse CLI, pre-commit (ruff, pre-commit-hooks,
  detect-secrets), doctor on the standard library only
- GitHub (applied by the agent with `gh`, supervisor-approved): default branch `develop`; ruleset "protect main and
  develop" (PR required, 0 approvals, required checks `lint`, `tools (ubuntu-24.04)`, `tools (windows-2025)`, and
  since 2026-11-14 `compose` and `module` (supervisor), no force-push, no deletion); squash + merge commits, no rebase;
  head branches auto-deleted
- Team: solo developer for now (supervisor, 2026-10-28); the specification lists a co-author who does not open PRs
- No GitHub issues or project board for now
- ADR-008 still Proposed (final after Task 4.2). ADR-013 Accepted 2026-11-14 (protocol v1); ADR-014 Accepted
  2026-11-13 (Task 1.4b)
- Evaluation protocol v1 is binding (`docs/evaluation/protocol.md`, tag `protocol-v1`); `04` §3, §8, §11 point to it.
  Unsatisfied-query signal approved. Seed `20261025` with one derived stream per random step
- Task 2.3 split into 2.3a and 2.3b (supervisor, 2026-11-14)
- Task 2.4 split into 2.4a (brand field, categories, vendors, products with vendor prices, id map) and 2.4b (stock,
  full import, checks, snapshot); importer through the JSON-2 API (ADR-019) unless measured too slow (> 30 min
  projected); imported products carry **no sales tax**, so the shop shows the synthetic prices as they are
  (the generic chart would add 15 %) (supervisor, 2026-11-14)
- Hidden sets: **option B2** (supervisor, 2026-11-14) — protocol v1.1, a deviation from v1 §4 and from the
  specification's "hide 20 % of the catalog". Measured on the slice: hiding single E-targets (v1) empties only 52–71
  of 1,000 queries and ~3 % of hidden products sit in such a query (8,786 of 8,824 E-targets are E for one query;
  median 7 E per query), so recall ≈ 3 % by construction. B2 hides **all** E products of 20 % of each set's queries
  (hidden-test: 140 test queries, ≈ 6.5 % of the catalog; hidden-dev: 60 dev queries, ≈ 2.7 %). The out-of-stock
  set is drawn among E-targets of non-hidden queries. Academic supervisor's approval may be needed (D11)
- Personal Kibana user gets the built-in `editor` role (not read-only) because dashboards are built in the UI in
  Task 4.5; `01_ARCHITECTURE.md` §5.2 updated — approved by the supervisor 2026-10-29
- `.odoo-src/` layout `.odoo-src/odoo/...` and translations (`*.po`) excluded by default, `--with-translations` to
  include them (supervisor, 2026-10-29). Copy method: `tar` stream from `docker run --rm --network none`, not
  `docker create` + `docker cp` (no leftover container, exclusion at the source, symlinks skipped on Windows)
- Odoo image: client set pinned and hash-locked (`--require-hashes`, wheels only, `--no-deps`) after two SonarCloud
  findings on PR #8 (docker:S8541, docker:S8544); `typing-extensions` 4.16.0 shadows Ubuntu's 4.10.0 in `/usr/local`
- SonarCloud runs on PRs (added outside the agent, first seen on PR #8); not a required check. CI `uv` calls use
  `--locked --no-build` (githubactions:S8541/S8544, PR #19)
- CI `module` job runs the real compose stack without Kibana, not service containers (supervisor, 2026-11-14)
- `shop up` never pulls images: missing images stop it with the `docker compose pull` command (no surprise downloads)
- `stop_grace_period`: Elasticsearch 60 s, PostgreSQL 30 s (Elasticsearch was killed with exit 137 at Docker's default 10 s)
- Task 1.2 split into 1.2a (database) and 1.2b (snapshots) (supervisor, 2026-10-29). Company and website "Lost Demand
  Demo Shop", no country (generic chart); integration user with Sales, Inventory and Purchase Administrator rights, no
  Settings rights; persistent (non-expiring) API key, local `.env` only. "Products / Create" added 2026-11-06
  (supervisor): in 19.0 only `product.group_product_manager` creates products, and only Settings implies it
- `db_name` removed from `odoo.conf` (supervisor, 2026-10-29, option A): with it, the 19.0 server creates a blank
  database (admin/admin) at every start (`odoo/cli/server.py::main`). `dbfilter = ^shop$` and `list_db = False` stay;
  scheduled jobs now run on every database owned by `odoo` (only `shop`). The empty auto-created database was dropped
- Kibana memory limit raised (supervisor, 2026-10-29): standard 1536m → 2g, lowmem 1g → 1280m; it idled at 75–88 %
  of the old limits. After the change: 1.34 of 2 GiB at startup (standard)
- Task 1.3 plan accepted by the supervisor's "go" (2026-11-06), with the agent's recommendations: status block in
  Settings > Website (computed, non-stored fields on `res.config.settings`, no new model), manifest license LGPL-3,
  `shop test module` drops and recreates `shop_test` without asking (never the shop database), no `elasticsearch`
  package on the host (the client is imported only when a real client is built), group "Shop manager" created now with
  a header-only `ir.model.access.csv`. Module depends only on `website_sale` for now
- Module services are tested on the host by pytest as the top-level package `services` (`pythonpath` in
  `pyproject.toml`); ruff ignores F401 in addon `__init__.py` and B018 in manifests (Odoo conventions)

## Open issues / risks
- PyCharm Pro trial ends 2026-11-14. Supervisor decision (2026-11-13): apply for the free JetBrains educational (student)
  license, which keeps the Docker Compose interpreter; free, verified by university email, ISIC/ITIC card or GitHub
  Student Pack, valid one year and renewable while a student (JetBrains sales FAQ). Applying is human-only. Until it is
  active, PyCharm's free tier cannot debug in Docker: use the scripted `pdb` check or wait; the host-run fallback
  (`docs/setup/PYCHARM.md` §9) stays the plan only if the license is refused
- Docker memory 8.3 GB is at the low edge of `standard` and shared with another project's containers
- XML-RPC/JSON-RPC: deprecated in Odoo 19, removal planned in Odoo 22 (`.odoo-src/odoo/addons/rpc/controllers/__init__.py`);
  the tools use JSON-2 only (`POST /json/2/<model>/<method>`, bearer API key)
- Free disk: 72 GB on 2026-11-14 after the supervisor freed space (2.2 GB that morning: doctor FAIL; 37.5 GB on
  2026-11-06). Docker images 18.9 GB (14.7 GB unused, mostly other projects). Datasets (ESCI 1.1 GB, REES46 13.7 GB)
  come in M2/M7. Never prune without the supervisor
- The supervisor's kind cluster (`mlops-lab-*`, `kind-registry`, another project) restarts with Docker Desktop; the agent
  stopped it on request (2026-11-14), never removed
- `shop test module` takes about 85–90 s (fresh `shop_test` with `website_sale` and its dependencies) and runs a second
  Odoo process in the `odoo` container next to the development server
- Kibana and Elasticsearch memory under real dashboard and indexing load is not measured yet (M4, M7, M8)
- Clean start 387 s on 2026-11-19 (target < 5 min; 93 s on 2026-11-14) with ~17 containers of other projects running
  (a kind cluster among them); the timing targets assume a quieter engine. Stop other stacks before timed runs
- Fresh stack: cluster health was yellow at the M2 gate. Checked 2026-11-20: Kibana 9.5 creates
  `.entity_analytics.watchlists.default` with `auto_expand_replicas: 0-1`, so on one node it settles at 0 replicas
  (green on the real stack). The yellow was most likely transient while Kibana started; `es-setup` cannot change an
  index created after it runs, so nothing was changed. Re-check at the M3 regression gate
- Free disk 39.2 GB on 2026-11-20 (35.7 GB on 2026-11-19; doctor WARN below 50 GB): enough for M3; never prune
  without the supervisor
- The PostgreSQL password was shown once in the agent chat (process list check, before the fix); it never reached
  the repository. Rotate it if the transcript is shared (needs `ALTER USER` on the existing volume)

## Waiting on human / supervisor
- Calendar of milestone dates in `docs/ai/05_ROADMAP.md` (optional, helps warn about delays)
- A local shop owner for interview #1 (Task 1.6) — start looking early

## Next step (exact)
- **Supervisor: manual test of Task 3.3** (PR from `feat/es-shop-search`; the stack already runs the branch's
  module 19.0.0.5.0). Steps:
  1. Browser, `http://127.0.0.1:8069/shop?search=royal blue bedspreads` (Odoo alone finds nothing: baseline),
     `theottle cable` (typo), `windex`: results, prices, pages; open page 2; pick "Price - Low to High" in the
     sort menu; open a category from the left list while searching;
  2. a sold-out product of the results sits after the in-stock ones (e.g. search a word of the Giftgarden shelf
     from the 2.4b follow-up);
  3. `docker compose stop elasticsearch`, search again: results (Odoo's own, e.g. `royal blue bedspreads` shows
     none, `windex` 36), no error page; `docker compose start elasticsearch`: within ~1–2 min Elasticsearch
     results return (breaker cooldown 30 s after Elasticsearch answers again);
  4. optional: `uv run shop doctor`; read `docs/report/kit/odoo-overrides.md` § Task 3.3;
  5. say "merge" (or what to change). Screenshots S3.7–S3.9 (`docs/report/kit/figures.md`) need a browser.
- Known limits to decide later (not bugs of 3.3): the sort menu still says "Featured" while results are in
  relevance order (a "Relevance" entry would be a template change); the Elasticsearch engines do not search the
  internal reference (`default_code`), Odoo's does — a Task 3.5 candidate; typo tolerance makes totals large
  (capped at 1,000) — `minimum_should_match` is a Task 3.5 experiment; the first search after a restart of
  Elasticsearch can fall back once (cold caches, 518 ms measured)
- Task 3.2's optional screenshots S3.1–S3.3 and its manual-test steps, for reference:
  1. Odoo › Inventory › a product › "On Hand" › set the quantity to 0 (or Settings › Website, change a price);
     within a minute `GET shop-products/_search?q=template_id:<id>` (Kibana Dev Tools, read-only) shows
     `free_qty: 0`, `in_stock: false` (shop ordering by stock comes with Task 3.3);
  2. Settings › Website › "Product changes": "Up to date"; Settings › Technical › Scheduled Actions shows
     "Lost-demand search: sync product changes to Elasticsearch" (every 1 minute);
  3. `docker compose stop elasticsearch`, change a price: the save is instant and the block shows "1 product
     changes waiting"; `docker compose start elasticsearch`: within ~1–2 min it is sent (block back to "Up to date");
  4. `uv run shop probe products` → read p50/p95 (last run: p95 2.19 s), then `uv run shop doctor`
     (`product changes waiting` OK);
  5. read `docs/report/kit/odoo-overrides.md` (the file asked for the report)
- Supervisor: old product indices (`shop-products-v1..v3`, ~70 MB each) are kept; say when to delete them
- Idea for M4/M6 (not decided): Odoo's "Get notified when back in stock" form on out-of-stock pages is an explicit
  lost-demand signal (a shopper asking for a missing product); consider it as an extra event
- Agent note: `odoo module upgrade -c /etc/odoo/odoo.conf -d shop website_sale_lost_demand` inside the `odoo`
  container (`MSYS_NO_PATHCONV=1` in Git Bash), then `docker compose restart odoo`, upgrades the module in `shop`
- Follow-up (before M9 facets, optional): keyword categories are right for roughly 3 of 4 products; ambiguous
  bullet-point words cause most misses. Tuning them (dev products only) changes the catalog hashes and the hidden
  sets' strata: rebuild the slice, re-run the import and re-save `baseline-catalog`, all before any campaign
- Supervisor: academic supervisor's approval of protocol v1.1 if required (D11)
- Observation for 2.3b/M5 (not a protocol deviation): the typo position is uniform over the word's letters, so
  first-letter typos ("poll" → "opll") occur; real typos are rarer there. The shopper model may weight positions
- Supervisor: JetBrains student license; optional PyCharm screenshots 01–05 and 08 (`docs/setup/PYCHARM.md` §7); the
  screenshots listed in `docs/report/notes/M1.md`; Task 1.6 (interview) in parallel
- Agent note: PyCharm rewrites `.run/*.run.xml` from its in-memory copy and can undo committed changes (it dropped
  `--addons-path` and turned "debug just my code" on again on 2026-11-13): check `git diff .run` before committing
- Agent note: Odoo `call_kw` takes the record ids as the first argument of non-`@api.model` methods
  (`odoo/service/model.py`): `onchange` over `/web/dataset/call_kw` needs `args = [[], values, names, spec]`
- Agent note: on Windows, `python3` in Git Bash is the Store stub and hangs; use `uv run python`
- Agent note: SHA-256 values and 40-hex commits trip detect-secrets: mark them `# pragma: allowlist secret`
  (pins, manifest lines, tests) or use non-hex test values
- Agent note: never poll CI (no `gh pr checks --watch`, no sleep loops); auto-merge is off in the repository: ask the
  supervisor to come back when a run has finished. Required checks: lint, tools ×2, compose, module (~3–4 min)
- Agent note: to work on a second branch while the checkout is busy (a long download, PyCharm open), use a git
  worktree next to the repository and remove it after the merge; never switch branches under a running job
- Agent note: a stack run under another Compose project (isolated regression) needs `COMPOSE_PROJECT_NAME` set for
  every command of that run only; the doctor honours it since PR #25
- Agent note: a new module needs `docker compose restart odoo` before Apps > Update Apps List: 19.0 caches manifest
  lookups per process, including "not found" (`odoo/modules/module.py`, `Manifest._get_manifest_from_addons`)
- Agent note: in the built-in browser, navigating to the same Odoo URL (only `#...` differs) does not reload the page;
  go to another URL first. `Update Apps List` needs `?debug=1`
- Agent notes: detect-secrets flags `*_PASSWORD = "..."` and multi-key strings in tests — build test `.env` text from a
  dict, mark fake values with `# pragma: allowlist secret`; never print container command lines or `.env` values
- Agent note: `shop lint` (`pre-commit run --all-files`) skips untracked files and no git hook is installed:
  `git add` new files before running lint (PR #11 failed CI `lint` on two new files that passed locally)
- Agent note: `docker compose exec` forwards stdin; every Docker call without input now uses `stdin=DEVNULL` (it
  swallowed the `shop db reset` confirmation). The agent's background commands get no stdin: feed a prompt from a file
  in a foreground command
- Agent note: in Git Bash, `/etc/...` arguments to `docker compose exec` are rewritten to Windows paths; prefix
  one-off commands with `MSYS_NO_PATHCONV=1` (the `shop` tools call Docker from Python and are not affected)
