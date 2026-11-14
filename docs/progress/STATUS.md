# STATUS

Updated: 2026-11-14 by agent session 5 — HANDOFF: a fresh session starts Task 2.3a from here

## Current position
- Milestone: M2 — Datasets, evaluation protocol, catalog import — in progress. M1 released 2026-11-14 (PR #22,
  merge commit f3926a1, tag `m1-stack`)
- M2 order: 2.1 ✓ → 2.2 ✓ → 2.3a → 2.3b → 2.4 (split 2.4a/2.4b proposed, to confirm) → 2.5 → 2.6. Task 1.6
  (interview) still open, in parallel
- Task: **2.3a — slice builder, part a** — state: **go given by the supervisor (2026-11-14), not started**; plan in
  "Next step" below. Tasks 2.1 and 2.2 merged 2026-11-14; protocol tagged `protocol-v1`
- Branch / PR: `feat/slice-query-sets` (from `develop` 5689f1e) — draft PR to `develop`, opened with this handoff
- Local checkout: on `feat/slice-query-sets`; no other worktree; ESCI in `data/raw/esci/` (3 files, verified)
- Repository: https://github.com/akramnemri/odoo-search-lost-demand (public, default branch `develop`)

## Milestone 0 exit check (2026-10-28)
- `uv run shop doctor` (M0 sections): 30 OK, 5 WARN, 0 FAIL — WARN = 4 stack images not pulled, `.odoo-src/` missing
  (both expected before M1)
- `docs/setup/VERSIONS.md` approved by the supervisor (ADR-018 accepted)
- Scaffold, `shop` CLI, doctor and CI merged into `develop` (PRs #1–#5); CI green on `develop` after the merge
- CI green on PR #5: `lint`, `tools (ubuntu-24.04)`, `tools (windows-2025)`; failure demonstrated on PR #6 (closed)
- `main` still holds only the prompt pack: the first promotion `develop` → `main` is Task 1.7 (tag `m1-stack`)

## Environment
- Doctor: 50 OK, 0 WARN, 0 FAIL, 4 SKIP — 2026-11-14 with the stack up (free disk 72 GB after the supervisor freed
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
- REES46: not yet (13.67 GB; usage rules in ADR-012)
- Odoo source copy: `.odoo-src/odoo/` from `odoo:19.0-20261015` (Odoo `19.0.post20261015`), 38,948 files, 409 MB,
  translations (`*.po`) excluded, 19 font symlinks skipped; copied in 320 s; provenance in `.odoo-src/SOURCE.toml`
- Odoo database: `shop`, recreated 2026-11-06 by `shop db reset` in 87 s (supervisor-approved, to give the integration
  user the "Products / Create" group); 86 modules, no demo data, company and website "Lost Demand Demo Shop", USD,
  generic chart of accounts, en_US, Demo payment provider (test), guest checkout on; integration user
  `shop_integration` with a JSON-2 API key in `.env`; 1 product ("Standard delivery"), 0 sale orders
- Snapshots (`local/snapshots/`): `baseline-empty` (2026-11-06, 6.9 MB: the state above, use this one);
  `after-1-2a-manual-test` (2026-11-06, older: its integration user cannot create products)
- Module `website_sale_lost_demand` 19.0.0.1.0: installed in `shop` from Apps on 2026-11-06 (browser re-test of 1.3);
  snapshot `baseline-empty` is the state without it. `shop` also holds an archived throwaway user `ld_tester`
  (internal, Website designer) from that test. `shop test module` uses a throwaway `shop_test`, dropped after
  each run
- Elasticsearch: users `odoo_app`, `shop_tools`, personal Kibana user `supervisor` (built-in `editor` role); no indices
- Product index: none
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

## Latest results
- none (no evaluation yet)

## Decisions since last milestone
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
- The doctor reads the Compose project name from `compose.yaml` and ignores `COMPOSE_PROJECT_NAME`: with a second
  project (the isolated regression run) its port checks fail. Small follow-up, not blocking
- The supervisor's kind cluster (`mlops-lab-*`, `kind-registry`, another project) restarts with Docker Desktop; the agent
  stopped it on request (2026-11-14), never removed
- `shop test module` takes about 85–90 s (fresh `shop_test` with `website_sale` and its dependencies) and runs a second
  Odoo process in the `odoo` container next to the development server
- Kibana and Elasticsearch memory under real dashboard and indexing load is not measured yet (M4, M7, M8)
- The PostgreSQL password was shown once in the agent chat (process list check, before the fix); it never reached
  the repository. Rotate it if the transcript is shared (needs `ALTER USER` on the existing volume)

## Waiting on human / supervisor
- Calendar of milestone dates in `docs/ai/05_ROADMAP.md` (optional, helps warn about delays)
- A local shop owner for interview #1 (Task 1.6) — start looking early

## Next step (exact)
- **Agent (fresh session): implement Task 2.3a** on `feat/slice-query-sets` (go already given 2026-11-14; read
  `docs/evaluation/protocol.md` §2–3, §6.1, §6.3 and `04` §3–4 first). Approved plan:
  - `uv run shop data build-slice [--dry-run]`; config `tools/shoptools/data/slice.toml` (seed `20261025`, sizes,
    locale `us`, `small_version = 1`); derived seed streams per step (`dev-queries`, `test-queries`, `typos`, …) with
    the standard library's `random` (no new dependency)
  - dev = 300 queries from the ESCI train split; test = 700 from the test split after removing queries whose
    normalized text equals a dev query (normalization of `04` §8.1: NFKC, case-fold, trim, collapse whitespace, strip
    surrounding punctuation; a shared normalizer in `tools/shoptools/data/`, to be reused by the module in M4)
  - qrels (query id, product id, label, gain E 1.0 / S 0.1 / C 0.01 / I 0) for dev + test; catalog = all judged
    products of dev + test, read from the 1.1 GB products file in column batches (memory < 2 GB); product text fields
    kept for 2.3b and the import
  - `test-typo`: one seeded edit (swap, delete, duplicate, keyboard-neighbour) in one word of ≥ 4 letters per test query
  - outputs in `data/processed/` (Parquet, sorted rows) + a slice manifest (counts, seed, config hash, output SHA-256);
    deterministic (same seed → same hashes)
  - tests on synthetic ESCI-format fixtures: determinism, dev ∩ test = ∅ by id and by normalized text, every judged
    product in the catalog, typo = exactly one edit, counts
  - then STATUS, PR, task report, manual test (run twice, compare hashes)
- Then Task 2.3b (enrichment: categories `categories.toml`, synthetic price/stock/vendor; hidden-dev, hidden-test,
  out-of-stock sets, stratified, E-targets only; `results/summary/enrichment-report.md`)
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
