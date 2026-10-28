# 06 — Environment Setup: Detect, Pin, Install, Verify

Act as the engineer who makes a student laptop ready for this project quickly and repeatably.

Finding the right versions and setting tools up is the most time-consuming part of starting this project.
Your job in Milestone 0 is to do it **for** the supervisor: detect what is installed, verify which versions to use,
propose an install plan, install with approval, verify, and record everything so the next machine takes minutes.
After Milestone 0, `uv run shop doctor` re-checks the whole environment in one command.

---

## 1. Principles

1. **Detect before you install.** Read-only inventory first. Never reinstall something that already works at a compatible version.
2. **Verify versions online, never from memory.** Use official sources (vendor docs, release notes, Docker Hub, PyPI).
   Record the source URL and the date you checked.
3. **Official sources only.** OS package managers (winget, Homebrew, apt with vendor repositories) or the vendor's documented
   installer. No random download sites, no unofficial scripts.
4. **One tool at a time, with approval.** For each install: name, version, source, exact command, size, time,
   admin rights or reboot needed. Wait for "go". Verify right after installing.
5. **User-level when possible.** Prefer per-user installs (uv, Toolbox). System-level installs (Docker, WSL) are announced as such.
6. **Pin everything.** No `latest` tags. Docker images, Python packages and tools are pinned in files committed to the repository.
7. **Record everything.** `docs/setup/VERSIONS.md` (what and why), `docs/setup/ENVIRONMENT.md` (how, per OS),
   `local/machine-report.md` (this machine, git-ignored).
8. **Do not fight the machine silently.** If something fails twice, stop, report what you tried and the exact error, and propose options.

---

## 2. What the project needs

### 2.1 Machine

| Resource | Recommended | Minimum | Why |
|---|---|---|---|
| RAM | 16 GB | 8 GB (`lowmem` profile) | Odoo + PostgreSQL + Elasticsearch + Kibana + IDE + browser |
| Memory available to Docker | 8–10 GB | 5–6 GB | Measured by `docker info` |
| CPU | 4+ cores | 2 cores | Load tests and replay |
| Free disk | 50 GB | 35 GB | Images ≈ 4–5 GB, ESCI ≈ 2.5 GB (+ extracted), REES46 ≈ 14 GB uncompressed, Elasticsearch data for 10M+ events, Odoo source copy, snapshots |
| OS | Windows 10/11 with WSL2, macOS 13+, Ubuntu 22.04/24.04 (or equivalent) | | Docker support |
| Virtualization | Enabled in BIOS/UEFI | | Required by Docker on Windows and by WSL2 |

### 2.2 Tools

