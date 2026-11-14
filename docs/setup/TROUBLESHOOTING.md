# Troubleshooting

Start with `uv run shop doctor` (add `--verbose` for every hint). Each WARN or FAIL line ends with a fix hint;
this page explains the ones that need more than one command. Add every new problem you solve here.

| Symptom | Likely cause | Fix |
|---|---|---|
| Doctor: `daemon ... not reachable` | Docker Desktop not started (Windows/macOS) or the service is stopped (Linux) | Start Docker Desktop and wait for "Engine running"; Linux: `sudo systemctl start docker` |
| Doctor: `memory for Docker` WARN/FAIL | Docker's VM has too little memory for the `standard` profile | Windows: edit `%USERPROFILE%\.wslconfig` (`[wsl2]` `memory=10GB`), then `wsl --shutdown` — this stops **every** running container, including other projects'. macOS: Docker Desktop > Settings > Resources. Or keep the `lowmem` profile |
| Elasticsearch container exits shortly after start, logs mention `vm.max_map_count`; doctor `vm.max_map_count` FAIL | Kernel setting too low in the Docker VM | Windows (until restart): `wsl -d docker-desktop -u root sysctl -w vm.max_map_count=262144`; persistent: `.wslconfig` → `[wsl2]` `kernelCommandLine = "sysctl.vm.max_map_count=262144"` (verify on your WSL version), then `wsl --shutdown`. Linux: `sudo sysctl -w vm.max_map_count=262144` and a file in `/etc/sysctl.d/` |
| Elasticsearch killed (exit 137) or very slow | Heap too large for Docker's memory | Lower the heap in `.env` or raise Docker memory; use the `lowmem` profile |
| Kibana stuck on "server is not ready yet" | `kibana_system` password not set or wrong; `es-setup` failed | `uv run shop logs es-setup`; re-run it with `docker compose up -d es-setup` |
| `shop up` fails, doctor: `service es-setup exited (1)` | Elasticsearch rejected a setup step (the log names the request and the answer) | `uv run shop logs es-setup`. On a brand-new cluster the license appears a few seconds after the cluster is healthy; es-setup waits up to 60 s for it |
| `401` from Elasticsearch or Kibana (doctor: `rejected (HTTP 401)`) | A password in `.env` changed after the stack was set up | `docker compose up -d es-setup` resets the `kibana_system`, `odoo_app`, `shop_tools` and personal passwords from `.env`. Exception: `ELASTIC_PASSWORD` is fixed when the data volume is first created; changing it in `.env` later breaks es-setup |
| Kibana exits with code 137, or restarts while dashboards load | Kibana reached its memory limit (`KIBANA_MEM_LIMIT`) | Raise `KIBANA_MEM_LIMIT` in `.env`, then `uv run shop up`. Measured values: `docs/ai/01_ARCHITECTURE.md` §5.3 |
| Elasticsearch shows `exited (137)` after `docker compose stop` | It was killed before a clean shutdown (Docker's default 10 s grace period) | `compose.yaml` gives it 60 s (`stop_grace_period`); exit 143 after a stop is the normal clean exit |
| License shows `trial` | Started with a script or setting that enables a trial | `xpack.license.self_generated.type=basic`; never use Elastic's start-local script |
| Doctor: `port NNNN ... in use by another program`; Docker: `port is already allocated` | Another program listens on the port (a native Odoo or PostgreSQL service, another stack) | Windows: `Get-NetTCPConnection -LocalPort NNNN -State Listen` gives the process ID; stop that program or service. macOS/Linux: `lsof -iTCP:NNNN -sTCP:LISTEN` |
| `/bin/sh^M` or `\r` errors in containers; doctor `core.autocrlf` WARN | CRLF line endings | `uv run shop doctor --fix` (sets `core.autocrlf false` for this repository); `.gitattributes` forces LF; re-checkout the affected files |
| Parquet files are a few hundred bytes | Git LFS pointers, objects not downloaded | `git lfs install`, then `git lfs pull` in the ESCI clone |
| Kaggle `403` | Dataset terms not accepted or token missing | Accept the terms on the dataset page; place the token as the Kaggle CLI documents |
| Doctor: `Python 3.12 ... not found`, or `uv python install` from the Claude desktop app is invisible to other terminals | The Claude desktop app is a packaged (MSIX) app: Windows redirects its writes under `%APPDATA%`/`%LOCALAPPDATA%` to a private folder | Run `uv python install 3.12` from a normal terminal (details in `ENVIRONMENT.md`, "Problems met") |
| `bootstrap.ps1 cannot be loaded because running scripts is disabled` | PowerShell execution policy | `powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1` |
| PyCharm cannot see Docker | Docker Desktop not running, or WSL integration off | Start Docker; check PyCharm's Docker connection settings |
| Very slow Odoo reloads on Windows | Bind mount from the Windows file system (no file-change events) | Restart the Odoo container after Python changes (ADR-014) |
| `docker-compose: command not found` but `docker compose` works | Compose v1 vs v2 | Always use `docker compose` |
