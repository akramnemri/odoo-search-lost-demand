# ADR-014 — Odoo runs in Docker; debugging through PyCharm's Docker Compose interpreter

- Status: Accepted (2026-11-13, Task 1.4b manual test)
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
One environment for everything, and the specification requires PyCharm debugging.

## Decision
Odoo runs in its container; PyCharm debugs it through a Docker Compose interpreter.
Fallback: Odoo from source on the host, with PostgreSQL and Elasticsearch still in Docker.

## Consequences
The repository stays on the Windows drive (supervisor decision, 2026-10-28). Bind-mounted addons from the Windows
file system do not deliver file-change events into the container, so Odoo is restarted after Python changes instead
of auto-reloading.

## Task 1.4b findings (2026-11-07, before the supervisor's PyCharm session)
- PyCharm 2026.2.3 runs a configuration on a Docker Compose interpreter with `docker compose up`, `compose.yaml` and
  a generated override (command, PyCharm environment, working directory `/opt/project`, repository and helpers
  mounts): it replaces the `odoo` service container, keeps the image entrypoint (so `odoo.conf` is generated from
  `.env`) and publishes 8069 as usual (supervisor's first run, 2026-11-07). After the run the `odoo` container stays
  stopped; `uv run shop up` recreates the normal one. Its helper containers use `docker compose run` with the
  entrypoint cleared; the debug parameters also work that way (`--entrypoint ""` check: `shop` served on 8069, base
  image `odoo.conf`, connection from the `PG*` variables, database manager disabled).
- Breakpoints and stepping into Odoo core work in the container's Python 3.12 (scripted `pdb` check in a throwaway
  container: stop at `res_config_settings.py:60` under `fields.py::Field.__get__` → `compute_value` →
  `models.py::_compute_field_value`, step into `_lost_demand_es_status`, then into `orm/environments.py::Environment._`).
  This does not test PyCharm itself.
- PyCharm maps only the repository to `/opt/project`; a breakpoint in `addons/` never matched code loaded from
  `/mnt/extra-addons` (supervisor's first Debug, 2026-11-07). The Odoo configurations load the module from
  `/opt/project/addons` (`--addons-path`), so no manual path mapping is needed.
- PyCharm drops the interpreter from `.run/` configurations it loads before that interpreter exists, and turns on
  "debug just my code" (which skips Odoo core); both are set explicitly in `.run/`.
- In threaded mode Odoo reloads the server when a request runs longer than `limit_time_real`
  (`odoo/service/server.py`, `ThreadedServer.process_limit`): the debug configuration sets `--limit-time-real=0`.
- Guide and configurations: `docs/setup/PYCHARM.md`, `.run/`.

## Result (supervisor's PyCharm session, 2026-11-13)
- Debug of `Odoo (debug)` on the Docker Compose interpreter (PyCharm 2026.2.3, pydevd): the breakpoint in
  `res_config_settings.py::_compute_lost_demand_es_status` (line 60) stopped when Settings was reloaded; the *Frames*
  list showed `fields.py::Field.__get__` → `compute_value` → `models.py::_compute_field_value` → `determine`.
- Step Into from `_lost_demand_es_status` (line 52) opened `odoo/orm/environments.py::Environment._` (line 330,
  `source = 'Reachable'`). PyCharm opened its downloaded copy (`remote_sources`): the optional `.odoo-src` path mapping
  was not set.
- Screenshots: `docs/setup/img/pycharm/06-breakpoint-hit.png`, `07-step-into-core.png`.
- Time: spread over two sittings (2026-11-07 setup and first runs, 2026-11-13 test); the fixes above were found on the
  way. Breakpoints work, so the host-run fallback is not needed: the decision is accepted as proposed.

## License after the trial
The Docker Compose interpreter is a paid PyCharm feature; the trial ends 2026-11-14. Supervisor decision (2026-11-13): the
free JetBrains educational license for students (no payment, one year, renewable). If it is refused, the host-run
fallback becomes the decision.

## Revisit when
The student license is refused, or Windows bind mounts prove too slow.
