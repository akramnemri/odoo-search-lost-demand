# ADR-012 — Datasets: Amazon ESCI and REES46, never committed

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Specification section 9: real queries with relevance labels, plus volume for dashboards.

## Decision
Amazon ESCI (Apache-2.0) for catalog, queries and relevance labels; REES46 (Kaggle) for volume; seeded synthetic
enrichment, labelled synthetic. Data is never committed; `data/manifest.toml` records sources, versions and checksums.

## REES46 usage rules (supervisor decision, 2026-10-28)
The Kaggle license field reads "Data files © Original Authors" (checked 2026-10-28), which is not an open license.
REES46 publishes the data as a free dataset, but a free download does not grant redistribution rights. Therefore:

- academic, non-commercial analysis only;
- attribution to both REES46 and the Kaggle dataset (`mkechinov/ecommerce-behavior-data-from-multi-category-store`)
  in `data/README.md`, the README and the report;
- raw files stay local and private (`data/raw/`, git-ignored); they are never committed, uploaded or shared;
- only code, documentation and derived aggregate results (counts, rates, timings, dashboards screenshots) are published;
- Elasticsearch snapshots or exports containing REES46 events are never published.

## Consequences
Anyone can rebuild the data from the manifest after downloading REES46 themselves with their own Kaggle account.

## Revisit when
The academic supervisor or the university requires a different rule, or REES46 publishes an explicit license.
