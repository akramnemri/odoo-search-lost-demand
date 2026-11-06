# STATUS

Updated: 2026-10-29 by agent session 3 (Task 1.2a implemented, waiting for the supervisor's manual test)

## Current position
- Milestone: M1 — Docker stack, module skeleton, debugging, first interview — in progress
- M1 order (supervisor, 2026-10-29): 1.1a → 1.1b → 1.4a → 1.2a → 1.2b → 1.3 → 1.4b → 1.5 → 1.7; 1.6 in parallel, not blocking the tag
- Task: 1.2a — Database bootstrap (`uv run shop db create|reset`) — state: implemented, PR open, waiting for the manual test
- Branch / PR: `chore/db-bootstrap` — PR to `develop` (see the task report)
- Repository: https://github.com/akramnemri/odoo-search-lost-demand (public, default branch `develop`)

## Milestone 0 exit check (2026-10-28)
- `uv run shop doctor` (M0 sections): 30 OK, 5 WARN, 0 FAIL — WARN = 4 stack images not pulled, `.odoo-src/` missing
  (both expected before M1)
- `docs/setup/VERSIONS.md` approved by the supervisor (ADR-018 accepted)
- Scaffold, `shop` CLI, doctor and CI merged into `develop` (PRs #1–#5); CI green on `develop` after the merge
- CI green on PR #5: `lint`, `tools (ubuntu-24.04)`, `tools (windows-2025)`; failure demonstrated on PR #6 (closed)
- `main` still holds only the prompt pack: the first promotion `develop` → `main` is Task 1.7 (tag `m1-stack`)

## Environment
- Doctor: 47 OK, 0 WARN, 0 FAIL, 5 SKIP — run on 2026-10-29 with the stack up, after `uv run shop db create`
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
- ESCI: not yet (≈ 1.1 GB via Git LFS, Apache-2.0)
- REES46: not yet (13.67 GB; usage rules in ADR-012)
- Odoo source copy: `.odoo-src/odoo/` from `odoo:19.0-20261015` (Odoo `19.0.post20261015`), 38,948 files, 409 MB,
  translations (`*.po`) excluded, 19 font symlinks skipped; copied in 320 s; provenance in `.odoo-src/SOURCE.toml`
- Odoo database: `shop`, created 2026-10-29 by `shop db reset` in 90 s (dropped first: the blank database the server had
  auto-created at the first start, base only, no data); 86 modules, no demo data, company and website "Lost Demand
  Demo Shop", USD, generic chart of accounts, en_US, Demo payment provider (test), guest checkout on; integration user
  `shop_integration` with a JSON-2 API key in `.env`; no products yet
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
  `db_name` removed from `odoo.conf` — implemented 2026-10-29, not merged yet

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
  develop" (PR required, 0 approvals, required checks `lint`, `tools (ubuntu-24.04)`, `tools (windows-2025)`, no
  force-push, no deletion); squash + merge commits, no rebase; head branches auto-deleted
- Team: solo developer for now (supervisor, 2026-10-28); the specification lists a co-author who does not open PRs
- No GitHub issues or project board for now
- ADR-008, ADR-013, ADR-014 still Proposed (final after Tasks 4.2, 2.2, 1.4b)
- Personal Kibana user gets the built-in `editor` role (not read-only) because dashboards are built in the UI in
  Task 4.5; `01_ARCHITECTURE.md` §5.2 updated — approved by the supervisor 2026-10-29
- `.odoo-src/` layout `.odoo-src/odoo/...` and translations (`*.po`) excluded by default, `--with-translations` to
  include them (supervisor, 2026-10-29). Copy method: `tar` stream from `docker run --rm --network none`, not
  `docker create` + `docker cp` (no leftover container, exclusion at the source, symlinks skipped on Windows)
- Odoo image: client set pinned and hash-locked (`--require-hashes`, wheels only, `--no-deps`) after two SonarCloud
  findings on PR #8 (docker:S8541, docker:S8544); `typing-extensions` 4.16.0 shadows Ubuntu's 4.10.0 in `/usr/local`
- SonarCloud runs on PRs (added outside the agent, first seen on PR #8); not a required check
- `shop up` never pulls images: missing images stop it with the `docker compose pull` command (no surprise downloads)
- `stop_grace_period`: Elasticsearch 60 s, PostgreSQL 30 s (Elasticsearch was killed with exit 137 at Docker's default 10 s)
- Task 1.2 split into 1.2a (database) and 1.2b (snapshots) (supervisor, 2026-10-29). Company and website "Lost Demand
  Demo Shop", no country (generic chart); integration user with Sales, Inventory and Purchase Administrator rights, no
  Settings rights; persistent (non-expiring) API key, local `.env` only
- `db_name` removed from `odoo.conf` (supervisor, 2026-10-29, option A): with it, the 19.0 server creates a blank
  database (admin/admin) at every start (`odoo/cli/server.py::main`). `dbfilter = ^shop$` and `list_db = False` stay;
  scheduled jobs now run on every database owned by `odoo` (only `shop`). The empty auto-created database was dropped
- Kibana memory limit raised (supervisor, 2026-10-29): standard 1536m → 2g, lowmem 1g → 1280m; it idled at 75–88 %
  of the old limits. After the change: 1.34 of 2 GiB at startup (standard)

## Open issues / risks
- PyCharm Pro trial ends 2026-11-14. Plan: finish the Docker debugging task before then; otherwise apply for the
  JetBrains student license only if it is free with no bank card, else switch to a free alternative (decide in Task 1.4b)
- Docker memory 8.3 GB is at the low edge of `standard` and shared with another project's containers
- XML-RPC/JSON-RPC: deprecated in Odoo 19, removal planned in Odoo 22 (`.odoo-src/odoo/addons/rpc/controllers/__init__.py`);
  the tools use JSON-2 only (`POST /json/2/<model>/<method>`, bearer API key)
- Kibana and Elasticsearch memory under real dashboard and indexing load is not measured yet (M4, M7, M8)
- The PostgreSQL password was shown once in the agent chat (process list check, before the fix); it never reached
  the repository. Rotate it if the transcript is shared (needs `ALTER USER` on the existing volume)

## Waiting on human / supervisor
- Calendar of milestone dates in `docs/ai/05_ROADMAP.md` (optional, helps warn about delays)
- A local shop owner for interview #1 (Task 1.6) — start looking early

## Next step (exact)
- Supervisor: manual test of Task 1.2a (guest checkout with the Demo provider), then merge the PR into `develop`
- Agent after the merge: sync `develop`, delete the branch, then post the plan for **Task 1.2b** (snapshots). Facts for
  1.2b: `odoo db dump|load` exist in 19.0 (`.odoo-src/odoo/cli/db.py`, zip = SQL + filestore); the image's `pg_dump`/`psql`
  are 18.6 against server 16, and Odoo's restore runs `psql` without `ON_ERROR_STOP` (`service/db.py::restore_db`):
  verify the restored state, fall back to `pg_dump` 16 in the `db` container if needed
- Agent notes: detect-secrets flags `*_PASSWORD = "..."` and multi-key strings in tests — build test `.env` text from a
  dict, mark fake values with `# pragma: allowlist secret`; never print container command lines or `.env` values
- Agent note: `shop lint` (`pre-commit run --all-files`) skips untracked files and no git hook is installed:
  `git add` new files before running lint (PR #11 failed CI `lint` on two new files that passed locally)
- Agent note: `docker compose exec` forwards stdin; every Docker call without input now uses `stdin=DEVNULL` (it
  swallowed the `shop db reset` confirmation). The agent's background commands get no stdin: feed a prompt from a file
  in a foreground command
