# Environment setup — what actually worked

How the development laptop was prepared in Milestone 0, per OS. Versions come from [`VERSIONS.md`](VERSIONS.md).
The rules behind these steps are in `docs/ai/06_ENVIRONMENT_SETUP.md`.

## Windows 11 (first machine, 2026-10-28)

Starting point: Git, Git LFS, GitHub CLI, Docker Desktop (WSL2 backend), WSL2 with Ubuntu, JetBrains Toolbox and
PyCharm were already installed. Only uv was missing.

### Steps

1. **uv** (user scope, no admin prompt):

   ```powershell
   winget install --id astral-sh.uv -e --source winget --version 0.13.6 --scope user
   ```

   winget adds `%LOCALAPPDATA%\Microsoft\WinGet\Links` to the user PATH: open a new terminal, then `uv --version`.

2. **Python 3.12 for the tools** — run in a normal terminal (Windows Terminal or PowerShell), **not** from a shell
   started by the Claude desktop app (see "Problems met"):

   ```powershell
   uv python install 3.12
   uv python list --only-installed
   ```

3. **Git settings for this repository only** (global settings are left alone so other repositories on the machine
   keep their behavior; `.gitattributes` enforces LF from Task 0.4):

   ```powershell
   git config --local core.autocrlf false
   git config --local core.longpaths true
   ```

4. **Git LFS**: already configured by the Git for Windows installer (`filter.lfs.process` present). Otherwise run `git lfs install`.

5. **Docker Desktop**: kept as installed (4.60.1, Compose v5). Memory for Docker comes from `%USERPROFILE%\.wslconfig`
   (`[wsl2] memory=8GB, processors=4, swap=2GB` on this machine → Docker sees 7.76 GiB, 4 CPUs).
   `vm.max_map_count` was already 1048576 (≥ 262144 needed by Elasticsearch); check with:

   ```powershell
   wsl -d docker-desktop cat /proc/sys/vm/max_map_count
   ```

   Changing `.wslconfig` requires `wsl --shutdown`, which stops **every** running container on the machine.

6. **Port 8069**: a native Odoo installation (Windows service `odoo-server-<version>`) held the port. In an
   Administrator PowerShell:

   ```powershell
   Stop-Service odoo-server-17.0
   Set-Service odoo-server-17.0 -StartupType Manual
   ```

7. **PyCharm**: installed from JetBrains Toolbox. The Pro subscription (trial or JetBrains student license) is
   activated under Help → Register.

### Problems met

| Problem | Cause | Fix |
|---|---|---|
| `uv python install` from the Claude desktop app reported `Missing expected target directory for Python minor version link`; the installed Python was invisible to other terminals and PyCharm | The Claude desktop app is a packaged (MSIX) app: Windows redirects its writes under `%APPDATA%` / `%LOCALAPPDATA%` to a private folder (`%LOCALAPPDATA%\Packages\Claude_…\LocalCache`). winget installs run outside the app and were not affected | Install managed Python versions from a normal terminal, then delete the app's private copy (`%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\uv`; remove the `cpython-3.12-…` junction with `rmdir` first so its target is not followed). Commands that only read Python or write inside the repository (`uv sync`, `uv run`) then work from both places |
| `uv python install 3.12` warned `Executable already exists at ~/.local/bin/python3.12.exe but is not managed by uv` | That launcher was created by the earlier attempt from the Claude app. It works (runs 3.12.16) | Harmless. Optional: `uv python install 3.12 --force` in a normal terminal so uv manages it |
| Port 8069 already in use | Native Odoo 17 Windows service | Step 6 |
| Git warned "LF will be replaced by CRLF" on first `git add` | Git for Windows sets `core.autocrlf=true` system-wide | Step 3 (repository-local only) |

## macOS / Linux

Not set up yet. Follow `docs/ai/06_ENVIRONMENT_SETUP.md` §4.2–4.3 and record here what worked.
