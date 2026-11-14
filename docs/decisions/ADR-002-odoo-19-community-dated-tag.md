# ADR-002 — Odoo 19 Community, pinned to a dated official image

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Website code changes between Odoo versions; tutorials and fixes exist for 19.0; results must be reproducible.

## Decision
Odoo 19.0 Community, official Docker image pinned to a dated tag (`19.0-YYYYMMDD`, see ADR-018).
No move to Odoo 20 during the project.

## Consequences
Reproducible builds; patch updates only by changing the dated tag at a milestone boundary.

## Revisit when
After the defense.