| Tool | Required | Purpose | Detect with |
|---|---|---|---|
| Git | Yes | Version control | `git --version` |
| Git LFS | Yes | ESCI files are stored with Git LFS | `git lfs version` |
| GitHub CLI (`gh`) | Recommended | PRs, issues, task board from the terminal | `gh --version`, `gh auth status` |
| uv | Yes | Python versions, virtual environments, locked dependencies, `uv run shop` | `uv --version` |
| Python | Via uv | Host tools (version = Odoo image's Python minor) | `uv python list` |
| Docker Desktop (Windows/macOS) or Docker Engine (Linux) | Yes | The stack | `docker version`, `docker info` |
| Docker Compose v2 | Yes | `docker compose` (v1 `docker-compose` is not supported) | `docker compose version` |
| WSL2 (Windows only) | Yes | Docker Desktop backend | `wsl --status`, `wsl -l -v` |
| PyCharm (via JetBrains Toolbox) | Yes (spec) | IDE, Odoo debugging | Toolbox / install folder |
| A modern browser | Yes | Shop, Odoo backend, Kibana | — |
| Kaggle CLI | Milestone 7 | REES46 download (run with `uvx`, no global install) | `uvx kaggle --version` |

Python libraries are never installed globally: they are declared in `pyproject.toml` (dependency groups: `dev`, `data`,
`load`, `eval`, `semantic`) and locked in `uv.lock`. The Odoo image gets only the pinned `elasticsearch` client.

### 2.3 Docker images (pulled by Compose, sizes announced before pulling)

Odoo 19.0 (dated tag), PostgreSQL (pinned major), Elasticsearch 9.x and Kibana 9.x (same exact version),
a tiny `alpine`/`busybox` image for kernel checks. Later, optionally, the embedding service image (FR13).

---

## 3. Version selection policy

| Component | Rule |
|---|---|
| Odoo | 19.0 Community (spec), pinned to a **dated official tag** (e.g. `19.0-YYYYMMDD`) for reproducibility. Never 20 during the project |
| Python (host) | Same minor version as the Python inside the pinned Odoo image (check with `docker run --rm <image> python3 --version`). Odoo 19 officially requires Python ≥ 3.10 |
| PostgreSQL | A major version supported by Odoo 19 (official minimum: 13). Pick the newest one Odoo documents or tests, justify it in VERSIONS.md (check `odoo/release.py` in the source copy) |
| Elasticsearch + Kibana | Latest patch of the current 9.x minor at project start; **identical** versions; never a trial license |
| `elasticsearch` Python client | Same major as the server; minor ≤ server minor (check Elastic's client compatibility policy) |
| Locust, pandas, pyarrow, sentence-transformers… | Latest stable compatible with the pinned Python, locked by uv |
| Docker | Current stable Docker Desktop / Engine with Compose v2 |
| PyCharm | Current stable release |

Upgrades during the project: patch versions only, at milestone boundaries, with an ADR line and a full regression check.

### 3.1 Starting points found on 2026-10-28 (verify in Task 0.2, do not trust blindly)

| Component | Starting point | Where to verify |
|---|---|---|
| Odoo 19 requirements | Python ≥ 3.10, PostgreSQL ≥ 13 (official "install from source" page for 19.0) | odoo.com documentation 19.0; `odoo/release.py` |
| Elastic Stack | 9.5.5 was the latest release listed on Elastic's release-notes page | elastic.co release notes; Docker image tags on `docker.elastic.co` |
| Odoo external API | Odoo 19 deprecates XML-RPC/JSON-RPC (removal planned for Odoo 22) in favour of the JSON-2 API (`/json/2/<model>/<method>`, API key in a bearer header) | Odoo 19.0 developer documentation |
| Elastic features on Basic | kNN/vector search: free. RRF and linear retrievers: Enterprise only | Elastic subscriptions page; a quick call on the running cluster |
| ESCI | Apache-2.0; ≈ 2.5 GB download | `amazon-science/esci-data` repository |
| REES46 | Kaggle `mkechinov/ecommerce-behavior-data-from-multi-category-store`; `2019-Nov.csv` ≈ 9 GB | Kaggle dataset page (license, terms) |
| PyCharm | Unified product since 2025.1 (core features free, Pro features with subscription; students can get Pro free). The Docker Compose interpreter page shows no Pro restriction, but check in the installed version | jetbrains.com |

### 3.2 Feature-license table (keep in `docs/setup/VERSIONS.md`)

| Elastic feature | Needed for | Tier (verify on the pinned version) | Decision |
|---|---|---|---|
| Security: users, roles, passwords | Spec security | Free (Basic) | Used |
| Index templates, data streams, ingest pipelines, ILM | Events | Free | Used |
| Synonyms API / synonym sets | FR2 | Verify on the running cluster | Used if free, else file/inline fallback |
| `search_as_you_type`, completion, aggregations, `function_score` | FR2–FR5 | Free | Used |
| `dense_vector` + kNN | FR13 | Free | Used if FR13 is built |
| Transforms | Optional (unsatisfied signal) | Verify | Optional |
| RRF / linear retrievers | — | Enterprise | **Not used** (fusion in the module) |
| Learning to Rank, ELSER, E5, ML anomaly detection | — | Paid | **Not used** |
| Kibana Lens, dashboards, Discover | FR7 | Free | Used |

---

## 4. The bootstrap procedure (Milestone 0)

```text
Phase A  Inventory (read-only)        -> local/machine-report.md + summary table      -> STOP (Task 0.1)
Phase B  Version matrix (research)    -> docs/setup/VERSIONS.md + ADR                 -> STOP for approval (Task 0.2)
Phase C  Install plan                 -> table: tool, command, source, size, admin?, reboot?
Phase D  Install, one tool at a time  -> verify after each; human handles UAC/sudo/reboots
Phase E  Configure                    -> git, Docker resources, kernel setting, WSL, IDE
Phase F  Verify and record            -> inventory again: all required items green;
                                         docs/setup/ENVIRONMENT.md updated            -> STOP (Task 0.3)
```

### 4.1 Phase A — inventory commands (read-only)

Use the commands for the detected OS; do not fail if a tool is missing, just record it.

- OS and hardware: Windows `systeminfo`, PowerShell `Get-CimInstance Win32_OperatingSystem, Win32_Processor, Win32_ComputerSystem`;
  macOS `sw_vers`, `sysctl -n hw.memsize hw.ncpu`, `uname -m`; Linux `cat /etc/os-release`, `free -b`, `nproc`, `uname -m`.
- Disk: free space on the repository drive (and on `C:` for Docker Desktop's WSL disk on Windows).
- Package managers: `winget --version`; `brew --version`; `apt --version`, `snap --version`.
- Tools: every "Detect with" command of §2.2.
- Docker: `docker version`, `docker compose version`, `docker info --format "{{.MemTotal}} {{.NCPU}} {{.OperatingSystem}}"`,
  kernel setting `docker run --rm alpine sysctl -n vm.max_map_count` (only if Docker runs; tiny image — mention the pull).
- Windows extras: `wsl --status`, `wsl -l -v`, contents of `%USERPROFILE%\.wslconfig` if present, where the repository lives
  (Windows drive vs WSL file system), `git config --get core.autocrlf`.
- Conflicts: processes listening on ports 8069, 8072, 9200, 5601, 8089; a local PostgreSQL service; legacy `docker-compose` v1;
  proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`).

### 4.2 Phase D — install commands (verify package IDs and commands at execution time)

**Windows** (PowerShell; winget triggers UAC when needed — the human clicks):

```powershell
winget install --id Git.Git -e --source winget              # includes Git LFS
winget install --id GitHub.cli -e --source winget
winget install --id astral-sh.uv -e --source winget
wsl --install                                               # admin + reboot, only if WSL2 is missing
winget install --id Docker.DockerDesktop -e --source winget # then first launch: accept terms, WSL2 backend
winget install --id JetBrains.Toolbox -e --source winget    # then install PyCharm from Toolbox
```

**macOS** (Homebrew; install Homebrew itself only with approval, from brew.sh):

```bash
brew install git git-lfs gh uv
brew install --cask docker-desktop      # cask name may differ: check `brew search docker`
brew install --cask jetbrains-toolbox
```

**Linux (Ubuntu/Debian)** (sudo needed — the human runs privileged commands if the agent cannot enter a password):

```bash
sudo apt-get update && sudo apt-get install -y git git-lfs ca-certificates curl
# Docker Engine + Compose plugin: follow https://docs.docker.com/engine/install/ (official apt repository),
# packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"         # then log out and back in
# GitHub CLI: official apt repository from https://cli.github.com
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv official installer (user level)
# JetBrains Toolbox: tarball from jetbrains.com/toolbox-app
```

Then, on every OS: `uv python install <pinned version>` (inside the repository, `.python-version` pins it) and `git lfs install`.

**Docker Desktop license note.** Docker Desktop is free for personal use, education and small businesses.
If the laptop belongs to a company above Docker's size/revenue thresholds (for example an internship host company),
check the license; alternatives are Docker Engine inside WSL2/Linux. Record the choice in an ADR.

### 4.3 Phase E — configuration

| Item | Windows | macOS | Linux |
|---|---|---|---|
| Git identity | `git config --global user.name/user.email` (values from the human) | same | same |
| Line endings | `git config --global core.autocrlf false` + repository `.gitattributes` forcing LF | — | — |
| Long paths | `git config --global core.longpaths true` | — | — |
| Docker memory/CPU | `%USERPROFILE%\.wslconfig` → `[wsl2]` `memory=6GB` (lowmem) or `10GB` (standard), `processors=4`, `swap=4GB`; then `wsl --shutdown` | Docker Desktop → Settings → Resources (human) | Not limited by default |
| `vm.max_map_count ≥ 262144` (Elasticsearch) | Persistent: `.wslconfig` → `kernelCommandLine = "sysctl.vm.max_map_count=262144"` (verify); temporary: `wsl -d docker-desktop -u root sysctl -w vm.max_map_count=262144` | Usually already set by Docker Desktop; check with the alpine command | `sudo sysctl -w vm.max_map_count=262144` + file in `/etc/sysctl.d/` |
| Repository location | Prefer a short path without spaces; for faster bind mounts and file watching consider the WSL file system (decide with the supervisor; ADR) | Default | Default |
| Docker running at login | Docker Desktop setting (human choice) | same | `systemctl enable docker` |

Apply changes, restart Docker if needed, re-run the inventory.

### 4.4 Phase F — record

- `docs/setup/VERSIONS.md`: pinned versions, sources, verification dates, feature-license table.
- `docs/setup/ENVIRONMENT.md`: the steps that actually worked, per OS, and the problems met (no personal paths or usernames).
- `local/machine-report.md`: this machine's inventory (git-ignored).
- STATUS.md: environment state (doctor result and date).

---

## 5. Odoo source copy (for reading and IDE navigation)

The agent must read the real 19.0 code before overriding it. Keep an exact copy of the code that runs:

1. Preferred: copy the Odoo package out of the pinned image, so it matches the running version exactly
   (find its path with `docker run --rm <image> python3 -c "import odoo, os; print(os.path.dirname(odoo.__file__))"`,
   then `docker create` + `docker cp` into `.odoo-src/`).
2. Alternative: `git clone --depth 1 --branch 19.0 https://github.com/odoo/odoo.git .odoo-src` (may differ slightly from the image's build date).

`.odoo-src/` is git-ignored. Search it with `rg`/`grep` or the IDE; never edit it.

## 6. IDE setup (PyCharm)

- Open the repository root. Interpreter for `tools/` and tests: the uv environment (`.venv`), which recent PyCharm versions detect.
- Odoo debugging (default, ADR-014): add an interpreter **On Docker Compose** using `compose.yaml` and the `odoo` service;
  create a run/debug configuration that starts Odoo in that container with our addons path and the development database;
  set path mappings (`addons/` ↔ `/mnt/extra-addons`); attach `.odoo-src/` as an additional content root for navigation.
  Acceptance: a breakpoint in a module controller stops when the page is opened.
- If this feature is unavailable in the installed edition, or breakpoints do not work within a 2-hour time box, use the fallback:
  run Odoo from source on the host (uv virtual environment with Odoo's `requirements.txt`, same Python minor as the image)
  with PostgreSQL and Elasticsearch still in Docker. Document the decision in `docs/setup/PYCHARM.md` and the ADR.
- Odoo tests can also be launched from PyCharm with the same interpreter (`--test-enable --test-tags /website_sale_lost_demand --stop-after-init`).

---

## 7. The doctor (`uv run shop doctor`)

A cross-platform, read-only health check of everything this project depends on. Built in Task 0.5,
extended in later milestones.

### 7.1 Behavior

- Read-only by default. `--fix` performs only safe repository/user-level actions after asking
  (create `.env` from `.env.example` with generated secrets, `git lfs install`, repository-local git settings). It never installs software.
- Output: one line per check with status `OK`, `WARN`, `FAIL` or `SKIP`, the found value, the expected value, and a fix hint
  (command or doc link to `docs/setup/TROUBLESHOOTING.md`).
- Options: `--section <name>` (repeatable), `--json` (for CI and scripts), `--verbose`.
- Exit codes: 0 = no FAIL; 1 = at least one FAIL; 2 = the doctor itself crashed.
- Expected versions come from a machine-readable file (e.g. `docs/setup/versions.toml`) kept in sync with VERSIONS.md.
- Unit-tested: version parsing and comparison, each check's decision logic with fake command outputs.

### 7.2 Checks by section

| Section | Checks |
|---|---|
| `machine` | OS and architecture; RAM; CPU; free disk on the repository drive (WARN < 50 GB, FAIL < 20 GB); recommended RAM profile |
| `tools` | Git, Git LFS, gh (WARN only), uv, pinned Python available, Docker, Compose v2 — each against the minimum version |
| `docker` | Daemon reachable; memory and CPUs available to Docker vs profile; `vm.max_map_count ≥ 262144`; required images present (sizes if missing); WSL2 backend (Windows) |
| `ports` | 8069, 8072, 9200, 5601, 8089 free, or used by our own containers |
| `repo` | Inside the repository; `.env` present with every key of `.env.example`; no tracked file matches secret/data patterns; line-ending settings; `.odoo-src/` present (WARN) |
| `stack` | Containers up and healthy; `es-setup` exited 0 |
| `elastic` | Authenticated access with the tools user; cluster health; **license type = basic (FAIL otherwise)**; templates, pipeline, ILM, synonyms set present; product alias exists; doc count vs Odoo product count |
| `odoo` | HTTP health endpoint (verify path in 19.0); database exists; module installed and its version; outbox backlog; last flush and last lost-demand run |
| `kibana` | Status API green; data view and dashboards imported (WARN) |
| `data` | Dataset files present; sizes plausible (no Git LFS pointer files); SHA-256 match `data/manifest.toml`; processed slice present |

### 7.3 Bootstrap scripts

`scripts/bootstrap.ps1` (Windows PowerShell) and `scripts/bootstrap.sh` (macOS/Linux) do only this:
check that uv exists; if not, show the official install command and ask before running it; then run `uv sync` and
`uv run shop doctor`. They are the first thing a new team member runs after cloning.

---

## 8. Troubleshooting (seed for `docs/setup/TROUBLESHOOTING.md`)

| Symptom | Likely cause | Fix |
|---|---|---|
| Elasticsearch container exits shortly after start, logs mention `vm.max_map_count` | Kernel setting too low in the Docker VM | §4.3, then restart Docker |
| Elasticsearch killed (exit 137) or very slow | Heap too large for Docker's memory | Lower heap in `.env` or raise Docker memory; use `lowmem` profile |
| Kibana stuck on "server is not ready yet" | `kibana_system` password not set or wrong; `es-setup` failed | `docker compose logs es-setup`; re-run setup |
| `401` from Elasticsearch | Wrong user/password, `.env` changed after first start | Check `.env`; passwords are set at first initialization of the data volume |
| License shows `trial` | Started with a script or setting that enables trial | Set `xpack.license.self_generated.type=basic`; never use the start-local script (it starts a trial) |
| `port is already allocated` | Another program (often a local PostgreSQL or another Odoo) | Stop it, or change the published port in `.env` |
| `/bin/sh^M` or `\r` errors in containers | CRLF line endings | `.gitattributes` LF; `core.autocrlf false`; re-checkout the files |
| Parquet files are a few hundred bytes | Git LFS pointers, objects not downloaded | `git lfs install` then `git lfs pull` in the ESCI clone |
| Kaggle `403` | Dataset terms not accepted or token missing | Human: accept terms on the dataset page; place the token as documented by the Kaggle CLI |
| PyCharm cannot see Docker | Docker Desktop not running, or WSL integration off | Start Docker; check PyCharm Docker connection settings |
| Very slow Odoo reloads on Windows | Bind mount from the Windows file system | Restart the container after Python changes; or move the repository into the WSL file system (ADR) |
| `docker-compose: command not found` but `docker compose` works | Compose v1 vs v2 | Always use `docker compose` |
