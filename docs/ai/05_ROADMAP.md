# 05 — Roadmap: Milestones and Bounded Tasks

Act as the senior implementation engineer. Implement the project **one bounded task at a time**.

## Non-negotiable execution rule

```text
read docs/progress/STATUS.md
 -> read ONLY the current milestone section below
 -> post the plan for the current task, wait for "go"
 -> implement it
 -> automated checks
 -> update STATUS.md
 -> TASK REPORT
 -> STOP
 -> supervisor tests manually and reports
 -> only then the next task
```

- Do NOT implement a whole milestone in one response. Do NOT silently move to the next task.
- **[HUMAN]** = contains actions only the supervisor can do (admin rights, accounts, licenses, interviews, browser-only work).
  Prepare everything, give exact instructions, then STOP.
- **[SUPERVISOR]** = needs a decision or approval (academic or design). Present options with trade-offs, then STOP.
- **[SPIKE]** = time-boxed experiment on a `spike/*` branch; the deliverable is a written conclusion + ADR; the code is not merged.
- Requirement IDs (FR1–FR13) come from `01_ARCHITECTURE.md` §1.
- If a task reveals that the plan is wrong, say so and propose a correction. Do not silently drift.

## Session strategy (protect the context window)

- One milestone ≈ one to three sessions. Start a fresh session at each milestone boundary and whenever the context gets long.
- `docs/progress/STATUS.md` is the memory between sessions. Keep it accurate and short.
- Do not re-read finished milestones. Do not re-read whole documents when one section is enough.
- Long jobs run in the background with logs; report progress instead of waiting silently.

## Milestone overview

| # | Milestone | Spec step | Priority | Ends with |
|---|---|---|---|---|
| M0 | Environment bootstrap & repository foundation | 1 (setup) | Must | Doctor green, CI green |
| M1 | Docker stack, module skeleton, debugging, first interview | 1 (setup) | Must | Tag `m1-stack` |
| M2 | Datasets, evaluation protocol, catalog import | 2 | Must | Tag `m2-catalog` |
| M3 | Search engine (FR1–FR3 + fallback + synonyms) | 3 | Must | **Checkpoint "search works"**, tag `m3-search` |
| M4 | Events & dashboards (FR6, FR7) | 4 | Must | Tag `m4-events` |
| M5 | Virtual shoppers (FR11) | 5 | Must | Tag `m5-shoppers` |
| M6 | Lost-demand loop (FR8, FR9) | 6 | Must | **Checkpoint "full loop works"**, tag `m6-loop` |
| M7 | REES46 replay (FR12) | 7 | Must | Tag `m7-replay` |
| M8 | Evaluation campaign (spec §11) | 8 | Must | Results report, scope review, tag `m8-evaluation` |
| M9 | Shop extras (FR4, FR5, FR10) | 9 | Should | Tag `m9-extras` |
| M10 | Semantic search (FR13) | 10 | Could | Tag `m10-semantic` |
| M11 | Pilot, report, presentation | 11 | Must | Final release tag |

Order rationale: the spec's order is kept. Two things are pulled earlier on purpose:
the **evaluation protocol** (M2) because the catalog slice and the hidden set must be designed for it, and a **minimal NDCG
harness** (M3) because "tuned search" cannot be tuned without measuring it. The full campaign stays in M8.

## Calendar (filled in by the supervisor)

| Milestone | Target end date | Academic checkpoint / meeting |
|---|---|---|
| M0–M1 | | |
| M2–M3 | | |
| M4–M6 | | |
| M7–M8 | | |
| M9–M10 (if time allows) | | |
| M11 | | Report deadline: … — Defense: … |

The agent warns the supervisor when a milestone is likely to miss its date and proposes what to cut (Should/Could first).

---

# M0 — Environment bootstrap & repository foundation

**Goal:** every required tool installed at a verified, pinned version; one command proves the machine is ready;
the repository skeleton passes checks locally and in CI.
**Exit criteria:** `uv run shop doctor` shows no FAIL for the sections available in M0; `docs/setup/VERSIONS.md` approved;
scaffold merged into `develop`; CI green on a PR.
**Read:** `06_ENVIRONMENT_SETUP.md` (whole), `03_GIT_TESTING_PIPELINE.md` §1–6.

### Task 0.1 — Machine inventory (read-only)
- Run the Phase A inventory of `06` §4.1 for the detected OS. No installs, no configuration changes, no image pulls
  (except the tiny kernel-check image if Docker already runs — ask first). The only files written are
  `local/machine-report.md` and a `local/` line in `.gitignore` (create the file if needed) so the report is never committed.
