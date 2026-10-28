# ADR-016 — Semantic search with a small embedding service and fusion in the module

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
FR13 (Could) needs hybrid search; the RRF and linear retrievers are Enterprise-only
(Elastic subscriptions PDF dated 2026-08-04, see `docs/setup/VERSIONS.md` §6).

## Decision
A small CPU embedding service plus `dense_vector`/kNN (Basic). Fusion of keyword and vector results is done in the module.

## Consequences
Stays on the free license; the fusion code is ours to test.

## Revisit when
FR13 is cut.
