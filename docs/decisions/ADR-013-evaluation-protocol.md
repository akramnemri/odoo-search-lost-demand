# ADR-013 — Evaluation: separate dev and test query sets, NDCG@10, hidden catalog

- Status: Proposed (final after protocol approval in Task 2.2)
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Specification section 11; results must be scientifically valid and reproducible.

## Decision (proposed)
Dev set for tuning, test set for reporting (used once, after the freeze); NDCG@10 with ESCI gains; hidden-catalog
protocol for lost-demand detection; every run recorded with metadata (`run.json`).

## Consequences
No tuning on the test set; every reported number traces back to a recorded run.

## Revisit when
Protocol approval (Task 2.2).