- Output: `local/machine-report.md` (git-ignored) and, in chat, one table: item | found | required | status | note.
- Flag blockers early: virtualization disabled, < 35 GB free disk, 8 GB RAM (→ `lowmem` profile), company-owned laptop
  (Docker Desktop license), ports in use.
- Manual: the supervisor confirms the table matches reality (OS, RAM, disk).

### Task 0.2 — Version matrix (research, no installs) [SUPERVISOR]
- Verify every component of `06` §3 from official sources; start from the 2026-10-28 starting points but re-check them.
- Write `docs/setup/VERSIONS.md` (component, pinned version, why, source URL, date verified, compatibility notes) with the
  feature-license table, and `docs/setup/versions.toml` (machine-readable, used by the doctor).
- Determine the Odoo image's Python version without pulling 1.5 GB if possible (official image build files); otherwise ask before pulling.
- Write ADR-001…ADR-017 from `01` §3 into `docs/decisions/`, plus ADR-018 "pinned versions".
- Create `docs/progress/STATUS.md` (structure in `00_HOW_TO_USE.md` §9) and `docs/glossary.md`.
- Manual: the supervisor reads the version table and approves or corrects it.

### Task 0.3 — Install and configure prerequisites [HUMAN]
- Post the install plan (tool, command, source, size, admin?, reboot?), wait for "go", then install one tool at a time
  following `06` §4.2, verifying after each. Configure per `06` §4.3 (git identity values from the human, line endings,
  Docker memory per profile, `vm.max_map_count`, `git lfs install`).
- Human: click UAC/sudo prompts, reboot when asked, accept Docker Desktop terms, install PyCharm from Toolbox and activate
  the license, choose the repository location (ADR if WSL file system).
- Re-run the inventory: all required tools green. Write `docs/setup/ENVIRONMENT.md` (what actually worked, problems met).
- Manual: open Docker Desktop (or `docker run --rm hello-world`), open PyCharm, run `uv --version`, `git lfs version`.

### Task 0.4 — Repository scaffold
- Connect to `<REPO_URL>` (ask the supervisor for the URL; the pack is already on `main`).
- Create the layout of `01` §4 (empty folders with a README where useful): `.gitignore` (`data/` except README.md and manifest.toml,
  `results/` except `results/summary/`, `local/`, `.env`, `.odoo-src/`, `.venv/`, `*.parquet`, dumps, snapshots — do not blanket-ignore
  `*.csv`, small summaries are committed), `.gitattributes` (LF, binary types), `.editorconfig`,
  `pyproject.toml` (uv project `shoptools`, console script `shop`, dependency groups), `.python-version`, ruff config,
  `.pre-commit-config.yaml` (ruff, end-of-file, trailing whitespace, YAML/JSON/XML/TOML checks, a secret scanner),
  README skeleton, `docs/` skeleton, spec PDF in `docs/sources/` (human provides the file), LICENSE [SUPERVISOR choice].
- `shop` CLI skeleton (argparse or a small dependency, justified) with `--help` and sub-command placeholders.
- Acceptance: fresh clone → `uv sync` → `uv run shop --help` → `uv run pre-commit run --all-files` passes.
- Manual: clone into a new folder and repeat the acceptance commands.

### Task 0.5 — `shop doctor` and bootstrap scripts
- Implement the doctor per `06` §7 for sections `machine`, `tools`, `docker`, `ports`, `repo`; other sections return
  `SKIP (available from M<n>)`. `--json`, `--section`, `--fix` (safe actions only), exit codes.
- `scripts/bootstrap.ps1` and `scripts/bootstrap.sh` per `06` §7.3.
- Unit tests with fake command outputs (version parsing, thresholds, Windows/macOS/Linux branches).
- Manual: run the doctor; stop Docker and run it again (Docker checks FAIL with a fix hint); rename `.env` (repo check FAIL).

### Task 0.6 — CI and GitHub hygiene [HUMAN]
- `.github/workflows/ci.yml` jobs `lint` and `tools` (`03` §12); `compose` and `module` jobs are added in M1.
- Human: repository settings (`03` §12), optionally a GitHub Project board; with approval, the agent creates one issue per
  roadmap task with `gh` (labels: milestone, FR IDs, Must/Should/Could).
- Manual: open a PR with a deliberate lint error → CI fails; fix → CI passes.

---

# M1 — Docker stack, module skeleton, debugging, first interview

