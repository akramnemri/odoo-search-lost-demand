# ADR-013 — Evaluation: separate dev and test query sets, NDCG@10, hidden catalog

- Status: Accepted (2026-11-14, supervisor; `docs/evaluation/protocol.md` v1, decisions D1–D11; v1.1, D12)
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Specification section 11; results must be scientifically valid and reproducible.

## Decision
Dev set for tuning, test set for reporting (used once, after the freeze); NDCG@10 with ESCI gains; hidden-catalog
protocol for lost-demand detection; every run recorded with metadata (`run.json`).

Detailed in `docs/evaluation/protocol.md` (approved 2026-11-14), which adds: the unsatisfied-query signal; two disjoint
hidden sets (thresholds chosen on dev, reported on test); a negative-control campaign, seed and noisy-shopper
robustness runs and a time-to-detection curve; a typo test set, breakdowns (including vocabulary mismatch for
synonyms), condensed NDCG, effect sizes and Holm correction; a resilience run (E7); structured interview ratings;
pre-registration with the tag `protocol-v1`.

**v1.1 (2026-11-14, supervisor, decision D12, option B2):** hidden sets are built from hidden *queries*: every Exact
product of 20 % of the test queries (hidden-test) and of 20 % of the dev queries (hidden-dev) is hidden; the
out-of-stock set is drawn among products that shoppers search for. Reason: with product-by-product hiding, measured
recall would be about 3 % by construction (protocol "Changes"). Hidden-test covers 5.4 % of the catalog instead of the
specification's 20 %; reported as a threat to validity; the academic supervisor may need to approve it.

## Consequences
No tuning on the test set; every reported number traces back to a recorded run. Detection takes about 3 h 15 min of
campaigns in Milestone 8; the slice builder (Task 2.3) writes the extra sets (test-typo, hidden-dev, hidden-test).

## Revisit when
A deviation from the tagged protocol (`protocol-v1`): new protocol version + ADR line.
