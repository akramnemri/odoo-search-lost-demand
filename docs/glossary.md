# Glossary

Domain and project terms used in code, docs and the report. Code uses these names (`docs/ai/02_CODING_STANDARDS.md` §12).

| Term | Meaning |
|---|---|
| Lost demand | Sales the shop misses because shoppers do not find what it has, or want what it does not have |
| Zero-result search | A search whose result page, after Odoo re-filtering, shows no product |
| Unsatisfied search | A search with results but no click or add-to-cart on the same `search.id` within a time limit (proposed signal, needs approval in Task 2.2) |
| Normalized query | The query after Unicode NFKC, case-folding, trimming, whitespace collapsing and surrounding-punctuation stripping, with PII masks kept; no stemming |
| Signal | A detected lost-demand gap stored in Odoo (`lost_demand.signal`): zero-result query, unsatisfied query, or out-of-stock demand |
| Out-of-stock demand | A product with weighted demand (views, clicks, add-to-cart) above a threshold while its Odoo stock is zero or below |
| Restock proposal | A suggested purchase (`lost_demand.proposal`) for a product with out-of-stock demand; becomes a draft RFQ only after buyer approval |
| RFQ | Request for quotation: Odoo's draft purchase order |
| Asked-for entry | An item of the "customers asked for" list (`lost_demand.asked_for`, FR10): a query customers searched that the shop could not satisfy |
| Outbox | A database table where changes or events are written in the same transaction as the business change, then sent to Elasticsearch in bulk by a job |
| Flush | The job run that sends outbox rows to Elasticsearch and deletes them once accepted |
| Alias swap | Pointing the `shop-products` alias to a newly built `shop-products-v<N>` index in one atomic operation |
| Fallback | Using Odoo's native search when Elasticsearch fails or is slow |
| Circuit breaker | Per-process switch that stops calling Elasticsearch after repeated failures, then retries after a cooldown (closed → open → half-open) |
| Engine | The search implementation used for a request: `odoo`, `odoo_fallback`, `es_plain`, `es_tuned`, `es_tuned_stock`, `hybrid` |
| Traffic type | Origin of an event: `human`, `virtual` (Locust), `eval` (harness), `probe` (freshness), `replay` (REES46) |
| Source | Data origin of an event: `shop` or `rees46` |
| Run | One recorded execution (lost-demand job, evaluation, load test, replay) with an ID and metadata (`run.json`) |
| ESCI | Amazon Shopping Queries Dataset; labels E (exact), S (substitute), C (complement), I (irrelevant) |
| REES46 | Public multi-category e-commerce behavior dataset (Kaggle) used for volume and dashboard tests |
| qrels | Relevance judgments file: query ID, product ID, label, gain |
| NDCG@10 | Normalized discounted cumulative gain over the first 10 results; the search-quality metric |
| Dev set / test set | Query sets for tuning (dev) and for final reporting, used once (test) |
| Hidden set | Products unpublished during the detection campaign to test whether lost demand is detected |
| Synthetic | Values added by us to ESCI products (categories, prices, stock, vendors); always labelled as such |
| RAM profile | Resource settings for the laptop: `lowmem` (8 GB) or `standard` (16 GB) |
| Doctor | `uv run shop doctor`: read-only environment and stack health check |
