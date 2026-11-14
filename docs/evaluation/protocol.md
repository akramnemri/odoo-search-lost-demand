# Evaluation protocol v1

Status: **APPROVED by the supervisor on 2026-11-14** (decisions D1–D11, §11). The academic supervisor's approval is
the supervisor's call (D11) and is recorded below if obtained. The ESCI counts in §2 are data facts filled from the
profile (filled 2026-11-14), not decisions. The approved version is **pre-registered** with the git tag `protocol-v1` (§9). It changes only
through a new version with an ADR line (ADR-013).

Sources: the specification's §11 (`docs/sources/project-specification.pdf`, 25 October 2026),
`docs/ai/04_DATA_SEARCH_EVALUATION.md` §3, §4, §8, §9, §11, §12, ADR-006, ADR-012, ADR-013.

## 1. What is measured, and the targets

| # | What | How (summary) | Target (specification §11) |
|---|---|---|---|
| E1 | Search quality | NDCG@10 on English ESCI test queries: Odoo's default search, plain Elasticsearch, tuned Elasticsearch | Tuned search scores highest of the three |
| E2 | Lost-demand detection | Hide 20 % of the catalog, let virtual shoppers keep searching, check whether the report finds the hidden products | ≥ 80 % of hidden products flagged |
| E3 | Search speed | Locust, 50 virtual shoppers | Page < 1 s for 95 % of requests; Elasticsearch query < 100 ms (p95) |
| E4 | Freshness | Delay from event to Kibana; product change to search | Event < 10 s; product change < 60 s |
| E5 | Volume | REES46 replay | ≥ 10 million events; dashboards load in < 5 s |
| E6 | Usefulness | Demo to a real shop owner, interview before and after | Their feedback included in the report |
| E7 | Resilience (added, ADR-006) | Elasticsearch stopped for 2 minutes during a load run | No failed shopper request; search still answers |

A target that is missed is reported as missed, with the reason. Negative results are reported.

## 2. Data

- **ESCI** (Shopping Queries Dataset), `amazon-science/esci-data` at commit `7916cdf6ab75a462e77f20ab40428a10923998d5`,
  Apache-2.0. Sizes and SHA-256 pinned in `docs/setup/versions.toml`, recorded in `data/manifest.toml` by
  `uv run shop data fetch esci` (Task 2.1).
- Only `product_locale = us` and `small_version = 1` (the queries with the most complete judgments).
- Counts available for sampling, from `results/summary/esci-profile.md` (Task 2.1, 2026-11-14): `us`/`small_version = 1`
  has **20,888 train** and **8,956 test** queries, 601,354 judgments (min 8, median 16, max 188 per query; mean ≈ 20),
  482,105 distinct judged products. Label shares in that pool: E 43–44 %, S 35 %, C 4.5 %, I 17 %.
  So 300 dev + 700 test queries are 1.4 % and 7.8 % of their pools, and the catalog (§3) is about
  1,000 × 20 ≈ 20k judgments, a little fewer distinct products after overlaps.
- Synthetic enrichment (category, price, stock, vendor) is seeded and labelled synthetic wherever it appears (`04` §4);
  it never changes the relevance labels.

## 3. Seeds, query sets and catalog

**Seeds.** One base seed, **`20261025`**, stored in the slice configuration and in every `run.json`. Each random choice
uses its own stream derived from the base seed and a label (`dev-queries`, `test-queries`, `typos`, `hidden-dev`,
`hidden-test`, `out-of-stock`, `traffic-1` … `traffic-3`), so adding one random step never changes the others.
Same inputs + seed → byte-identical outputs (hash test, Task 2.3).

| Set | Rule | Used for |
|---|---|---|
| **dev** | 300 queries drawn uniformly from the ESCI *train* split (`us`, `small_version = 1`) | All relevance tuning (Task 3.5), the synonym list, the detection thresholds |
| **test** | 700 queries drawn uniformly from the ESCI *test* split, **after removing** any query whose normalized text (§6 normalization) equals a dev query's | Reported NDCG, **run once**, after the freeze (Task 8.1) |
| **test-typo** | The 700 test queries, each with one seeded typo (§6.3), same judgments | Typo robustness (FR2) |
| **catalog** | Union of all products judged (any label) for the dev + test queries | The shop's products (about 20k from the profile; exact count recorded by Task 2.3) |
| **qrels** | (query id, product id, label, gain) for dev + test | NDCG |
| **traffic pool** | dev + test queries | Virtual shoppers (Locust) |

