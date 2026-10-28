# ADR-018 — Pinned versions

- Status: Accepted (supervisor approval of docs/setup/VERSIONS.md, 2026-10-28)
- Date: 2026-10-28
- Source: `docs/ai/05_ROADMAP.md` Task 0.2

## Context
Reproducibility needs exact versions; `docs/ai/06_ENVIRONMENT_SETUP.md` §3 sets the selection rules.
Versions were verified from official sources on 2026-10-28.

## Decision
- Odoo `odoo:19.0-20261015` (Python 3.12 inside, from `ubuntu:noble`)
- PostgreSQL `postgres:16.15-trixie`
- Elasticsearch and Kibana `9.5.5`; Python client `elasticsearch==9.5.1`
- Host Python 3.12 via uv; uv ≥ 0.13.6

Full table with sources: `docs/setup/VERSIONS.md`; machine-readable copy: `docs/setup/versions.toml`.

## Consequences
Upgrades are patch-only, at milestone boundaries, with a line added here and a full regression check.

## Revisit when
Each milestone boundary (patch updates only).
