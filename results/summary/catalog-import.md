# Catalog import: record of a real run

Written by `uv run shop import catalog` (Tasks 2.4a-b, ADR-019) after a run that changed something.
Timings depend on the machine and on what Odoo had to do: a first import creates products and
stock moves, a re-run only compares. The data is SYNTHETIC except the ESCI texts (docs/ai/04 §4).

- date (UTC): 2026-11-15T01:23:04Z
- command: `uv run shop import catalog`; git `89ececdebd2fed4cc9d75775a32d7d13b8ff5ee6-dirty`
- machine: Windows AMD64, 16 logical CPUs; Python 3.12.16
- products: 19,869 of 19,869 in `products.parquet`

| what | created | updated | unchanged |
|---|---:|---:|---:|
| categories (public + internal) | 0 | 0 | 47 |
| vendors | 0 | 0 | 20 |
| products | 0 | 19,869 | 0 |
| stock (inventory adjustment) | — | 0 adjusted | 19,869 |

- total 122 s; 100 batches of up to 200; 5.6 ms per product
- batch time: median 1.1 s, p95 1.5 s, max 4.6 s
- id map: 19,869 products in `data/processed/odoo_id_map.parquet`