- dev ∩ test = ∅ by ESCI split **and** by normalized text (checked by a test). The number of removed duplicates is
  recorded.
- Every judged product of every selected query is in the catalog, so NDCG is not penalised by missing products.
- **Test queries in the traffic pool** do not leak labels into NDCG **as long as no click- or popularity-based ranking
  feature is used**. If one is ever added, NDCG runs must disable it or exclude test-query traffic, with an ADR.
- **Synonyms** (FR2, Task 3.6): the starter synonym list is built only from dev queries and general vocabulary, never
  from test queries; it is frozen with the configuration and its size is reported.

## 4. Hidden sets and out-of-stock set

- Two **disjoint** hidden sets, each 20 % of the catalog size, stratified by category, drawn only among products that
  are the **Exact (E)** match of at least one traffic-pool query (otherwise no shopper would ever look for them):
  - **hidden-dev** — for choosing the signal thresholds (§5.3);
  - **hidden-test** — for the reported detection result.
  If the E-targets are too few for two disjoint 20 % sets, hidden-dev is reduced (it only serves tuning) and the sizes
  are recorded.
- **Out-of-stock set:** 10 % of the products in neither hidden set start with zero stock (default), for FR3 and the
  out-of-stock signal.
- All sets are written by the slice builder (Task 2.3) and recorded with their hashes.

## 5. Lost-demand detection (E2)

### 5.1 Signals

Defaults from `04` §8.2; thresholds are module settings, chosen on the dev campaign (§5.3) and frozen.

| Signal | Definition |
|---|---|
| Zero-result query | ≥ *a* searches with 0 results for the same normalized query, from ≥ 2 distinct sessions, in the window (default *a* = 3) |
| **Unsatisfied query (proposed: add)** | Searches with results but no click or add-to-cart carrying the same `search.id` within 120 s: count ≥ *b*, unsatisfied rate ≥ *r*, ≥ 2 distinct sessions (defaults *b* = 5, *r* = 0.6) |
| Out-of-stock demand | Per product: `1·views + 2·clicks + 5·add_to_cart ≥ c`, ≥ 2 distinct sessions, and current stock ≤ 0 (default *c* = 10) |

**Why the unsatisfied signal is proposed.** In a 20k-product catalog, a search for a hidden product almost always still
returns *other* products (the same words appear in many titles), so it rarely produces zero results. With the
zero-result signal alone, recall on the hidden set would be close to 0 by construction, and the 80 % target could not be
met whatever the quality of the system. A shopper who looks for a product that is gone typically gets results but does
not click or buy: that is the signal to detect.

### 5.2 Detection rule and metrics

- A hidden product *p* is **detected** if at least one query *q* with label(*q*, *p*) = E appears in the lost-demand
  report (zero-result list, or unsatisfied list if approved). Only hidden products searched at least 3 times during the
  run count (the denominator).
- **Recall** = detected hidden products / hidden products searched ≥ 3 times (target ≥ 0.8).
- **Precision** = reported queries that target a hidden or out-of-stock product (label E) / all reported queries.
- **Excess flags** (from the negative control, §5.3): flags in the test campaign minus flags in the control campaign,
  per hour of traffic. It separates "the product is missing" from "the ranking is poor".
- **Time to detection:** recall after *t* minutes (*t* = 5, 10, … 45) and the median number of searches for a hidden
  product before it is first flagged. Computed by running the detection over growing windows [start, *t*] of the same
  events: no extra traffic.
- Secondary: recall of the out-of-stock signal on the out-of-stock set.
- Misses are listed with their reason (not searched enough, query normalised differently, below a threshold).

### 5.3 Campaigns

All campaigns: baseline snapshot restored, Locust `detection` profile (50 users, Zipf popularity over the traffic pool),
lost-demand job over a window covering the run, report exported, hidden set reverted (`uv run shop eval hide --revert`).

| Campaign | Hidden | Shopper model | Seed | Length | Purpose |
|---|---|---|---|---|---|
| D1 dev | hidden-dev | default | traffic-1 | 45 min | Choose *a*, *b*, *r*, *c* (grid over a few values, best F1 on hidden-dev), then **freeze** them |
| D2 control | none | default | traffic-1 | 45 min | False alarms with nothing missing (precision baseline) |
| D3 test | hidden-test | default | traffic-1 | 45 min | **Reported** recall, precision, excess flags, time-to-detection curve |
| D4–D5 seeds | hidden-test | default | traffic-2, traffic-3 | 20 min | Spread across simulation randomness |
| D6 noisy shoppers | hidden-test | noisy variant | traffic-1 | 20 min | Robustness to the click model |

