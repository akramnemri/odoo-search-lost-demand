# ADR-008 — Event pipeline: outbox flushed within seconds

- Status: Proposed (final decision after the Task 4.2 spike)
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
FR6 and the freshness target (event in Kibana < 10 s), without ever blocking or breaking a shopper request.

## Decision (proposed)
Same outbox pattern as ADR-007 (`lost_demand.event.outbox`), flushed within seconds, writing with `op_type=create`
and a fixed `_id` (event UUID) so retries never duplicate.

## Consequences
Events survive Elasticsearch outages (bounded retention). Read-only routes may need a separate cursor (checked in the spike).

## Revisit when
After the Task 4.2 spike, which compares this with at least one alternative and records the final choice here.