**Goal:** the whole stack starts with one command on the laptop; the module installs; breakpoints work; the first shop-owner
interview is prepared.
**Exit criteria:** `docker compose up -d` from nothing reaches healthy; license = basic; a manual checkout works on a fresh
database; module installs and its tests run locally and in CI; a breakpoint is hit in PyCharm.
**Read:** `01` §4–6, §12; `06` §5–6.

**Order (supervisor decision, 2026-10-29):** 1.1a → 1.1b → 1.4a → 1.2 → 1.3 → 1.4b → 1.5 → 1.7; 1.6 runs in parallel and does not
block the tag. Reasons: Tasks 1.1 and 1.4 were split to stay testable; the Odoo source copy (1.4a) comes before 1.2 and 1.3 because
both must read the 19.0 source; PyCharm debugging (1.4b) comes right after 1.3 because the PyCharm Pro trial ends on 2026-11-14.

### Task 1.1a — Compose stack, images, es-setup, `.env`
- `compose.yaml` with `db`, `elasticsearch`, `es-setup`, `kibana`, `odoo` per `01` §5 (healthchecks, startup order, named volumes,
  ports bound to `127.0.0.1`, memory settings from `.env`, RAM profiles); `docker/odoo/Dockerfile` (pinned base + pinned client);
  `docker/es-setup/` (passwords, roles/users of `01` §5.2, license assertion, templates placeholder).
- `uv run shop env init [--profile]` (generate `.env` secrets); `.env.example`.
- Acceptance: clean start healthy in < 5 min (after images are pulled); `GET _license` = basic; Kibana login with the personal user;
  Odoo database manager disabled.
- Manual: `docker compose up -d`, open Kibana and Odoo, then `docker compose restart` and check nothing is lost.

### Task 1.1b — Stack commands, doctor sections, memory measurement
- `shop up [--no-kibana]`, `shop down` (never removes volumes), `shop status`, `shop logs`.
- Doctor sections `stack`, `elastic`, `kibana` (basic checks); the `ports` check uses the project name set in `compose.yaml`.
- Measure memory per container (`docker stats`) in both profiles if possible; correct `01` §5.3.
- Manual: `uv run shop up`, `uv run shop doctor`, `uv run shop down`, then `uv run shop up --no-kibana`.

### Task 1.2 — Database bootstrap and snapshots
- `uv run shop db create`: fresh database without demo data (verify the 19.0 flag), apps (verify names in 19.0):
  website, eCommerce, website stock, purchase with stock, a test payment provider (demo provider if it exists in 19.0 Community);
  English, USD, company and website configured; guest checkout enabled; integration user with a JSON-2 API key written to `.env`.
- `uv run shop db reset` (destructive: asks for confirmation), `uv run shop snapshot save|restore|list <name>`
  (database dump + filestore, stored under `local/snapshots/`, git-ignored).
- Acceptance: create a product by hand, buy it as a guest with the test provider, order confirmed; snapshot restore brings back
  the previous state in under a minute.
- Manual: the full guest checkout; save a snapshot, change something, restore.

### Task 1.3 — Module skeleton
- `addons/website_sale_lost_demand/`: manifest, security groups and access file, settings page with read-only Elasticsearch
  status (reachable, version, license, cluster health), `services/config.py`, `services/es_client.py` (timeouts, health cache,
  circuit breaker skeleton), fake ES service for tests, README.
- `uv run shop test module [--es]`: runs the module tests in the container.
- Doctor section `odoo` (health endpoint, database exists, module installed and version).
- Tests: config validation, breaker transitions, settings page renders for admin and is forbidden for others.
- Manual: install the module from Apps; open its settings page with Elasticsearch up, then stopped (status changes, page still works).

### Task 1.4a — Odoo source copy (done before Task 1.2)
- `uv run shop odoo-src` copies the exact Odoo package from the image into `.odoo-src/` (`06` §5).
- Manual: run it; open `.odoo-src/` and find `odoo/addons/website_sale/controllers/main.py` (layout `.odoo-src/odoo/`,
  supervisor decision 2026-10-29: translations excluded by default); the doctor's `.odoo-src/` check is OK.

### Task 1.4b — PyCharm debugging [HUMAN] (done right after Task 1.3, before 2026-11-14)
- PyCharm Docker Compose interpreter + run/debug and test configurations (`06` §6); `docs/setup/PYCHARM.md` with screenshots
  listed for the human to capture.
- Time box: 2 hours. If breakpoints do not work, switch to the host-run fallback and record ADR-014's final decision.
- Manual: set a breakpoint in the module settings controller, open the page, PyCharm stops; step into an Odoo core method.

### Task 1.5 — CI module job
- CI jobs `compose` (config validation) and `module` (build image, PostgreSQL + small-heap Elasticsearch services,
  install the module on a fresh database, run unit + `es` tests).
