# STATUS

Updated: 2026-10-29 by agent session 2 (Task 1.1a manual test passed; SonarCloud findings fixed before merge)

## Current position
- Milestone: M1 — Docker stack, module skeleton, debugging, first interview — in progress
- M1 order (supervisor, 2026-10-29): 1.1a → 1.1b → 1.4a → 1.2 → 1.3 → 1.4b → 1.5 → 1.7; 1.6 in parallel, not blocking the tag
- Task: 1.1a — Compose stack, images, es-setup, `.env` — state: manual test **passed** 2026-10-29, waiting for merge
- Branch / PR: `chore/compose-stack` → `develop`
- Repository: https://github.com/akramnemri/odoo-search-lost-demand (public, default branch `develop`)

## Milestone 0 exit check (2026-10-28)
- `uv run shop doctor` (M0 sections): 30 OK, 5 WARN, 0 FAIL — WARN = 4 stack images not pulled, `.odoo-src/` missing
  (both expected before M1)
- `docs/setup/VERSIONS.md` approved by the supervisor (ADR-018 accepted)
- Scaffold, `shop` CLI, doctor and CI merged into `develop` (PRs #1–#5); CI green on `develop` after the merge
- CI green on PR #5: `lint`, `tools (ubuntu-24.04)`, `tools (windows-2025)`; failure demonstrated on PR #6 (closed)
- `main` still holds only the prompt pack: the first promotion `develop` → `main` is Task 1.7 (tag `m1-stack`)

## Environment
- Doctor: 35 OK, 1 WARN (`.odoo-src/` missing, Task 1.4a), 0 FAIL — run on 2026-10-29 with the stack up
- Stack: `compose.yaml` (project `odoo-search-lost-demand`), clean start from empty volumes healthy in 94 s,
  restart in 37 s; images pulled 2026-10-29 (2.34 GB compressed)
- First memory reading (standard profile, idle, no data): Elasticsearch 2.63/3 GiB, Kibana 1.19/1.5 GiB,
  Odoo 0.10/1.5 GiB, PostgreSQL 0.08/1 GiB — Kibana and Elasticsearch near their limits; measure properly in 1.1b
- RAM profile: `standard` — 16.9 GB RAM; Docker 8.3 GB / 4 CPUs (`.wslconfig` memory=8GB, decimal GB as in the docs),
  shared with another project's running stack (~0.4 GB used, ~2.4 GB of limits). Measure real usage in Task 1.1
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
- Odoo database: none (`ODOO_DB_NAME=shop`, created in Task 1.2)
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
- 1.1a — Compose stack, Odoo image, es-setup, `shop env init` — manual test passed 2026-10-29 (PR #8, not merged yet)

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
- Odoo image: client set pinned and hash-locked (`--require-hashes`, wheels only, `--no-deps`) after two SonarCloud
  findings on PR #8 (docker:S8541, docker:S8544); `typing-extensions` 4.16.0 shadows Ubuntu's 4.10.0 in `/usr/local`
- SonarCloud runs on PRs (added outside the agent, first seen on PR #8); not a required check

## Open issues / risks
- PyCharm Pro trial ends 2026-11-14. Plan: finish the Docker debugging task before then; otherwise apply for the
  JetBrains student license only if it is free with no bank card, else switch to a free alternative (decide in Task 1.4)
- Docker memory 8.3 GB is at the low edge of `standard` and shared with another project's containers
- XML-RPC/JSON-RPC deprecation timeline not re-verified (before Task 1.2)
- The doctor's "port used by our stack" check assumes Compose's default project name; `compose.yaml` sets the same
  name, read it from there in Task 1.1b
- Kibana (1.19 of 1.5 GiB) may hit its memory limit under dashboards load; decide the limit in Task 1.1b
- Three empty volumes `lost-demand-cleanstart_*` remain from the clean-start test (no data); the supervisor may remove them
- The PostgreSQL password was shown once in the agent chat (process list check, before the fix); it never reached
  the repository. Rotate it if the transcript is shared (needs `ALTER USER` on the existing volume)

## Waiting on human / supervisor
- Calendar of milestone dates in `docs/ai/05_ROADMAP.md` (optional, helps warn about delays)
- A local shop owner for interview #1 (Task 1.6) — start looking early

## Next step (exact)
- Supervisor: merge PR #8 (`chore/compose-stack`) once CI and SonarCloud are green
- Then Task 1.1b: `shop up/down/status/logs`, doctor sections `stack`, `elastic`, `kibana`, memory measurement
