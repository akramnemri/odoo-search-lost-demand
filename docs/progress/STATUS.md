# STATUS

Updated: 2026-10-28 by agent session 1 (Tasks 0.1–0.2)

## Current position
- Milestone: M0 — Environment bootstrap & repository foundation
- Task: 0.4 — Repository scaffold — state: planned (needs the code license decision)
- Branch / PR: none open
- Repository: https://github.com/akramnemri/odoo-search-lost-demand (public), created 2026-10-28

## Environment
- Doctor: not built yet (Task 0.5). Inventory: `local/machine-report.md` (git-ignored), 2026-10-28
- RAM profile: `standard` (15.7 GB RAM). Docker gets 7.76 GiB / 4 CPUs (`.wslconfig` memory=8GB), shared with another
  project's running stack (~0.4 GB used, ~2.4 GB of limits). Measure real usage in Task 1.1 before changing anything
- Stack versions: `docs/setup/VERSIONS.md` (approved 2026-10-28)
- Tools: Git 2.51, Git LFS 3.7, gh 2.102 (logged in), uv 0.13.6, Docker Desktop 4.60.1 (Compose v5.0.2), WSL 2.6.3,
  PyCharm 2026.2.3 (Pro **trial until 2026-11-14**). `vm.max_map_count` = 1048576 (OK). Ports 8069/8072/9200/5601/8089 free
- Python 3.12.16 (uv-managed) installed by the supervisor from a normal terminal; the app-private copy was deleted.
  `docker run --rm hello-world` OK (2026-10-28)
- Repository location: Windows drive, path with spaces (`...\Lost Demand (ERP+ Big Data)\odoo-search-lost-demand`); kept by supervisor decision
- Git: repository-local `core.autocrlf=false`, `core.longpaths=true`; global settings untouched
- Agent note: tools run from the Claude desktop app write `%APPDATA%`/`%LOCALAPPDATA%` into a private virtual folder.
  Anything that must be visible outside the app (managed Python, global tool installs) is installed by the supervisor
  from a normal terminal

## Data state
- ESCI: not yet (≈ 1.1 GB via Git LFS, Apache-2.0)
- REES46: not yet (13.67 GB; usage rules in ADR-012)
- Odoo database: none
- Product index: none
- Events stored: 0

## Last completed tasks
- 0.1 — Machine inventory (read-only) — confirmed by the supervisor 2026-10-28 (no PR: done before the repository existed)
- 0.2 — Version matrix, ADR-001…018, STATUS, glossary — approved and merged 2026-10-28 (PR #1, squash, merged by the agent on the supervisor's instruction)
- 0.3 — Install and configure prerequisites (uv, Python 3.12, ENVIRONMENT.md) — manual test passed, merged 2026-10-28 (PR #2, merged by the agent on the supervisor's instruction)

## Latest results
- none

## Decisions since last milestone
- 2026-10-28 — Repository `odoo-search-lost-demand`, public, on GitHub (supervisor)
- 2026-10-28 — Repository stays on the Windows drive, not the WSL file system (supervisor; consequence in ADR-014)
- 2026-10-28 — Native Odoo 17 service stopped and set to Manual to free port 8069 (supervisor)
- 2026-10-28 — No global git changes and no `.wslconfig` change (protect other repositories and the other Docker stack)
- 2026-10-28 — Version table approved (ADR-018): Odoo 19.0-20261015, PostgreSQL 16.15, Elastic 9.5.5, client 9.5.1, Python 3.12
- 2026-10-28 — PostgreSQL 16 kept (supervisor)
- 2026-10-28 — Docker Desktop stays at 4.60.1, no update (supervisor: protect the other project's stack)
- 2026-10-28 — REES46: academic use, attribution, raw data local and never redistributed (ADR-012)
- ADR-008, ADR-013, ADR-014 still Proposed (final after Tasks 4.2, 2.2, 1.4)

## Open issues / risks
- PyCharm Pro trial ends 2026-11-14. Supervisor plan: finish before then; otherwise apply for the JetBrains student license
  only if it is free with no bank card (official pages: free, university email / ISIC / GitHub Student Pack, 1 year,
  renewable, non-commercial; form not checked for payment fields), else switch to a free alternative (decide in Task 1.4)
- Docker memory 7.76 GiB is at the low edge of `standard` and shared with another project's containers
- Python 3.12 inside the Odoo image is inferred from `ubuntu:noble`; confirm at the first image pull (Task 1.1)
- XML-RPC/JSON-RPC deprecation timeline not re-verified (before Task 1.2)
- Spec PDF not yet in `docs/sources/`

## Waiting on human / supervisor
- Code license for the repository (Task 0.4); spec PDF for `docs/sources/`
- "go" for the Task 0.4 plan

## Next step (exact)
- Task 0.4 — repository scaffold on `chore/repo-scaffold`, once the code license is chosen