- Manual: open a PR that breaks a module test → CI fails; fix → passes.

### Task 1.6 — Shop-owner interview #1 [HUMAN]
- Draft `docs/pilot/interview-guide-1.md` (how they restock today, how they learn what customers want, whether they look at
  search terms, examples of missed sales, what a useful alert or list would look like, what they would never trust),
  `docs/pilot/consent.md` (what is recorded, anonymisation, right to withdraw), and a notes template.
- Human: recruit a local shop owner, conduct the interview, write anonymised notes in `docs/pilot/interview-1-notes.md`.
- Agent: summarize implications (thresholds, wording, priorities) as proposals for the supervisor.

### Task 1.7 — Milestone note and promotion
- `docs/report/notes/M1.md`; regression gate (`03` §9, items 1–2); PR `develop → main`; tag `m1-stack` after merge.

---

# M2 — Datasets, evaluation protocol, catalog import

**Goal:** a reproducible ~20k-product catalog from ESCI, with synthetic enrichment, imported into Odoo; an approved evaluation protocol.
**Exit criteria:** protocol approved; slice outputs reproducible (hash test); catalog imported idempotently; baseline snapshot saved.
**Read:** `04` §1–4, §11–12.

### Task 2.1 — ESCI acquisition
- `uv run shop data fetch esci`: announce size/time/disk, wait for "go", download from the official repository with Git LFS
  into `data/raw/esci/`, check real file sizes (no pointer files), record source commit, SHA-256 and license in `data/manifest.toml`.
- Profile (aggregates only) into `results/summary/esci-profile.md`: queries and judgments per locale, split, `small_version`, label distribution.
- Doctor section `data` (ESCI part).
- Manual: run the doctor `data` section; open the profile.

### Task 2.2 — Evaluation protocol v1 [SUPERVISOR]
- Write `docs/evaluation/protocol.md` from `04` §3, §8, §11: query set sizes and seed, catalog rule, hidden-set rule,
  out-of-stock set, detection definition and whether the **unsatisfied-query signal** is added (recommended — explain why
  zero-result alone would rarely trigger with a 20k catalog), gains and NDCG formula, engines, statistics, freeze rule.
- STOP until the supervisor (and, if needed, the academic supervisor) approves. Record the approval date in the protocol.

### Task 2.3 — Slice builder and synthetic enrichment
- `uv run shop data build-slice`: writes `data/processed/` (catalog, dev/test/traffic queries, qrels, hidden set, out-of-stock set)
  and `results/summary/enrichment-report.md`; category rules in a config file; seeded generators.
- Streams/filters parquet without loading everything; memory under 2 GB.
- Tests (synthetic ESCI-format fixtures): determinism (hash), dev ∩ test = ∅, all judged products present, hidden ⊂ E-targets, category coverage reported.
- Manual: run twice, compare hashes; read the enrichment report (are prices and categories plausible?).

### Task 2.4 — Odoo catalog importer
- `uv run shop import catalog [--limit N] [--dry-run]`: batches through the Odoo JSON-2 API (or an in-container ORM script if
  measurably faster — decide in the plan, ADR); upsert by internal reference; public and internal categories; `brand` field
  (added by the module in this task, with module version bump); vendors and vendor price lines; stock through a proper inventory
  adjustment; all published; id map written; resumable; progress with ETA; timing recorded.
- Tests: idempotency (second run creates nothing), batch failure resume, mapping of each field (with the fake API or a test database).
- Acceptance: product count = slice count; re-run creates no duplicates; 10 random products match their source rows;
  `uv run shop snapshot save baseline-catalog`.
- Manual: `--limit 200` first, check in the shop and backend; then the full import; then a second full run (no duplicates).

### Task 2.5 — Baseline observations
- With Odoo's native search, run 20 hand-picked queries (typos, synonyms, plural forms, brand names) and record what fails
  in `docs/report/notes/baseline-search.md` (screenshots listed for the human). This becomes the "problem" section of the report.

### Task 2.6 — Milestone note and promotion
- `docs/report/notes/M2.md`; regression gate items 1–3; promotion; tag `m2-catalog`.

---

# M3 — Search engine (FR1–FR3, fallback, synonyms) — checkpoint "search works"

**Goal:** the shop's search runs on Elasticsearch, tolerates typos, understands synonyms, puts in-stock products first,
stays fresh within a minute, and falls back to Odoo search when Elasticsearch fails.
**Exit criteria:** FR1–FR3 acceptance passed; fallback demonstrated; dev-set NDCG@10 recorded for `odoo`, `es_plain` and `es_tuned`
(target: tuned highest — if not, the gap is analysed, not hidden); checkpoint demo accepted by the supervisor.
**Read:** `01` §7–8, §13; `04` §5–6, §11.1.

