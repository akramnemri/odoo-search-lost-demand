# Data

Datasets are **never committed** (ADR-012). This folder holds only this file and `manifest.toml`
(source URL, version, SHA-256, size, license and download date of every file).

| Folder | Content |
|---|---|
| `raw/` | Untouched downloads, never modified |
| `interim/` | Intermediate Parquet files |
| `processed/` | Catalog slice, query sets, qrels, hidden set, id map |

## Datasets

| Dataset | How to get it | License |
|---|---|---|
| Amazon Shopping Queries Dataset (ESCI) | `uv run shop data fetch esci` (Task 2.1) — 1.16 GB from the repository's Git LFS storage at the commit pinned in `docs/setup/versions.toml`, each file checked against its pinned size and SHA-256; `uv run shop data profile esci` writes `results/summary/esci-profile.md` | Apache-2.0 |
| REES46 eCommerce behavior data | `uv run shop data fetch rees46` (Task 7.1) — needs your own Kaggle account and token, ≈ 14 GB | "Data files © Original Authors": academic analysis only, never redistributed |

Citation: Reddy et al., *Shopping Queries Dataset: A Large-Scale ESCI Benchmark for Improving Product Search* (2022);
REES46 Marketing Platform, *eCommerce behavior data from multi category store* (Kaggle). Exact references are recorded
with the downloads.

## ESCI download, step by step

1. `uv run shop data fetch esci --dry-run`: files, sizes, free disk and a time estimate; nothing is downloaded.
2. `uv run shop data fetch esci`: asks, then downloads into `data/raw/esci/`. Each file is written to `<name>.part`,
   resumed after an interruption (run the command again), and renamed only when its size and SHA-256 match.
   Files already present and correct are skipped. The entries in `manifest.toml` are written at the end.
3. `uv run shop doctor --section data`: size, Parquet markers (a Git LFS pointer file is detected) and manifest.

## Catalog slice and query sets (Task 2.3a)

1. `uv run shop data build-slice --dry-run`: checks the ESCI files are present, selects the dev and test queries and
   counts their judgments; writes nothing.
2. `uv run shop data build-slice`: checks the ESCI files against their pinned SHA-256, then writes into `processed/`
   `queries-dev.parquet`, `queries-test.parquet`, `queries-test-typo.parquet`, `qrels.parquet`, `catalog.parquet` and,
   last, `slice-manifest.json`; aggregates in `results/summary/slice-report.md`. About 15–25 s, under 0.7 GiB of memory.
3. Same seed and settings (`tools/shoptools/data/slice.toml`) give the same SHA-256 for every output: compare two runs.

The same command also builds the shop catalog (Task 2.3b): `products.parquet` with **synthetic** category, price,
stock and vendor, `vendors.parquet`, the hidden sets `hidden-test.parquet` and `hidden-dev.parquet` and
`out-of-stock.parquet`; aggregates in `results/summary/enrichment-report.md`. About 15–30 s and under 0.8 GiB in total.
