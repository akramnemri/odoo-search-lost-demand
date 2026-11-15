# Catalog import: record of a real run

Written by `uv run shop import catalog` (Tasks 2.4a, 2.4b; ADR-019) after every real run.
Timings depend on the machine and on what Odoo had to do: a first import creates products and
stock moves, a re-run only compares. The data is SYNTHETIC except the ESCI texts (docs/ai/04 §4).

- date (UTC): 2026-11-15T00:55:52Z
- command: `uv run shop import catalog`; git `52720451976e89fb8135efaa61dd4c615e1e0f7f-dirty`
- machine: Windows AMD64, 16 logical CPUs; Python 3.12.16
- products: 19,869 of 19,869 in `products.parquet`

| what | created | updated | unchanged |
|---|---:|---:|---:|
| categories (public + internal) | 0 | 0 | 47 |
| vendors | 0 | 0 | 20 |
| products | 16,869 | 0 | 3,000 |
| stock (inventory adjustment) | — | 15,287 adjusted | 4,582 |

- total 442 s; 100 batches of up to 200; 21.9 ms per product
- batch time: median 5.0 s, p95 5.5 s, max 7.4 s
- id map: 19,869 products in `data/processed/odoo_id_map.parquet`