- The **noisy variant** flattens click attractiveness (E 0.4, S 0.25, C 0.15, I 0.10, unjudged 0.10) and adds 5 %
  random clicks: shoppers who sometimes click on anything, so "no click" is a weaker signal.
- D4–D6 are compared with D3's recall at 20 minutes (from the time-to-detection curve), so all lengths match.
  Reported: D3 at 20 and 45 minutes; min, mean and max over D3–D5 at 20 minutes; D6 at 20 minutes.
- Total about 3 h 15 min of laptop time in Milestone 8.

## 6. Search quality (E1)

### 6.1 Metric

- **Gains:** E = 1.0, S = 0.1, C = 0.01, I = 0, the ESCI benchmark convention: `ranking/train.py` (`esci_label2gain`)
  and the `trec_eval` NDCG mapping in `ranking/prepare_trec_eval_files.py` at the pinned commit (checked 2026-11-14).
- **NDCG@10:** `DCG@10 = Σ_{i=1..10} gain_i / log2(i + 1)`; `IDCG@10` from the ideal ordering of the query's judged
  products; NDCG@10 = DCG@10 / IDCG@10 (queries with IDCG = 0 are excluded and counted). Unjudged results count as 0.
- Also reported: **judged@10** (share of top-10 results that are judged) and **condensed NDCG@10** (unjudged results
  removed from the ranking before scoring, Sakai 2007) as a check that unjudged results do not change the order of the
  engines.
- **Normalization** of query text for duplicate removal and breakdowns: the same as the module's (`04` §8.1: NFKC,
  case-fold, trim, collapse whitespace, strip surrounding punctuation).

### 6.2 Engines and modes

