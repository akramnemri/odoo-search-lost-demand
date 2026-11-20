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

## Implementation notes (Task 3.2, 2026-11-20)
Refinements within this decision, found in the design review and the Odoo 19 source:
- outbox rows hold the template ID as a plain integer (the row outlives a deleted product) and are written by a
  pre-commit callback, one per product per transaction; duplicates across transactions are merged by the job;
- the stock hook is `stock.quant._update_available_quantity`, which every inventory adjustment, delivery,
  receipt and reservation goes through; the index stores the shop's free quantity (definition version 2);
- bulk writes use `require_alias=true`, so a missing alias can never be replaced by an auto-created index;
- the full rebuild and the sync never overlap (PostgreSQL advisory lock; the rebuild reads after taking it);
- measured latency: `results/summary/freshness-products.md` (`uv run shop probe products`).