### Task 3.1 — Product index as code and full rebuild
- `elastic/products/` (settings, analyzers, mapping, synonyms set seed — created before the index); module service to build
  documents from templates in batches; full rebuild into `shop-products-v<N+1>` + count check + atomic alias swap;
  admin button and `uv run shop index rebuild [--check]`.
- Verify on the running Basic cluster that synonym sets work; otherwise implement the fallback and record it.
- Tests: document builder (unit), rebuild + alias swap (integration), counts.
- Manual: rebuild; check the alias in Kibana Dev Tools (read-only query); doctor `elastic` section shows the counts match.

### Task 3.2 — Incremental sync within 60 s (FR1)
- Outbox `lost_demand.index.queue`; triggers on product create/write/unlink/publish and on stock changes (verify the right
  19.0 hook); flush job requested immediately by cron trigger, collapsing duplicates, bulk with per-item error handling and retry.
- `uv run shop probe products --count 30`: changes stock/price through the API and measures time until visible in search.
- Tests: create/update/unpublish/delete reflected; stock change reflected; ES down → rows wait → flushed after recovery; no duplicates.
- Manual: change a product's stock to 0 in the backend; within a minute the shop shows it after in-stock items; run the probe and read p95.

### Task 3.3 — Shop search through Elasticsearch, with fallback
- Locate the 19.0 integration points (`01` §7 list) and cite them in the plan. Override the lookup so Elasticsearch returns ranked IDs,
  Odoo re-filters with its own domain and keeps the order; pagination, totals and existing category/attribute filters keep working.
- Circuit breaker + timeouts; fallback to `super()`; guarded engine switch for evaluation (load-test key).
- Tests: ES result order preserved; unpublished product never shown even if indexed as published; ES down → native results;
  ES slow → timeout → native results within budget; engine switch ignored without the key.
- Manual: search a few queries; stop Elasticsearch (`docker compose stop elasticsearch`), search again (results, no error page);
  start it again (Elasticsearch results return after the breaker cooldown).

### Task 3.4 — Minimal NDCG harness
- `shoptools/eval/metrics.py` (NDCG@10 with ESCI gains, judged@10, bootstrap CI) with hand-computed unit tests;
  `uv run shop eval ndcg --set dev --engine odoo,es_plain,es_tuned --mode http|direct`; run folders with `run.json`.
- Manual: run on the dev set; open the summary; re-run and confirm identical results.

### Task 3.5 — Relevance tuning v1 (FR2, FR3)
- Dev set only. Experiments from `04` §6, one change at a time, logged in `docs/evaluation/experiments.md` with run IDs;
  compare stock rule (a) tiered vs (b) boosted; choose the configuration (ADR) and implement it as `es_tuned` / `es_tuned_stock`.
- Test set untouched. Keep the experiment budget bounded (e.g. 10–15 runs) and report what did not help.
- Manual: the supervisor reviews the experiment log and approves the configuration.

### Task 3.6 — Synonym management (FR2, Administrator)
- `lost_demand.synonym` model, views (Administrator), sync to the synonyms set (or the fallback), validation of rules,
  seed list (e.g. sneakers/trainers, tv/television, phone/cell phone/mobile).
- Tests: create/update/delete sync; invalid rule rejected with a clear message; search uses the synonym without reindex.
- Manual: add "sneakers, trainers"; search "trainers" finds sneakers immediately.

### Task 3.7 — Checkpoint "search works" and promotion
- Demo script: typo query, synonym query, in-stock first, product change within a minute, fallback with Elasticsearch stopped,
  NDCG dev table. Milestone note; regression gate items 1–5 and 10; promotion; tag `m3-search`.

---

# M4 — Events & dashboards (FR6, FR7)

**Goal:** every search, click, add-to-cart and purchase becomes an event in Elasticsearch within seconds, visible on live dashboards.
**Exit criteria:** event freshness p95 < 10 s on the probe; no shopper request slowed or broken by logging; the five FR7 dashboards
importable from the repository.
**Read:** `01` §9; `04` §7, §10, §11.4.

### Task 4.1 — Event data stream as code
- `elastic/events/`: index template (strict mapping of `04` §7), ingest pipeline (`event.ingested`), ILM policy, applied by `es-setup`;
  Kibana data view.
- Tests: sample events of every type accepted; an unknown field rejected; REES46-shaped sample accepted.
- Manual: index a sample event with the tools user; see it in Discover.

