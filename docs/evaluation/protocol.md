# Evaluation protocol v1

Status: **DRAFT, not approved** (Task 2.2). Approval by the supervisor (and, if the supervisor asks for it, the academic
supervisor) is recorded at the end. Until then no evaluation number is produced. After approval this document changes
only through a new version with an ADR line (ADR-013).

Sources: the specification's §11 (`docs/sources/project-specification.pdf`, 25 October 2026),
`docs/ai/04_DATA_SEARCH_EVALUATION.md` §3, §8, §9, §11, §12, ADR-012, ADR-013.

## 1. What is measured, and the targets

| # | What | How (summary) | Target (specification §11) |
|---|---|---|---|
| E1 | Search quality | NDCG@10 on English ESCI test queries: Odoo's default search, plain Elasticsearch, tuned Elasticsearch | Tuned search scores highest of the three |
| E2 | Lost-demand detection | Hide 20 % of the catalog, let virtual shoppers keep searching, check whether the report finds the hidden products | ≥ 80 % of hidden products flagged |
| E3 | Search speed | Locust, 50 virtual shoppers | Page < 1 s for 95 % of requests; Elasticsearch query < 100 ms (p95) |
| E4 | Freshness | Delay from event to Kibana; product change to search | Event < 10 s; product change < 60 s |
| E5 | Volume | REES46 replay | ≥ 10 million events; dashboards load in < 5 s |
| E6 | Usefulness | Demo to a real shop owner, interview before and after | Their feedback included in the report |

A target that is missed is reported as missed, with the reason. Negative results are reported.

## 2. Data

- **ESCI** (Shopping Queries Dataset), `amazon-science/esci-data` at commit `7916cdf6ab75a462e77f20ab40428a10923998d5`,
  Apache-2.0. File sizes and SHA-256 pinned in `docs/setup/versions.toml`, recorded in `data/manifest.toml` by
  `uv run shop data fetch esci` (Task 2.1).
- Only `product_locale = us` and `small_version = 1` (the queries with the most complete judgments).
- Counts available for sampling, from `results/summary/esci-profile.md`: **pending the ESCI profile** (download in
  progress on 2026-11-14) — number of `us`/`small_version = 1` queries in the *train* and *test* splits, judgments per
  query, distinct judged products.
- Synthetic enrichment (category, price, stock, vendor) is seeded and labelled synthetic wherever it appears
  (`04` §4); it never changes the relevance labels.

## 3. Query sets and catalog