- **Engines:** `odoo` (Odoo's native shop search), `es_plain` (Elasticsearch, default analysis, no tuning), `es_tuned`
  (the frozen configuration). Extra rows if built: `es_tuned_stock`, `hybrid` (FR13).
- **Modes:** `http` through the real `/shop` page (what shoppers see; **used for every reported number**); `direct`
  Elasticsearch only (fast tuning loop on dev). A consistency check compares both modes on dev.

### 6.3 Typo robustness

`test-typo`: for each test query, one edit in one word of ≥ 4 letters (swap, delete, duplicate, keyboard-neighbour
replace; the same model as the shoppers, `04` §9), seeded (`typos`); queries without such a word stay unchanged and are
counted. Reported: NDCG@10 per engine on `test-typo`, and the drop from `test`.

### 6.4 Breakdowns (where tuning helps, and where it does not)

NDCG@10 per engine on these subsets of `test` (sizes reported; subsets under 30 queries reported as indicative only):

- query length: 1–2 words, 3+ words;
- number of Exact products: 1, 2–5, 6+;
- **vocabulary mismatch** (synonyms, e.g. "hat" for a "headwear" product): queries where no Exact product's title shares
  a content word with the query after normalization (stop words removed, simple plural folding). Synonyms (Task 3.6) and
  semantic search (FR13) are expected to help here; this subset measures it on real ESCI data, without inventing
  synonym variants from the system's own list.

### 6.5 Statistics

- Mean NDCG@10 per engine with a 95 % bootstrap confidence interval (10,000 resamples, seeded).
- Pairwise engine differences (`es_tuned`–`es_plain`, `es_tuned`–`odoo`, `es_plain`–`odoo`): mean difference with its
  95 % bootstrap interval (effect size) and a paired randomization test (10,000 permutations, seeded), **Holm-corrected**
  over the three comparisons. Extra rows and breakdowns are descriptive (intervals only, no new claims).
- No claim of "higher" without the interval and the corrected test.

## 7. Speed, resilience, freshness, volume, usefulness (E3–E7)

- **Speed (E3):** baseline restored; Odoo workers set for load tests (`01` §5.3); 2-minute warm-up; Locust `speed`
  profile: 50 users, spawn rate 5/s, 10 minutes, search-heavy mix; three repetitions (mean and range). Search-page
  p50/p95/p99 and failure rate (Locust); `took_ms` p95 from the run's search events. Machine and RAM profile recorded.
- **Resilience (E7):** a fourth speed run in which Elasticsearch is stopped at minute 5 and started at minute 7.
  Reported: failed requests (target 0), page p95 before, during and after the outage, time until the circuit breaker
  closes again, and that searches during the outage were answered by Odoo's own search (events or logs).
- **Freshness (E4):** events — 200 probe searches with unique tokens (`traffic = probe`), poll Elasticsearch every
  200 ms, delay = found time − `@timestamp` (same host clock); p50/p95/max, and "visible in Kibana" = that delay + the
  dashboard refresh interval (5 s). Products — 30 stock or price changes through the Odoo API; poll shop search until
  visible; p50/p95/max.
- **Volume (E5):** REES46 replay until `source: rees46` holds ≥ 10 M events; ingest throughput, store size, heap; load
  the Volume and Demand-by-category dashboards 5 times over 30 days of data; time until all panels render (automated if
  feasible, otherwise a stopwatch on a screen recording; the method is stated).
- **Usefulness (E6):** interviews before (Task 1.6) and after a demo (Task 11.2), guide and consent in `docs/pilot/`,
  anonymised notes. Besides the open questions, the same five 1–5 ratings before and after (how they learn what
  customers want today / would learn with the tool; usefulness of the "customers asked for" list; trust in the
  restock proposals; would they act on it; clarity of the screens). With one shop owner these are reported as answers,
  not statistics.

## 8. Runs and reproducibility

Every campaign: restore the baseline snapshot; write `results/<run-id>/run.json` (kind, git SHA and dirty flag,
command, frozen configuration or its hash, seeds, versions, data checksums, machine, start and end); keep raw outputs in
`results/<run-id>/` (git-ignored); write the summary to `results/summary/` (committed); report in
`docs/evaluation/results.md`. Before any number goes into the report: the run folder exists, the command re-runs from a
clean checkout of that SHA, the data checksums match `data/manifest.toml`, and the table or figure is generated by a
committed script. Numbers are never edited by hand.

**Freeze rule (Task 8.1):** the configuration (analyzers, synonyms, boosts, signal thresholds from D1, shopper models)
is frozen and tagged before the test-set run and campaigns D2–D6. A change after the freeze means a new freeze and new
runs, all reported.

## 9. Pre-registration

- After approval, the protocol is tagged **`protocol-v1`** in git: the method is provably fixed before any test result.
- Every analysis script (NDCG, statistics, breakdowns, detection metrics, time-to-detection) is written, tested and run
  on **dev** data before the first test run.
- `docs/evaluation/results.md` lists every deviation from the tagged protocol, with its reason.

## 10. Threats to validity

- ESCI labels reflect Amazon's catalog and judges; our catalog is a 20k slice of it, and every product is judged for
  some query (fewer unrelated "distractor" products than a real shop).
- Odoo's native ordering is not relevance-based by design, so the `odoo` row is a baseline, not a competitor.
- Virtual shoppers are a simulation (Zipf popularity, typo and click models): detection depends on that model. D4–D6
  measure how much.
- The vocabulary-mismatch subset is found by a word-overlap rule, which misses some synonyms and includes some
  non-synonyms.
- Prices, stock, categories and vendors are synthetic.
- One laptop: speed numbers depend on the machine and the RAM profile, which are recorded.
- REES46 is replayed from 2019 data at high speed; it tests volume, not shopper behaviour.

## 11. Decisions to approve

| # | Decision | Recommendation |
|---|---|---|
| D1 | Add the **unsatisfied-query signal** to the detection rule | Yes (§5.1) |
| D2 | Query set sizes | dev 300 (train split), test 700 (test split, duplicates of dev removed) |
| D3 | Base seed and derived streams | `20261025`, one stream per random step (§3) |
| D4 | Catalog = all judged products of dev + test | Yes |
| D5 | Two disjoint hidden sets (dev for thresholds, test for the result), 20 %, stratified, E-targets only | Yes |
| D6 | Detection campaigns D1–D6 (negative control, seeds, noisy shoppers; ~3 h 15 min) | Yes |
| D7 | Test queries in the traffic pool, with no click-based ranking feature | Yes |
| D8 | Reported NDCG from `http` mode; typo set, breakdowns, condensed NDCG, Holm correction | Yes |
| D9 | Resilience run (E7) and structured interview ratings | Yes |
| D10 | Pre-registration tag `protocol-v1` | Yes |
| D11 | Who approves | The supervisor; the academic supervisor too if required |

## Approval

| Date | Approved by | Decisions | Notes |
|---|---|---|---|
| 2026-11-14 | The supervisor (student developer) | D1–D11, all as recommended | After the review that added §5.3 campaigns, §6.3–6.5, E7, §9 |
| — | Academic supervisor | — | Not asked yet; to be obtained by the supervisor if required (D11) |