### Task 4.2 — [SPIKE] Event pipeline design (time box: 1 day)
- Compare the outbox + cron-trigger flush with at least one alternative (for example a separate short-lived cursor, or a buffered
  in-process sender). Measure: delay to searchable, added request latency, behavior with Elasticsearch down, behavior on read-only routes,
  behavior with several Odoo workers. Write the conclusion and record ADR-008's final decision.

### Task 4.3 — Search and click events
- Search event with `search.id`, raw (masked, capped) and normalized query, result count shown, page, filters, `took_ms`, engine;
  click event via `sid`/`pos` parameters on result links (template inheritance); `product_view` without search context;
  session hashing; traffic tagging with the load-test key.
- Tests: normalization and masking; one event per search; click linked to its search; invalid `sid`/`pos` ignored safely;
  logging failure never breaks the page; events written while Elasticsearch is down are delivered after recovery.
- Manual: search and click in the shop; see both events in Discover within seconds with the same `search.id`.

### Task 4.4 — Cart and purchase events
- `add_to_cart` (and `remove_from_cart` if simple) from the verified 19.0 cart methods; `purchase` events (one per order line)
  written in the order-confirmation transaction.
- Tests: confirmed order → one event per line; failed or abandoned checkout → no purchase event; quantities and amounts correct.
- Manual: add to cart and check out as a guest; see the events in Discover.

### Task 4.5 — Kibana dashboards (FR7) [HUMAN if no browser access]
- Dashboards 1–6 of `04` §10 (7 comes with M7). Build in the Kibana UI (human, following the agent's panel-by-panel spec, or the agent
  with browser access), export with the saved-objects API into `kibana/`, `uv run shop kibana import` restores them on a clean Kibana.
- Manual: import on a fresh Kibana; generate some traffic by hand; watch the panels update with 5 s auto-refresh.

### Task 4.6 — Freshness probe
- `uv run shop probe events --count 200` per `04` §11.4; record a run.
- Manual: run it; read p50/p95/max.

### Task 4.7 — Milestone note and promotion
- Milestone note (with dashboard screenshots to capture); regression gate items 1–6 and 10; promotion; tag `m4-events`.

---

# M5 — Virtual shoppers (FR11)

**Goal:** Locust shoppers replay real ESCI queries against the shop: search, click, add to cart and buy, producing realistic events.
**Exit criteria:** smoke and load profiles run headless without errors; events tagged `traffic=virtual` with the run ID; a first
informal speed reading.
**Read:** `04` §9, §11.3; `02` §6.

### Task 5.1 — Shopper model and search/click flow
- `loadtest/locustfile.py` + `loadtest/shopper_model.toml` (`04` §9); traffic pool and qrels via the id map; Zipf query choice;
  typo injection; session and CSRF handling; result parsing; label-based clicks; headers (load-test key, run ID).
- Tests: shopper-model functions (typo generator, click probabilities, query sampler) with seeds.
- Manual: run 2 users in the Locust web UI; watch searches and clicks appear in Kibana.

