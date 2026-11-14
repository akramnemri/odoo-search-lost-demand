# ADR-009 — One canonical event schema for every source

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Shop traffic, virtual shoppers and the REES46 replay must feed the same dashboards and analyses.

## Decision
One data stream (`shop-events`) with a strict mapping (`docs/ai/04_DATA_SEARCH_EVALUATION.md` §7).
The `source` and `traffic` fields separate the origins.

## Consequences
Unknown fields fail loudly; filters on `source` and `traffic` keep analyses clean.

## Revisit when
—
