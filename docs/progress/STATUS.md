# STATUS

Updated: 2026-10-28 by agent session 1 (Tasks 0.1–0.2)

## Current position
- Milestone: M0 — Environment bootstrap & repository foundation
- Task: 0.2 — Version matrix — state: awaiting supervisor approval of `docs/setup/VERSIONS.md`
- Branch / PR: `chore/version-matrix` — https://github.com/akramnemri/odoo-search-lost-demand/pull/1
- Repository: https://github.com/akramnemri/odoo-search-lost-demand (public), created 2026-10-28; pack committed on `main`, `develop` created from it

## Environment
- Doctor: not built yet (Task 0.5). Inventory: `local/machine-report.md` (git-ignored), 2026-10-28
- RAM profile: `standard` (15.7 GB RAM) — but Docker currently gets 7.76 GiB / 4 CPUs (`.wslconfig` memory=8GB),
  shared with another project's running stack (~0.4 GB used, ~2.4 GB of limits). Decide the Docker memory in Task 0.3
- Stack versions: see `docs/setup/VERSIONS.md` (proposed, not yet approved)
- Tools: Git 2.51, Git LFS 3.7, gh 2.102 (logged in), Docker Desktop 4.60.1 (Compose v5.0.2), WSL 2.6.3, PyCharm 2026.2.3 — present.
  uv missing. `vm.max_map_count` = 1048576 (OK)
- Repository location: Windows drive, path with spaces (`...\Lost Demand (ERP+ Big Data)\odoo-search-lost-demand`); kept by supervisor decision
- Git: repository-local `core.autocrlf=false` (system default is `true`); global settings untouched

## Data state
- ESCI: not yet (≈ 1.1 GB via Git LFS, Apache-2.0)
- REES46: not yet (13.67 GB; license to be confirmed)
- Odoo database: none
- Product index: none
- Events stored: 0

## Last completed tasks
- 0.1 — Machine inventory (read-only) — confirmed by the supervisor 2026-10-28 (no PR: done before the repository existed)

## Latest results
- none

## Decisions since last milestone
- 2026-10-28 — Repository `odoo-search-lost-demand`, public, on GitHub (supervisor)
- 2026-10-28 — Repository stays on the Windows drive, not the WSL file system (supervisor; consequence recorded in ADR-014)
- 2026-10-28 — Native Odoo 17 service to be stopped to free port 8069 (supervisor)
- ADR-001…ADR-017 written from `01` §3 (ADR-008, -013, -014 still Proposed); ADR-018 pinned versions (Proposed)

## Open issues / risks
- Port 8069 is held by the Windows service `odoo-server-17.0` (Automatic start). Needs an elevated shell to stop/disable
- Docker memory 7.76 GiB is below the `standard` range (8–10 GB) and is shared with another project's containers
- Docker Desktop 4.60.1 is old (latest 4.97.0); updating also affects the other project's stack
- REES46 Kaggle license is "Data files © Original Authors" (not an open license)
- PostgreSQL 16 is a justified choice, not an Odoo-documented maximum (Odoo publishes only the minimum, 13)
- Python 3.12 inside the Odoo image is inferred from `ubuntu:noble`; confirm at the first image pull (Task 1.1)
- XML-RPC/JSON-RPC deprecation timeline not re-verified (before Task 1.2)
- Spec PDF not yet in `docs/sources/`

## Waiting on human / supervisor
- Approve or correct `docs/setup/VERSIONS.md` (merge PR #1)
- Stop and disable the native Odoo 17 service (elevated PowerShell; commands in the Task 0.2 report)
- Decide REES46 use (academic, attribution, no redistribution) — with the academic supervisor if needed
- Code license for the repository (Task 0.4); spec PDF for `docs/sources/`

## Next step (exact)
- After the PR is merged: Task 0.3 — post the install/configure plan (uv; optional Docker Desktop update; git
  `core.autocrlf false` + `core.longpaths true`; Docker memory in `.wslconfig`; `git lfs install`) and wait for "go"