### Task 5.2 — Cart and checkout flow
- Add-to-cart (as the browser does it, with CSRF) and guest checkout with the test payment provider. Odoo's payment step uses
  JavaScript: reproduce the same HTTP calls the browser makes (inspect them in the browser's network tab or the 19.0 source).
  Time box: 1 day. Fallback: a test-only checkout route guarded by the load-test key that runs the same ORM steps (documented as a simulation shortcut).
- Manual: a 5-user run produces confirmed orders and purchase events.

### Task 5.3 — Run profiles and reports
- Profiles `smoke` (5 users, 2 min), `load` (50 users, 10 min), `detection` and `speed` placeholders for M8; headless CSV/HTML in
  `results/<run-id>/` with `run.json`; `uv run shop shoppers run --profile <name>`.
- Manual: run `smoke` then `load`; read Locust's p95 for the search page and the error rate; note it in STATUS.md.

### Task 5.4 — Milestone note and promotion
- Milestone note; regression gate items 1–6, 9 and 10; promotion; tag `m5-shoppers`.

---

# M6 — Lost-demand loop (FR8, FR9) — checkpoint "full loop works"

**Goal:** a scheduled job turns events into lost-demand signals; the buyer approves restock proposals that become draft RFQs;
when stock arrives the product is findable again.
**Exit criteria:** the full loop scenario passes end to end and is demonstrated to the supervisor.
**Read:** `01` §6.3, §10; `04` §8.

### Task 6.1 — Detection service
- Pure functions + Elasticsearch queries for the signals of `04` §8.2 (unsatisfied signal only if approved in Task 2.2);
  thresholds and window from settings; trend; `source=shop`, traffic filter.
- Tests: crafted event sets with a known answer (integration, unique index prefix); thresholds edge cases; REES46 events ignored.
- Manual: generate a few zero-result searches by hand; call the service from an Odoo shell; see the expected signals.

### Task 6.2 — Odoo models and scheduled job
- `lost_demand.run`, `lost_demand.signal`; scheduled action (default hourly) + "Run now"; idempotent upsert; run lock;
  manager/buyer views and menus; access rights.
- Tests: re-run same window → same records; parallel run refused; signal resolves when the condition disappears; access per group.
- Manual: run the job; open the signals list as buyer and as manager.

### Task 6.3 — Restock proposals and draft RFQs (FR9)
- `lost_demand.proposal` (states of `02` §14), suggested quantity heuristic (`04` §8.3, tooltip), approve → create or extend a
  **draft** RFQ per vendor, dismiss with reason; links proposal ↔ signal ↔ RFQ line; no duplicates for the same product while open.
  Products without vendor → asked-for entry instead (basic version; full FR10 list in M9).
- Tests: grouping by vendor, quantities, no confirmation ever automatic, duplicate prevention, access rights.
- Manual: approve two proposals for the same vendor → one draft RFQ with two lines.

### Task 6.4 — Full-loop scenario and checkpoint
- `uv run shop scenario full-loop`: make a product out of stock → virtual shoppers search for it → job → proposal → (human) approve →
  confirm RFQ → validate receipt → stock > 0 → reindex → search shows it in stock. Record timings.
- Human: perform the approval and confirmation steps in the backend; capture screenshots for the report.
- Milestone note; regression gate items 1–7, 9 and 10; promotion; tag `m6-loop`.

---

# M7 — REES46 replay (FR12)

**Goal:** 2019 REES46 events stream into Elasticsearch at an adjustable speed, as if live, and the stack holds 10M+ events.
**Exit criteria:** replay with speed control and resume works; ≥ 10M events stored; Volume dashboard usable.
**Read:** `04` §1–2, §7 (REES46 mapping), §11.5.

### Task 7.1 — Acquisition [HUMAN]
- Human: Kaggle account, accept the dataset terms, create the API token and place it as the current Kaggle CLI documents.
- `uv run shop data fetch rees46`: disk check, size/time estimate, "go", download with `uvx kaggle`, checksums and license in the manifest.
- Profile (aggregates only): rows per event type and month, categories, sessions.

### Task 7.2 — Streaming reader and mapping
- Chunked or lazy reading of the CSV files; mapping of `04` §7; deterministic `event.id`; date-range selection.
- Tests on a synthetic REES46-format fixture: mapping per event type, empty `category_code`, hashing, determinism; memory stays bounded.

### Task 7.3 — Replay engine
- `uv run shop replay --from 2019-10-01 --to 2019-10-07 --speed 60 [--max-rate N]`: time shift to now, pacing by speed,
  bulk ingestion with per-item error handling, checkpoint/resume, graceful stop (Ctrl+C), live metrics (events/s, lag).
- Tests: pacing math, resume without duplicates, stop and restart.
- Manual: replay one hour at high speed; stop; resume; watch the Volume dashboard.

### Task 7.4 — Volume run and dashboard 7
- Dashboard 7 (Volume) exported to `kibana/`. Run until ≥ 10M `rees46` events; monitor disk, heap, ingest rate; record a run.
- Manual: open dashboards on 30 days of data; note load times informally (the measured campaign is M8).

### Task 7.5 — Milestone note and promotion
- Milestone note; regression gate items 1–10; promotion; tag `m7-replay`.

---

# M8 — Evaluation campaign (spec §11)

**Goal:** measured, reproducible results for search quality, detection, speed, freshness and volume.
**Exit criteria:** `docs/evaluation/results.md` complete with run IDs, tables and figures; scope review done.
**Read:** `04` §11–13.

### Task 8.1 — Freeze [SUPERVISOR]
- Freeze configurations (tuned search ADR, thresholds, shopper model), versions, data checksums; protocol final version approved.
  Any later change requires a new protocol version and re-running every affected campaign.

### Task 8.2 — Search quality (test set, run once)
- `odoo`, `es_plain`, `es_tuned`, `es_tuned_stock` in HTTP mode; statistics; figures; misses analysis (worst queries per engine).

### Task 8.3 — Lost-demand detection (hidden catalog)
- Protocol `04` §11.2: apply, traffic, job, score, revert. Recall/precision, misses with reasons; secondary out-of-stock recall.

### Task 8.4 — Speed
- Protocol `04` §11.3, three repetitions; page p95, `took_ms` p95, error rate, machine profile.

### Task 8.5 — Freshness and volume
- Protocols `04` §11.4 and §11.5.

### Task 8.6 — Results report and scope review [SUPERVISOR]
- `docs/evaluation/results.md` (targets vs measured, confidence intervals, threats to validity, what failed and why);
  figures in `results/summary/`. Scope review: decide whether M9 and M10 fit the remaining time. Promotion; tag `m8-evaluation`.

---

# M9 — Shop extras (Should): FR4, FR5, FR10

**Goal:** autocomplete, filters and the full "customers asked for" list, without degrading search quality or speed.
**Exit criteria:** each feature accepted; dev-set NDCG and a Locust `speed` run show no regression (if a campaign number changes,
the report says which version was measured).

### Task 9.1 — Autocomplete (FR4)
- Suggestions index refreshed by a job from successful searches; server-side override of the 19.0 autocomplete route; product-name
  suggestions; < 100 ms budget with fallback to Odoo's suggestions. Tests + manual typing test.

### Task 9.2 — Filters and facets (FR5)
- Category, brand, price range, in-stock filters with aggregation counts (`post_filter`), integrated with the existing shop filter UI
  where possible. Tests (filters applied in Elasticsearch and re-checked by Odoo) + manual test.

### Task 9.3 — "Customers asked for" list (FR10)
- `lost_demand.asked_for` with counts, trend, candidate products from the full catalog, states and actions (add synonym, publish, create
  product, ignore); buyer views. Tests + manual test.

### Task 9.4 — Regression and promotion
- Dev-set NDCG, Locust `speed`, regression gate; promotion; tag `m9-extras`.

---

# M10 — Semantic search (Could): FR13

**Goal:** an optional embedding-based search beside keyword search, compared fairly.
**Exit criteria:** hybrid engine available behind a setting; dev-set comparison recorded; test-set result reported as an addendum
(the main comparison was frozen in M8).

### Task 10.1 — [SPIKE] Model and service
- Pick an open model that runs on CPU (license, size, latency per query, embedding dimension); `embedder` service (profile `semantic`).

### Task 10.2 — Embeddings in the index
- Offline batch embedding of products; `embedding` field (new index version + rebuild); query embedding with timeout and fallback.

### Task 10.3 — Hybrid fusion and evaluation
- Client-side RRF or normalized linear fusion in `services/`; tune on the dev set; report test-set NDCG as an addendum with the same protocol.

---

# M11 — Pilot, report, presentation

**Goal:** a real shop owner has seen it, the report is written, the defense is ready, and a stranger could set the project up from the README.
**Exit criteria:** fresh-machine setup proven; pilot feedback recorded; report and slides validated by the supervisor; final tag.

### Task 11.1 — Fresh-machine setup test [HUMAN]
- On a second laptop (or a clean user account): follow the README only, time each step, run the doctor, fix every gap in docs or scripts.

### Task 11.2 — Pilot demo and interview #2 [HUMAN]
- Demo script for a shop owner (their language, no jargon); `docs/pilot/interview-guide-2.md` (what is useful, what is missing, would they
  adopt it, what they would pay attention to); anonymised notes; summary of feedback for the report.

### Task 11.3 — Final report [SUPERVISOR]
- Outline approved first (university template and language). Draft sections from `docs/` (architecture, ADRs, milestone notes,
  evaluation results); every number linked to its run ID; synthetic data labelled; figures from scripts; screenshots captured by the human.

### Task 11.4 — Slides, demo script and backup video
- Slides from the report; rehearsed demo script (`03` §13); a recorded backup video.

### Task 11.5 — Final release
- Demo freeze; final regression gate; `docs/progress/CHANGELOG.md`; tag `v1.0`; `results/summary/` and `docs/setup/VERSIONS.md` final.

---

## Task definition template (for new or re-planned tasks)

```text
### Task X.Y — <Title> (<FR IDs>) [HUMAN] [SUPERVISOR] [SPIKE]
Goal: one sentence.
Scope: bullet list of what is built.
Out of scope: what must not be touched.
Odoo source to read first: <.odoo-src paths / grep hints>.
Acceptance criteria: observable, testable statements.
Failure behavior: what must degrade gracefully (Elasticsearch down/slow, bad input).
Data / index / schema: models, fields, templates, mappings, slice changes; rebuild needed?
Automated: tests to write and checks to run.
Manual: exact supervisor steps and expected results.
Human / supervisor actions: if any.
```
