# ADR-021 — Synonyms managed in Odoo, with typed words ranked first

- Status: Proposed (2026-11-27, agent, Task 3.6; plan accepted by the supervisor: "go as the recommendations",
  after a deeper review that asked to mitigate over-broad rules)
- Date: 2026-11-27
- Source: `docs/ai/05_ROADMAP.md` Task 3.6; `docs/ai/01_ARCHITECTURE.md` §6.3; `04` §5–6; protocol §3

## Context
FR2 asks the search to understand synonyms, managed by the shop's administrator. The index's search analyzer
already reads an Elasticsearch synonyms set at search time (`synonym_graph`, `updateable`), so a rule can work
without reindexing (Task 3.1). Checked on the cluster before the design (throwaway resources, 2026-11-27):

- the analyzer applies synonyms **before** stemming, so a rule matches only the forms it lists ("sneakers,
  trainers" does not expand "trainer"); moving synonyms **after** stemming matches every form but merges unrelated
  words ("trainers" is stemmed to "train": a toy train would bring sneakers);
- Elasticsearch accepts nearly any text as a rule ("=>" was stored as a rule);
- with a rule "laptop, pc" and no countermeasure, a search for "pc" listed the laptops **first** (the rarer word
  scores higher): a broad rule can push the products the shopper asked for down the list.

## Decision
1. **Odoo is the source of truth** (`lost_demand.synonym`, Website › Configuration › Search synonyms, Settings
   group only). Saving a rule never calls Elasticsearch: a pre-commit callback triggers the product sync job of
   Task 3.2, which compares Odoo's active rules with the set and replaces the whole set when they differ (atomic;
   also repairs a lost set; never raises; retried every minute while Elasticsearch is down). Settings shows the
   rule count and the last sync state.
2. **No analyzer change, no rebuild**: Odoo sends each term with its simple singular or plural form; the form
   shows the exact line sent ("Sent to search").
3. **Rules are validated in Odoo** with clear messages (two terms at least for "same meaning", reserved
   characters, a letter or digit in every term, length, duplicates, at most 10 terms per list).
4. **Typed words rank first** (`TUNED_V2` = `TUNED_V1` + `literal_boost` 3, `services/query_builder.py`): the
   shopper's words are scored a second time with the index-time analyzer (no synonyms) and added to the score, so
   products that contain what the shopper typed come before products found only through a synonym. Without a
   synonym in the query both scores are proportional for every product, so the order is unchanged: page 1 was
   identical to `TUNED_V1` on all 300 dev and 300 dev-typo queries for both tuned engines (2026-11-27).
5. **A starting list of 20 rules** of general shop vocabulary (US/UK variants, everyday equivalents), written
   without looking at the dev or test queries (protocol §3), installed as editable data (`noupdate`); ambiguous
   words are one-way ("torch" → flashlight). Measured on dev before and after loading (pre-registered rule: no
   loss above 0.005 on dev or dev-typo): passed (`results/summary/ndcg-dev-direct.md`,
   `results/summary/ndcg-dev-typo-direct.md`, comparison sections).

## Consequences
- A rule works within seconds of saving (cron trigger, then Elasticsearch reloads the analyzers by itself).
- The literal bonus costs a second scoring clause: Elasticsearch's `took` p95 rose by about 10–25 ms on dev
  (88–93 ms, under the 100 ms target), measured 2026-11-27; it is part of the speed campaign (M5, M8).
- Synonym-expanded words get no typo tolerance (Elasticsearch does not apply fuzziness to them).
- The plural helper is simple English and can produce a harmless non-word (it is shown to the administrator).
- The starting list is frozen with the configuration (Task 8.1); its size (20) is reported.

## Revisit when
The catalogue or language changes, a rule's effect is disputed (a per-rule match preview would help), or the
speed campaign shows the bonus clause is too costly (it could be added only when a rule applies to the query).
