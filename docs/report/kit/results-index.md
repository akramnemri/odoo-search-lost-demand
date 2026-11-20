# Results index

Every result the report may cite, and where it comes from. The numbers themselves live in the generated files
(never retyped here). A result is citable only if its file names a run folder and a git commit; a run on
uncommitted code is marked `-dirty` and is not citable.

| Result | Requirement / protocol | Command | Generated file | Run folder (local) | State |
|---|---|---|---|---|---|
| ESCI profile (queries, judgments) | data, protocol §2 | `uv run shop data profile esci` | `results/summary/esci-profile.md` | — | done (M2) |
| Catalog slice and query sets | protocol §3 | `uv run shop data build-slice` | `results/summary/slice-report.md` | — | done (M2) |
| Synthetic enrichment (prices, stock, categories, vendors; hidden sets) | protocol v1.1 | `uv run shop data build-slice` | `results/summary/enrichment-report.md` | — | done (M2) |
| Catalog import into Odoo (timings, counts) | Task 2.4 | `uv run shop import catalog` | `results/summary/catalog-import.md` | — | done (M2) |
| Baseline: Odoo's native search on dev queries (zero-result rate, exact on page 1) | 04 §11.1 context | `uv run shop eval baseline-search` | `results/summary/baseline-search.md` | `results/baseline-search-*` | done (M2), reproduced 2026-11-19 |
| Product change → searchable delay (p50/p95/max) | FR1, 04 §11.4 | `uv run shop probe products --count 30` | `results/summary/freshness-products.md` | `results/probe-products-*` | first run 2026-11-20 (Task 3.2, index level; shop-page level after Task 3.3) |
| Full rebuild time (19,869 products) | FR1, 01 §8 | `uv run shop index rebuild` | printed + `local/logs/index-rebuild.log` | — | recorded in STATUS (17–28 s); not a protocol result |
| NDCG@10 for `odoo`, `es_plain`, `es_tuned` (dev) | 04 §11.1 | Task 3.4 harness | — | — | planned (M3) |
| Hidden-product detection recall | 04 §11.2 | M6 | — | — | planned |
| Search page p95, ES `took` p95 | 04 §11.3 | Locust (M5) | — | — | planned |
| Event → Kibana delay | 04 §11.4 | probe events (M4) | — | — | planned |
| Events stored, dashboard load | 04 §11.5 | REES46 replay (M7) | — | — | planned |
