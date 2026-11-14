# ADR-010 — Lost-demand job in Odoo; purchase documents only as drafts

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
FR8/FR9: detect lost demand and act on it, while the buyer stays in control.

## Decision
An Odoo scheduled action reads Elasticsearch aggregations and stores results as Odoo records (runs, signals,
proposals). Purchase documents are created only as drafts and need buyer approval.

## Consequences
Auditable runs; nothing is ordered automatically.

## Revisit when
—
