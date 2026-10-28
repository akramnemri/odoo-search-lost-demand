# ADR-012 — Datasets: Amazon ESCI and REES46, never committed

- Status: Accepted (REES46 license use to be confirmed by the supervisor)
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Specification section 9: real queries with relevance labels, plus volume for dashboards.

## Decision
Amazon ESCI (Apache-2.0) for catalog, queries and relevance labels; REES46 (Kaggle) for volume; seeded synthetic
enrichment, labelled synthetic. Data is never committed; `data/manifest.toml` records sources, versions and checksums.

## Consequences
Anyone can rebuild the data from the manifest. The REES46 Kaggle license field reads "Data files © Original Authors"
(checked 2026-10-28), which is not an open license. Until the supervisor decides otherwise, use is limited to academic
analysis with attribution and no redistribution.

## Revisit when
The supervisor (or academic supervisor) rules on REES46 use, before Task 7.1.
