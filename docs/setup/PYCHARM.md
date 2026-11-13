# PyCharm: debugging Odoo in Docker

Task 1.4b, ADR-014. Odoo runs in its container; PyCharm debugs it through a **Docker Compose interpreter**.
Tested with PyCharm 2026.2.3 (build PY-262.10968.92, Pro trial until 2026-11-14) and Docker Desktop 4.60.1.

> Result of the first session (fill in after the supervisor's test): _pending_ — breakpoint hit: yes/no,
> step into Odoo core: yes/no, time spent: … min. Final decision in ADR-014.

## 1. How it works (read once)

- The Docker Compose interpreter is a paid (Pro) feature of PyCharm. The free tier cannot do it (section 9).
- A run/debug configuration on that interpreter **replaces the `odoo` service container**: PyCharm runs
  `docker compose up` with `compose.yaml` plus a generated override
  (`%LOCALAPPDATA%\JetBrains\PyCharm2026.2\tmp\docker_compose\docker-compose.override.<n>.yml`, seen 2026-11-07) that
  sets our command (with PyCharm's debugger, `pydevd`, around it when you click Debug), PyCharm's environment
  variables, the working directory `/opt/project` and two extra mounts. The image's entrypoint still runs, so
  `odoo.conf` is written from `.env` as usual; port 8069 is published as usual. When the run stops, the `odoo`
  container stays stopped: `uv run shop up` recreates the normal one.
- PyCharm's own helper containers (interpreter introspection, file sync) use `docker compose run` with the entrypoint
  cleared. The debug parameters do not depend on the entrypoint anyway: checked with
  `docker compose run --service-ports --entrypoint "" odoo python3 -m odoo …` (base image `odoo.conf`, connection from
  the `PG*` variables of `compose.yaml`, `shop` served on 8069, database manager disabled).
- PyCharm mounts the repository read-write at `/opt/project` and its helpers volume (`pycharm_helpers`, built once from
  the `busybox` image) at `/opt/.pycharm_helpers`, and maps `<repo>` ↔ `/opt/project` by itself. The Odoo
  configurations therefore load our module from `/opt/project/addons` (`--addons-path`), so breakpoints in `addons/`
  match; the normal server keeps loading it from `/mnt/extra-addons`.
- Odoo runs threaded (`workers = 0`): each HTTP request is a thread; the module's Elasticsearch calls run on a
  second thread from a 4-thread pool (`services/es_client.py`, `EsClient._within`). The debugger follows both.

## 2. Before you start

- Docker Desktop running; `uv run shop up` done and `uv run shop doctor` green (known warnings only).
- The PyCharm Pro trial or license active (human-only step).
- `.odoo-src/` present (`uv run shop odoo-src`, Task 1.4a).
- First use only: PyCharm builds its helpers image `pycharm_helpers:PY-<build>` (163 MB for PY-262.10968.92) and a
  helpers volume, no admin rights. It also reads the interpreter's packages once (about 13 min on 2026-11-07).

## 3. One-time setup

1. **Open** the repository root (`odoo-search-lost-demand`) in PyCharm. The project interpreter for `tools/` is the uv
   environment `.venv` (PyCharm detects it; otherwise *Add Interpreter > Local > Existing*, `.venv\Scripts\python.exe`).
2. **Docker connection**: *Settings > Build, Execution, Deployment > Docker* > `+` > *Docker for Windows*. It must say
   "Connection successful". Nothing else to change (no TCP daemon port).
3. **Interpreter**: *Settings > Python > Interpreter* (or the interpreter widget) > *Add Interpreter > On Docker Compose*:
   - Server: the Docker connection of step 2. Configuration files: `./compose.yaml` only. Service: `odoo`.
   - Leave the project name empty: `compose.yaml` sets `name: odoo-search-lost-demand`, so PyCharm uses the same
     volumes, network and database as `uv run shop up`.
   - Next: PyCharm introspects the image. Interpreter path: `/usr/bin/python3` (Python 3.12.3).
   - Rename it exactly **`Odoo 19 (Docker Compose: odoo)`**: the run configurations in `.run/` refer to that name.
   - Project interpreter: either one works, because every run configuration names its own interpreter. With this
     one the editor resolves `import odoo` from the image; with `.venv` it resolves `tools/` packages (pytest, ruff).
   - PyCharm loads `.run/` when the project opens. If that happened before this interpreter existed, it removes the
     interpreter from the two Odoo configurations (they then show the project interpreter): pick
     `Odoo 19 (Docker Compose: odoo)` again in each one.
4. **Path mappings** (in the interpreter's settings, or the run configuration's *Path mappings* field if shown):
   | Local path | Remote path |
   |---|---|
   | `<repo>\.odoo-src\odoo` | `/usr/lib/python3/dist-packages/odoo` |
   Optional: it makes "step into" open the local copy of the exact Odoo code in the image (without it PyCharm opens its
   own downloaded copy under `remote_sources`). No mapping is needed for our module: the Odoo configurations load it
   from `/opt/project/addons` (`--addons-path`), inside the repository mount PyCharm maps by itself
   (`<repo>` ↔ `/opt/project`). The first session (2026-11-07) showed why: with the module loaded from
   `/mnt/extra-addons`, PyCharm sent the breakpoint as `/opt/project/addons/…` and never stopped.
5. **Odoo source for navigation**: *Settings > Project Structure*: mark `.odoo-src` as *Sources* (so `import odoo` resolves
   in the editor, `06_ENVIRONMENT_SETUP.md` §5). Never edit files there.
6. **Debugger settings** (*Settings > Build, Execution, Deployment > Python Debugger*): *Gevent compatible* off
   (Odoo runs threaded, not evented).

## 4. Run configurations (committed in `.run/`)

PyCharm loads them automatically (*Run > Edit Configurations*). If it rewrites a file when you open or save it, keep its
version and tell the agent: the hand-written files are a starting point.

| Name | What | Notes |
|---|---|---|
| `Odoo (debug)` | `python -m odoo --addons-path=/opt/project/addons --limit-time-real=0 --max-cron-threads=0 --db-filter=^shop$ --no-database-list` on the Docker Compose interpreter | The development server on http://127.0.0.1:8069 |
| `Odoo module tests` | `python -m odoo -d shop_test … -i website_sale_lost_demand --test-tags=/website_sale_lost_demand,-es --stop-after-init` | Same as `uv run shop test module` without the `es` tests and without the drop of `shop_test` |
| `tools tests` | pytest on `tools/tests` with `.venv` | Same as `uv run shop test tools` |

Why these parameters (Odoo 19.0 source in `.odoo-src/odoo/`):

- `--addons-path=/opt/project/addons`: our module from the repository mount PyCharm adds and maps (`<repo>` ↔
  `/opt/project`, see `IDE_PROJECT_ROOTS` in the container), not from `/mnt/extra-addons`, so breakpoints in
  `addons/` match without a manual path mapping. Same files, read-write instead of read-only. Odoo's own addons are
  always added by Odoo itself.
- `--limit-time-real=0`: in threaded mode Odoo checks every request thread against `limit_time_real` (120 s by default) and
  **reloads the whole server** when one runs longer (`service/server.py`, `ThreadedServer.process_limit` and `run`).
  A request paused at a breakpoint for two minutes would restart Odoo under you. `0` turns the check off.
- `--max-cron-threads=0`: no scheduled jobs in the debug process, so only your request hits breakpoints.
- `--db-filter=^shop$ --no-database-list`: the same as `odoo.conf`, repeated so the debug server stays locked to the shop
  database even if the configuration file were not written.
- Module mode `odoo` (`python -m odoo`, `odoo/__main__.py` → `odoo/cli/command.py::main` → `odoo/cli/server.py::main`):
  the same entry point as `/usr/bin/odoo`, without a remote script path.
- *Add content roots / source roots to PYTHONPATH* are **off**: if PyCharm mounts the repository in the container
  (`/opt/project`), `/opt/project/.odoo-src/odoo` on `PYTHONPATH` would shadow the image's Odoo package.
- *Debug just my code* is **off** in both Odoo configurations: with it on, the debugger skips Odoo's own code
  (`dist-packages`), and "step into an Odoo core method" (the manual test) does not work.

### Check the command once

*Run > Edit Configurations > Odoo (debug)* > *Docker Compose* section > *Command preview*: a `docker compose … up …`
command on `compose.yaml` and PyCharm's override file. Keep the default *Command and options*. Take the screenshot of
section 7.

## 5. The debug session (manual test of Task 1.4b)

1. Nothing to stop: the debug run replaces the normal `odoo` container (section 1).
2. Open `addons/website_sale_lost_demand/models/res_config_settings.py` and set a breakpoint on the first line of
   `_compute_lost_demand_es_status` (`status, message = self._lost_demand_es_status()`).
3. Select `Odoo (debug)` and click **Debug** (bug icon). Wait for `HTTP service (werkzeug) running on …:8069` in the console.
4. Log in at http://127.0.0.1:8069/odoo as admin and open *Settings*, then the *Website* section. PyCharm stops on the
   breakpoint; the page waits.
5. Look at the *Frames* list: the request thread goes through `odoo/http.py` (`Application.__call__`, `Request._serve_db`)
   and the ORM (`odoo/orm/fields.py`, `Field.__get__` → `Field.compute_value`; `odoo/orm/models.py`,
   `BaseModel._compute_field_value`) down to our method. Click a core frame: it opens in `.odoo-src/odoo/`.
6. **Step into an Odoo core method**: *Step Into* (F7) once to enter `_lost_demand_es_status`, *Step Over* (F8) to the
   line `return status, self.env._("Reachable")`, then *Smart Step Into* (Shift+F7) and pick `_`: PyCharm opens
   `.odoo-src/odoo/orm/environments.py`, `Environment._`. If it steps over core code, use *Force Step Into*
   (Alt+Shift+F7): the image's Odoo lives under `dist-packages`, which PyCharm may treat as a library.
7. Resume (F9). The settings page finishes loading.
8. Stop the debug run (red square), then start the normal container again:
   ```bash
   uv run shop up
   ```

### Threads and deadlines: what to expect

- The Elasticsearch status is cached for 10 s (`health_cache_seconds`). Within 10 s of the last page load,
  `cluster_status()` returns the cached value and no Elasticsearch call happens.
- The three status requests run on a pool thread (`lost-demand-es-…`), and the page waits at most 2 s for them
  (`status_timeout`, `EsClient._within`). If you pause inside `fetch` (a breakpoint in `services/es_client.py`) or step
  into `self._within(...)`, the request thread's 2-s deadline passes: the page shows
  "Unreachable: no answer within 2 s". That is the timeout working, not a bug. The status call does not count toward the
  circuit breaker (only `guarded()` shopper calls do).
- To debug the Elasticsearch code itself, set the breakpoint inside `fetch`; PyCharm switches to the pool thread there.

## 6. Debugging a module test

1. Set a breakpoint in `addons/website_sale_lost_demand/tests/test_settings_page.py`.
2. Debug `Odoo module tests`. It creates `shop_test` if missing, installs the module, runs the tests and exits (2–3 min).
   It runs in its own container; the development server may keep running.
3. Afterwards run `uv run shop test module`: it drops the leftover `shop_test` first, then runs the suite normally.

## 7. Screenshots to capture (supervisor)

Save as PNG (< 200 KB each, crop to the dialog) in `docs/setup/img/pycharm/` and commit them on this branch:

| File | Shows |
|---|---|
| `01-docker-connection.png` | *Settings > Docker*: "Connection successful" |
| `02-compose-interpreter.png` | The *On Docker Compose* dialog: `compose.yaml`, service `odoo` |
| `03-interpreter-ready.png` | The interpreter `Odoo 19 (Docker Compose: odoo)`, Python 3.12.3, package list |
| `04-path-mappings.png` | Both path mappings |
| `05-run-config.png` | `Odoo (debug)` with the Docker Compose command preview |
| `06-breakpoint-hit.png` | Stopped in `_compute_lost_demand_es_status`, *Frames* and *Variables* visible |
| `07-step-into-core.png` | Stopped in `.odoo-src/odoo/orm/environments.py`, `Environment._` |
| `08-test-config.png` | `Odoo module tests` stopped in a test, or its passing summary |

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `port is already allocated` / bind error on 8069 | Another Odoo on 8069 (a native service, or a container of another project): stop it |
| Console shows Odoo starting but no `pydevd` / "Connected to pydev debugger" line | You clicked Run (green triangle), not Debug (bug icon) |
| Shop down after a debug session | Expected: the run replaced the `odoo` container. `uv run shop up` |
| Page loads, breakpoint never hit (the Odoo log shows the request) | Module not loaded from `/opt/project/addons`: `--addons-path=/opt/project/addons` missing from the parameters. Check *Run > Mute Breakpoints* is off |
| Step into opens a read-only file under PyCharm's `remote_sources` | Path mapping `.odoo-src\odoo` ↔ `/usr/lib/python3/dist-packages/odoo` missing |
| Odoo restarts while paused ("virtual real time limit") | `--limit-time-real=0` missing from the parameters |
| Odoo configuration shows `<no interpreter>` or the project interpreter, or `No module named odoo` on the host | Interpreter removed when `.run/` loaded (section 3): pick `Odoo 19 (Docker Compose: odoo)` again |
| Step into never enters `.odoo-src/` | *Debug just my code* switched on again: turn it off in the configuration |
| `ModuleNotFoundError` or a second `odoo` package | *Add content/source roots to PYTHONPATH* switched on again: turn both off |
| Odoo answers but the page lists no database / login fails | Wrong database filter: check `.env` `ODOO_DB_NAME` (= `shop`) and the `--db-filter` parameter |
| Python code change not picked up | Expected on the Windows drive (ADR-014): restart the debug run |

After any session, `docker compose ps` must show `odoo` running again (`uv run shop up`); leftover
`odoo-search-lost-demand-odoo-run-…` containers can be listed with `docker ps -a` and are removed by PyCharm on stop.

## 9. Fallback and after the trial

**Fallback (only if breakpoints do not work within the 2-hour time box, or without a Pro license):** run Odoo from source
on the host with the free PyCharm tier (plain local interpreter), PostgreSQL and Elasticsearch still in Docker:

- a second uv environment with Python 3.12 and Odoo 19.0's `requirements.txt` (from github.com/odoo/odoo, branch 19.0;
  about 300 MB, no admin rights), Odoo itself from `.odoo-src/`;
- `compose.yaml`: publish PostgreSQL on `127.0.0.1:5432` (a reviewed change, not done yet);
- a host `odoo.conf` generated from `.env` (no secrets in the repository).

Each of these needs the supervisor's "go" (download, compose change). The decision and its reason go in ADR-014.

**After 2026-11-14:** the Docker Compose interpreter needs a paid license. Decision (supervisor, 2026-11-13): the free
JetBrains educational license for students. Apply at <https://www.jetbrains.com/academy/student-pack/> with a
university email address (fastest), an ISIC/ITIC card or a GitHub Student Developer Pack account; no payment. It lasts
one year and is renewed from the JetBrains Account while you are a student; non-commercial use only. Then activate it in
PyCharm (*Help > Register*, sign in with the JetBrains Account). Nothing in this guide changes. If the application is
refused, use the fallback above.
