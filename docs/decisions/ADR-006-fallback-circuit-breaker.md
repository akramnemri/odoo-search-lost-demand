# ADR-006 — Fallback to Odoo search with timeouts and a circuit breaker

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Reliability requirement: if Elasticsearch is down, the shop still works.

## Decision
Short timeouts on every shopper-facing Elasticsearch call, plus a per-process circuit breaker. On failure the shop
uses Odoo's native search (`super()`), logs one warning per breaker opening and tags the event `engine=odoo_fallback`.

## Consequences
Shoppers never see an error page because of Elasticsearch. The fallback rate is visible in dashboards.

## Revisit when
—
