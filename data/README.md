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
| Amazon Shopping Queries Dataset (ESCI) | `uv run shop data fetch esci` (Task 2.1) — Git LFS, ≈ 1.1 GB | Apache-2.0 |
| REES46 eCommerce behavior data | `uv run shop data fetch rees46` (Task 7.1) — needs your own Kaggle account and token, ≈ 14 GB | "Data files © Original Authors": academic analysis only, never redistributed |

Citation: Reddy et al., *Shopping Queries Dataset: A Large-Scale ESCI Benchmark for Improving Product Search* (2022);
REES46 Marketing Platform, *eCommerce behavior data from multi category store* (Kaggle). Exact references are recorded
with the downloads.
