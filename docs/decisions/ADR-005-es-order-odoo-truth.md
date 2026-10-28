# ADR-005 — Elasticsearch decides the order, Odoo decides the truth

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
The product index can be stale; Odoo access rules (published, website, company, active, sale_ok) must always apply.

## Decision
Search returns ranked product template IDs from Elasticsearch; Odoo re-filters them with its own website domain and
keeps Elasticsearch's order. Price, stock and visibility shown to shoppers come from Odoo.

## Consequences
A stale index can affect ranking but never shows a product a shopper must not see.

## Revisit when
—
