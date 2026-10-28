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

## Revisit when
Task 1.4 result (2-hour time box), or if Windows bind mounts prove too slow.
