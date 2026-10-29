# Pinned versions

Status: **APPROVED by the supervisor on 2026-10-28 (Task 0.2).** Verified on 2026-10-28 from the official sources listed.
Machine-readable copy for the doctor: [`versions.toml`](versions.toml). Decision record: [ADR-018](../decisions/ADR-018-pinned-versions.md).

Upgrade rule: patch versions only, at milestone boundaries, with an ADR line and a full regression check (`06` §3).

## 1. Stack (pinned in the repository)

| Component | Pin | Why | Source | Verified | Notes |
|---|---|---|---|---|---|
| Odoo image | `odoo:19.0-20261015` | Newest dated 19.0 tag; dated tag = reproducible build (ADR-002) | [Docker Hub tags](https://hub.docker.com/_/odoo/tags?name=19.0), [odoo/docker 19.0 Dockerfile](https://github.com/odoo/docker/blob/master/19.0/Dockerfile) (`ODOO_RELEASE=20261015`, `ODOO_SHA=3a2e406fa0399944a7c339baa5f53ca2e783e71b`) | 2026-10-28 | amd64 image 666 MB compressed. Base `ubuntu:noble`; exposes 8069/8071/8072; volumes `/var/lib/odoo`, `/mnt/extra-addons` |
| Python inside the Odoo image | 3.12 | Ubuntu noble's `python3` (python3-defaults 3.12.3); the Dockerfile installs Odoo's deps from noble's `python3-*` packages | [Launchpad python3-defaults (noble)](https://launchpad.net/ubuntu/noble/+source/python3-defaults) | 2026-10-28 | **Confirmed 2026-10-29** (Task 1.1a): `python3 --version` in the image = 3.12.3 |
| Host Python (tools, via uv) | 3.12 (latest patch uv provides) | Same minor as the Odoo image (ADR-011); Odoo 19 accepts 3.10–3.14 | [`odoo/release.py` 19.0](https://github.com/odoo/odoo/blob/19.0/odoo/release.py) (`MIN_PY_VERSION = (3, 10)`, `MAX_PY_VERSION = (3, 14)`) | 2026-10-28 | `.python-version` = `3.12`. All chosen libraries support 3.12 (§3) |
| PostgreSQL | `postgres:16.15-trixie` | Odoo 19 minimum is 13; Odoo's own Docker examples use 15; pgvector needs ≥ 15. 16 is Ubuntu 24.04's default PostgreSQL (same OS as the Odoo image) | [`odoo/release.py`](https://github.com/odoo/odoo/blob/19.0/odoo/release.py) (`MIN_PG_VERSION = 13`), [19.0 install docs](https://github.com/odoo/documentation/blob/19.0/content/administration/on_premise/source.rst), [Odoo image README](https://hub.docker.com/_/odoo), [postgres tags](https://hub.docker.com/_/postgres/tags) | 2026-10-28 | Odoo publishes no maximum. **Kept by supervisor decision (2026-10-28):** a mature major (16.15 is its 15th patch release) on the same OS family as the Odoo image, with no known complication for this project |
| Elasticsearch | `docker.elastic.co/elasticsearch/elasticsearch:9.5.5` | Latest patch of the current 9.x minor (ADR-004) | [Elasticsearch release notes](https://www.elastic.co/docs/release-notes/elasticsearch), `docker.elastic.co` tag list (9.5.0 … 9.5.5) | 2026-10-28 | Image size announced before the pull (Task 1.1) |
| Kibana | `docker.elastic.co/kibana/kibana:9.5.5` | Must equal the Elasticsearch version | `docker.elastic.co` tag list (9.5.0 … 9.5.5) | 2026-10-28 | |
| `elasticsearch` Python client | `9.5.1` | Same major as the server; minor ≤ server minor | [PyPI](https://pypi.org/project/elasticsearch/) (latest 9.5.1, `requires_python >= 3.10`), [client compatibility](https://www.elastic.co/docs/reference/elasticsearch/clients/python) | 2026-10-28 | Installed in the Odoo image and in the tools environment. Odoo image: full set pinned in `docker/odoo/requirements.txt` (elastic-transport 9.4.2, anyio 4.15.1, sniffio 1.3.1, typing-extensions 4.16.0 — newer than Ubuntu's 4.10.0, installed in `/usr/local`) |

## 2. Host tools

"Minimum" is what the doctor accepts; "Latest" is the current release on the verification date.

| Tool | Minimum | Latest (2026-10-28) | This laptop | Source | Notes |
|---|---|---|---|---|---|
| Git | 2.40 | 2.56.0.windows.4 | 2.51.0 — OK | [git-for-windows releases](https://github.com/git-for-windows/git/releases) | Upgrade optional |
| Git LFS | 3.0 | 3.8.1 | 3.7.0 — OK | [git-lfs releases](https://github.com/git-lfs/git-lfs/releases) | Needed for ESCI |
| GitHub CLI | 2.40 (WARN only) | 2.103.3 | 2.102.0 — OK | [cli/cli releases](https://github.com/cli/cli/releases) | |
| uv | 0.13.6 | 0.13.6 (2026-10-27) | **missing** | [astral-sh/uv releases](https://github.com/astral-sh/uv/releases) | Install in Task 0.3 (`winget install --id astral-sh.uv -e`) |
| Docker Desktop | 4.60 | 4.97.0 (2026-10-26) | 4.60.1 — OK | [Docker Desktop release notes](https://docs.docker.com/desktop/release-notes/) | **Not updated (supervisor decision 2026-10-28):** 4.60.1 meets every need of this project, and an update would restart the engine under another project's running stack |
| Docker Engine / Compose | Engine 27 / Compose 2.20 | — | Engine 29.2.0 / Compose v5.0.2 — OK | — | Always `docker compose` (never v1 `docker-compose`) |
| WSL | 2.0 | — | 2.6.3 — OK | — | |
| PyCharm | 2025.1 (unified product) | 2026.2.3 | 2026.2.3 — OK | [JetBrains releases API](https://data.services.jetbrains.com/products/releases?code=PCP&latest=true&type=release) | Docker Compose interpreter checked in Task 1.4 |
| Kaggle CLI | — | — | — | — | Run with `uvx` in M7; version pinned then |

## 3. Python libraries (resolved and locked by uv in `uv.lock`, Task 0.4)

Latest versions on 2026-10-28, all compatible with Python 3.12 (from PyPI `requires_python`):

| Package | Version | Group | Purpose |
|---|---|---|---|
| ruff | 0.17.3 | dev | Lint + format |
| pre-commit | 4.7.0 | dev | Hooks |
| pytest | 9.2.0 | dev | Tests |
| elasticsearch | 9.5.1 | main | Tools talk to Elasticsearch |
| pandas | 3.1.0 | data | Small tabular work |
| pyarrow | 26.0.0 | data | Parquet streaming (ESCI) |
| locust | 2.47.0 | load | Virtual shoppers |
| sentence-transformers | 6.2.0 | semantic | FR13 only (Could) |

Candidates noted, not chosen yet (decided in the task that needs them): polars 2.1.0, duckdb 2.0.0 (streaming REES46 CSVs, M7).

## 4. Datasets

| Dataset | Source / version | License | Size | Verified | Notes |
|---|---|---|---|---|---|
| Amazon ESCI | [amazon-science/esci-data](https://github.com/amazon-science/esci-data), branch `main`, commit `7916cdf6ab75a462e77f20ab40428a10923998d5` (2024-10-07) | Apache-2.0 (GitHub license detection; re-check the LICENSE file at download, Task 2.1) | Git LFS: `shopping_queries_dataset_examples.parquet` 48.9 MB + `shopping_queries_dataset_products.parquet` 1,057.5 MB + sources CSV 1.7 MB ≈ **1.1 GB** | 2026-10-28 | The pack's "≈ 2.5 GB" estimate is corrected to ≈ 1.1 GB download (more once loaded) |
| REES46 | Kaggle `mkechinov/ecommerce-behavior-data-from-multi-category-store`, dataset version 8 (updated 2019-12-09) | Kaggle license field: **"Data files © Original Authors"** — not an open license | 13.67 GB (uncompressed total) | 2026-10-28 | **Supervisor decision (2026-10-28):** academic use only; cite REES46 and the Kaggle dataset; raw files stay local and private, never redistributed; only code, docs and aggregate results are published. See ADR-012 |

## 5. Odoo external API

| Item | Finding | Source |
|---|---|---|
| JSON-2 API | `POST /json/2/<model>/<method>`, header `Authorization: bearer <API key>` | [19.0 external API doc](https://github.com/odoo/documentation/blob/19.0/content/developer/reference/external_api.rst) |
| XML-RPC / JSON-RPC deprecation (removal planned for Odoo 22) | Not re-verified in this task (pack starting point) | Re-check before Task 1.2 |

## 6. Elastic feature-license table

Source: Elastic self-managed subscriptions page, PDF snapshot [`subscriptions-2026-08-04.pdf`](https://www.elastic.co/pdf/subscriptions-2026-08-04.pdf), read 2026-10-28.
Every "Used" feature is checked again on the running cluster (`GET _license` = basic) in the task that first uses it.

| Elastic feature | Needed for | Tier (from the PDF) | Decision |
|---|---|---|---|
| Role-based access control, file and native authentication, API keys | Spec security | Free – Basic | Used |
| Data streams, index lifecycle management, data stream lifecycle | Events | Free – Basic | Used |
| Ingest pipelines (Ingest Node Pipeline Builder) | Events | Free – Basic | Used |
| Synonym management, dynamically updateable synonyms | FR2 | Free – Basic | Used (confirm the synonyms API on the cluster, Task 3.1) |
| Type ahead, suggestions, corrections, aggregations | FR2–FR5 | Free – Basic | Used |
| Vector field type, vector search, retrievers: standard / kNN / pinned / rescorer | FR13 | Free – Basic | Used if FR13 is built |
| Data transforms | Optional (unsatisfied signal) | Free – Basic | Optional |
| Retrievers: linear, rule, RRF, text similarity re-ranker; RRF for hybrid search | — | **Enterprise** | **Not used** (fusion in the module, ADR-016) |
| Learning to Rank, Query Rules, DiskBBQ, rank vectors | — | **Enterprise** | **Not used** |
| ELSER, inference with Elastic models, ML anomaly detection | — | Paid (not in Basic) | **Not used** |
| Kibana dashboards, Lens, Discover | FR7 | Free (pack starting point; the PDF pages read did not cover the Kibana rows) | Used — confirm on the running Kibana (Task 4.5) |
