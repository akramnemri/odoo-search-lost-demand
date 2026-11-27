# ADR-020 — The tuned search configuration (`TUNED_V1`) and the stock rule

- Status: Proposed (2026-11-27, agent, Task 3.5) — to be accepted by the supervisor after reviewing the
  experiment log (roadmap Task 3.5: "the supervisor reviews the experiment log and approves the configuration")
- Date: 2026-11-27
- Source: `docs/ai/05_ROADMAP.md` Task 3.5; `docs/ai/04_DATA_SEARCH_EVALUATION.md` §6; protocol §6

## Context
The shop's `es_tuned` query of Task 3.3 (`TUNED_V0`) was a reasonable starting point, not a measured one: on the
dev queries it was not significantly better than Elasticsearch out of the box (`results/summary/ndcg-dev-both.md`).
Task 3.5 measured variants of it, one change at a time, on the dev queries only, with a decision rule written down
before any run (`docs/evaluation/experiments.md`) and a budget of 15 experiments. FR3 asks for in-stock products
first; the protocol (04 §6) makes rule (a) "tiered" the default unless the supervisor accepts rule (b) "boosted".

## Decision
**`TUNED_V1` = `TUNED_V0` + `tie_breaker` 0.3 + an exact, case-insensitive internal-reference match**
(`addons/website_sale_lost_demand/services/query_builder.py`), used by `es_tuned` and `es_tuned_stock`.

- The tie-breaker (best-matching field plus 30 % of the other fields' scores) is the only stage-1 change that
  passed the relevance rule; the reference match passed its functional goal at no cost on the dev queries (Odoo's
  own search finds a product by its reference; the earlier Elasticsearch query did not). Their combination
  (`c01-combined`) was measured as one variant and passed the same rule.
- **Stock rule (a) "tiered" stays** for `es_tuned_stock`, as the rule required: rule (b) with in-stock scores ×1.2
  gained clearly but put slightly fewer than the pre-registered 95 % in-stock products in the top 10; ×2.0 gained
  too little. The supervisor may still choose (b) ×1.2 (see Consequences).
- Every number: `results/summary/tuning-dev.md` (generated from the run folders `results/tune-*`).

Dropped, with the reason the rule computed (same table): typo tolerance off or `cross_fields` (large loss on the
typo set), first letter fuzzy (loss on dev), two exact first letters and "most words must match" (loss on the typo
set), `most_fields` (loss on dev), the name phrase bonus, a lighter description and the unstemmed name (no gain).

## Consequences
- The shop's search changes for every shopper with module code only (no index change, no rebuild).
- The weak tail of Task 3.3 is **not** solved: the only variant that cut it ("most words must match") cost too
  much on typo queries. It stays an open point for later work (for example a typo-tolerant word requirement),
  together with sold-out exact matches sitting after the in-stock ones under rule (a).
- Rule (a) has a visible relevance cost because the ESCI labels ignore stock (a product trade-off, reported).
  Rule (b) ×1.2 roughly halves that cost on the dev queries but no longer guarantees in-stock first; choosing it
  is a product decision for the supervisor (FR3 wording), recorded here if taken.
- Dev numbers of the chosen configuration are optimistic (it was chosen on them); the reported comparison is the
  test-set run after the freeze (Task 8.2). Synonyms (Task 3.6) come on top of `TUNED_V1`.

## Revisit when
Synonyms are added (Task 3.6), the catalog changes substantially, or the freeze (Task 8.1) re-examines the
configuration.
