# ADR-004 — Elasticsearch and Kibana 9.x, Basic license, security on, localhost only

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
The project must cost nothing, protect Elasticsearch with a password and run on one laptop.

## Decision
Elasticsearch and Kibana pinned to the same 9.x version (9.5.5, ADR-018). Free Basic license, asserted by `es-setup`
and the doctor; never a trial. Security on (passwords); plain HTTP inside the Docker network; published ports bound
to `127.0.0.1`.

## Consequences
Paid features are excluded (feature-license table in `docs/setup/VERSIONS.md`). No TLS setup to maintain on a laptop.

## Revisit when
Never during the project.
