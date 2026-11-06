# ADR-014 — Odoo runs in Docker; debugging through PyCharm's Docker Compose interpreter

- Status: Proposed (final after Task 1.4)
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
One environment for everything, and the specification requires PyCharm debugging.

## Decision (proposed)
Odoo runs in its container; PyCharm debugs it through a Docker Compose interpreter.
Fallback: Odoo from source on the host, with PostgreSQL and Elasticsearch still in Docker.

## Consequences
The repository stays on the Windows drive (supervisor decision, 2026-10-28). Bind-mounted addons from the Windows
file system do not deliver file-change events into the container, so Odoo is restarted after Python changes instead
of auto-reloading.

## Task 1.4b findings (2026-11-07, before the supervisor's PyCharm session)
- PyCharm 2026.2.3 starts a run on a Docker Compose interpreter with `docker compose run` and keeps the image's
  entrypoint, so `odoo.conf` is still generated from `.env`. Reproduced without PyCharm: `docker compose run
  --service-ports odoo python3 -m odoo …` served the shop database on 8069 with the normal configuration.
- The normal `odoo` container must be stopped during a debug session (port 8069).
- In threaded mode Odoo reloads the server when a request runs longer than `limit_time_real`
  (`odoo/service/server.py`, `ThreadedServer.process_limit`): the debug configuration sets `--limit-time-real=0`.
- Guide and configurations: `docs/setup/PYCHARM.md`, `.run/`. Final status after the supervisor's session
  (breakpoint hit and step into core within the 2-hour time box: Accepted; otherwise the host-run fallback).

## Revisit when
Task 1.4 result (2-hour time box), or if Windows bind mounts prove too slow.
