# ADR-007 — Product index sync through an outbox, with versioned rebuilds

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
FR1: a product change must show in search within 1 minute, with no lost updates and no downtime on rebuild.

## Decision
Model triggers write template IDs to a transactional outbox (`lost_demand.index.queue`); a cron trigger requests an
immediate flush that sends one bulk request. Full rebuilds go into `shop-products-v<N+1>`, then an atomic alias swap.

## Consequences
No update is lost while Elasticsearch is down; rebuilds do not interrupt search.

## Revisit when
The Task 3.2 measurement shows trigger latency is too high.