All sampling uses one seed, **`20261025`** (the specification's date), stored in the slice configuration and in every
`run.json`. Same inputs + seed → byte-identical outputs (hash test, Task 2.3).

| Set | Rule | Used for |
|---|---|---|
| **dev** | 300 queries drawn uniformly at random from the ESCI *train* split (`us`, `small_version = 1`) | All relevance tuning (Task 3.5) and quick checks |
| **test** | 700 queries drawn uniformly at random from the ESCI *test* split (`us`, `small_version = 1`) | Reported NDCG, **run once**, after the configuration freeze (Task 8.1) |
| **catalog** | Union of all products judged (any label) for the dev + test queries | The shop's products (expected 20–23k; exact count recorded by Task 2.3) |
| **qrels** | (query id, product id, label, gain) for dev + test | NDCG |
| **traffic pool** | dev + test queries | Virtual shoppers (Locust) |

- dev ∩ test = ∅ (they come from different ESCI splits; checked by a test).
- Every judged product of every selected query is in the catalog, so NDCG is not penalised by missing products.
- **Test queries in the traffic pool** do not leak labels into NDCG **as long as no click- or popularity-based
  ranking feature is used**. If one is ever added, NDCG runs must disable it or exclude test-query traffic, with an ADR.
- The test set is never used for tuning. Any extra run on the test set is recorded and explained in the results.

## 4. Hidden set and out-of-stock set (detection)

- **Hidden set:** 20 % of the catalog size, drawn with the seed, **stratified by category**, and only among products
  that are the **Exact (E)** match of at least one traffic-pool query. Otherwise no shopper would ever look for them and
  detection would be impossible by construction.
- **Out-of-stock set:** 10 % of the remaining products start with zero stock (default), for FR3 and the out-of-stock
  signal.
- Both sets are written by the slice builder (Task 2.3) and recorded with their hashes.

## 5. Lost-demand signals and the detection rule

Signals (defaults from `04` §8.2; thresholds are module settings and are frozen with the configuration):

| Signal | Definition |
|---|---|
| Zero-result query | ≥ 3 searches with 0 results for the same normalized query, from ≥ 2 distinct sessions, in the window |
| **Unsatisfied query (proposed: add)** | Searches with results but no click or add-to-cart carrying the same `search.id` within 120 s: count ≥ 5, unsatisfied rate ≥ 0.6, ≥ 2 distinct sessions |
| Out-of-stock demand | Per product: `1·views + 2·clicks + 5·add_to_cart ≥ 10`, ≥ 2 distinct sessions, and current stock ≤ 0 |

**Why the unsatisfied signal is proposed.** In a 20k-product catalog, a search for a hidden product almost always still
returns *other* products (the same words appear in many titles), so it rarely produces zero results. With the
zero-result signal alone, recall on the hidden set would be close to 0 by construction, and the 80 % target could not be
met whatever the quality of the system. A shopper who looks for a product that is gone typically gets results but does
not click or buy: that is the signal to detect. The shopper model (`04` §9) clicks with a probability driven by the
label of what is shown, so a search whose Exact target is hidden produces mostly unsatisfied searches.

**Detection rule.** A hidden product *p* is **detected** if at least one query *q* with label(*q*, *p*) = E appears in
the lost-demand report (zero-result list, or unsatisfied list if approved). Only hidden products searched at least 3
times during the run count (the denominator).

- **Recall** = detected hidden products / hidden products searched ≥ 3 times (target ≥ 0.8).
- **Precision** = reported queries that target a hidden or out-of-stock product (label E) / all reported queries.
- Secondary: recall of the out-of-stock signal on the out-of-stock set.
- Misses are listed with their reason (not searched enough, query normalised differently, below a threshold).

**Campaign** (`04` §11.2): restore the baseline snapshot; `uv run shop eval hide --apply`; Locust `detection` profile
(default 50 users, 45 min, traffic pool, Zipf popularity, seeded); run the lost-demand job over a window covering the
run; export the report; compute recall and precision; `uv run shop eval hide --revert`.

## 6. Search quality (E1)

- **Gains:** E = 1.0, S = 0.1, C = 0.01, I = 0 (the ESCI benchmark convention; checked against the ESCI repository in
  Task 2.3 and cited).
- **NDCG@10:** `DCG@10 = Σ_{i=1..10} gain_i / log2(i + 1)`; `IDCG@10` from the ideal ordering of the query's judged
  products; NDCG@10 = DCG@10 / IDCG@10 (queries with IDCG = 0 are excluded and counted). Unjudged results count as gain 0.
  Also reported: **judged@10**, the share of top-10 results that are judged.
- **Engines:** `odoo` (Odoo's native shop search), `es_plain` (Elasticsearch, default analysis, no tuning), `es_tuned`
  (the frozen configuration). Extra rows if built: `es_tuned_stock`, `hybrid` (FR13).
- **Modes:** `http` — through the real `/shop` page (what shoppers see; **used for every reported number**);
  `direct` — Elasticsearch only (fast tuning loop on the dev set). A consistency check compares both modes on the dev set.
- **Statistics:** mean NDCG@10 per engine with a 95 % bootstrap confidence interval (10,000 resamples, seeded);
  paired randomization test between engines on per-query scores (10,000 permutations, seeded); report the differences
  and p-values. No claim of "higher" without the interval and the test.

## 7. Speed, freshness, volume, usefulness (E3–E6)

- **Speed:** baseline restored; Odoo workers set for load tests (`01` §5.3); 2-minute warm-up; Locust `speed` profile:
  50 users, spawn rate 5/s, 10 minutes, search-heavy mix; three repetitions. Search-page p50/p95/p99 and failure rate
  (Locust); `took_ms` p95 from the run's search events. Machine and RAM profile recorded.
- **Freshness:** events — 200 probe searches with unique tokens (`traffic = probe`), poll Elasticsearch every 200 ms,
  delay = found time − `@timestamp`; report p50/p95/max, and "visible in Kibana" = that delay + the dashboard refresh
  interval (5 s). Products — 30 stock or price changes through the Odoo API; poll shop search until visible; p50/p95/max.
- **Volume:** REES46 replay until `source: rees46` holds ≥ 10 M events; ingest throughput, store size, heap; load the
  Volume and Demand-by-category dashboards 5 times over 30 days of data; time until all panels render (automated if
  feasible, otherwise a stopwatch on a screen recording; the method is stated).
- **Usefulness:** interviews before (Task 1.6) and after a demo (Task 11.2), guide and consent in `docs/pilot/`,
  anonymised notes; summary of what the owner would use, change or not trust.

## 8. Runs and reproducibility

Every campaign: restore the baseline snapshot; write `results/<run-id>/run.json` (kind, git SHA and dirty flag,
command, frozen configuration or its hash, seed, versions, data checksums, machine, start and end); keep raw outputs in
`results/<run-id>/` (git-ignored); write the summary to `results/summary/` (committed); report in
`docs/evaluation/results.md`. Before any number goes into the report: the run folder exists, the command re-runs from a
clean checkout of that SHA, the data checksums match `data/manifest.toml`, and the table or figure is generated by a
committed script. Numbers are never edited by hand.

**Freeze rule (Task 8.1):** the configuration (analyzers, synonyms, boosts, thresholds, shopper model) is frozen and
tagged before the test-set run and the detection campaign. A change after the freeze means a new freeze and a new run,
both reported.

## 9. Threats to validity

- ESCI labels reflect Amazon's catalog and judges; our catalog is a 20k slice of it.
- Odoo's native ordering is not relevance-based by design, so the `odoo` row is a baseline, not a competitor.
- Virtual shoppers are a simulation (Zipf popularity, typo and click models): detection recall depends on that model.
- Prices, stock, categories and vendors are synthetic.
- One laptop: speed numbers depend on the machine and the RAM profile, which are recorded.
- REES46 is replayed from 2019 data at high speed; it tests volume, not shopper behaviour.

## 10. Decisions to approve

| # | Decision | Recommendation |
|---|---|---|
| D1 | Add the **unsatisfied-query signal** to the detection rule | Yes (§5: zero-result alone makes the 80 % target unreachable by construction) |
| D2 | Query set sizes | dev 300 (train split), test 700 (test split) |
| D3 | Seed | `20261025` |
| D4 | Catalog = all judged products of dev + test | Yes |
| D5 | Hidden set: 20 %, stratified by category, E-targets only, searched ≥ 3 times to count | Yes |
| D6 | Test queries in the traffic pool, with no click-based ranking feature | Yes |
| D7 | Reported numbers from `http` mode only | Yes |
| D8 | Who approves | The supervisor; the academic supervisor too if required |

## Approval

| Date | Approved by | Decisions | Notes |
|---|---|---|---|
| — | — | — | pending |
