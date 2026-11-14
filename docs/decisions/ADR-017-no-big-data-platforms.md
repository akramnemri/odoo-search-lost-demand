# ADR-017 — No Kafka, Spark, Hadoop or cloud services

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
The data volume (≥ 10 million events) fits one laptop; the budget is zero.

## Decision
No Kafka, Spark, Hadoop or cloud services. Elasticsearch handles storage and aggregation; tools stream files.

## Consequences
Simpler setup; the report explains why these platforms are not needed at this volume.

## Revisit when
—
