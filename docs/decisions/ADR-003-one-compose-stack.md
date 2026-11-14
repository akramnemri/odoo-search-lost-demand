# ADR-003 — One Docker Compose stack for development, demo and evaluation

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
The specification requires one command to start everything; debugging several environments costs time.

## Decision
One `compose.yaml` with PostgreSQL, Elasticsearch, a one-shot `es-setup`, Kibana and Odoo, used for development,
demo and evaluation. Memory settings come from `.env` per RAM profile (`lowmem`, `standard`).

## Consequences
One environment to debug. Profiles change resource settings, never service behavior.

## Revisit when
—
