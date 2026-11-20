# Proposed report outline, with the material for each chapter

A proposal to make writing easier, not a decision: the structure, length and language of the report are the
supervisor's and the academic supervisor's call (`CLAUDE.md`, human-only actions). Each chapter lists where its
material already is.

| # | Chapter | Material in the repository |
|---|---|---|
| 1 | Introduction: lost demand in small online shops; the question (can search logs drive restocking?) | `docs/sources/project-specification.pdf`; `01_ARCHITECTURE.md` §1; shop-owner interviews (Task 1.6, anonymised) |
| 2 | Background: ERP (Odoo), search engines (Elasticsearch, BM25, analyzers, synonyms), event data | `docs/report/notes/baseline-search.md` (how Odoo 19 search works, with code references); `04` §5–6 |
| 3 | Requirements (FR1–FR13) and constraints (one laptop, zero budget, Basic license, no personal data) | specification; `CLAUDE.md`; `docs/setup/VERSIONS.md` feature-license table |
| 4 | Architecture: one Odoo module, Elasticsearch + Kibana, Python tools, Docker Compose | `01_ARCHITECTURE.md`; ADR-001…019; `docs/report/kit/figures.md` |
| 5 | Implementation in Odoo: extension by inheritance, never by editing the core | `docs/report/kit/odoo-overrides.md` (every override with Odoo's original and our addition); module `README.md` |
| 6 | Data: Amazon ESCI (real queries, human labels), labelled-synthetic shop data, REES46 events | `results/summary/esci-profile.md`, `slice-report.md`, `enrichment-report.md`; ADR-012; `docs/report/notes/M2.md` |
| 7 | Search: product index, sync within a minute (FR1), Elasticsearch search with fallback (FR2–FR3) | `docs/report/kit/odoo-overrides.md`; `figures.md` D1–D3; `results/summary/freshness-products.md`; `odoo-overrides.md` Task 3.3 (search override, fallback), `figures.md` D4, `engineering-log.md` 3.3; Tasks 3.4–3.6 |
| 8 | Events and dashboards (FR6–FR7) | M4 (to come) |
| 9 | Lost-demand detection and restocking (FR8–FR10) | M6 (to come); protocol v1.1 hidden sets |
| 10 | Evaluation protocol and results (NDCG, detection recall, speed, freshness, volume, usefulness) | `docs/evaluation/protocol.md` (tagged before any result); `docs/report/kit/results-index.md` |
| 11 | Engineering: quality gate, tests, CI, reproducibility; problems met and lessons | `docs/ai/03_GIT_TESTING_PIPELINE.md`; `docs/report/kit/engineering-log.md`; milestone notes |
| 12 | Limits, threats to validity, future work | synthetic prices/stock; ESCI judged-only catalog; laptop-scale measurements; negative results as found |
| 13 | Conclusion | — |

Appendices worth keeping in mind: the evaluation protocol, the version table, the override list, the run
metadata format (`04` §12).
