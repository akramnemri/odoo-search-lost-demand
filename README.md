# Search and lost-demand analysis for an Odoo online shop

Final-year project (ERP + Big Data). An Odoo 19 Community shop whose search runs on Elasticsearch, and which turns
every search, click, add-to-cart and purchase into restocking decisions inside Odoo.

- Elasticsearch-powered shop search with typo tolerance, synonyms and in-stock ranking, falling back to Odoo's search
- Live events and Kibana dashboards (free Basic license)
- A lost-demand job that finds zero-result searches and out-of-stock demand, and proposes draft purchase orders
- Evaluation on real shopping queries (Amazon ESCI) and large-scale behavior data (REES46)

**Status:** Milestone 0 (environment and repository foundation). Progress: [`docs/progress/STATUS.md`](docs/progress/STATUS.md).

## Quick start

The one-command stack arrives in Milestone 1. Today:

```bash
uv sync
uv run shop --help
uv run pytest
uv run pre-commit install
uv run pre-commit run --all-files
```

Prerequisites and pinned versions: [`docs/setup/VERSIONS.md`](docs/setup/VERSIONS.md);
machine setup: [`docs/setup/ENVIRONMENT.md`](docs/setup/ENVIRONMENT.md).

## Repository layout

| Path | Content |
|---|---|
| `addons/website_sale_lost_demand/` | The Odoo module (Milestone 1+) |
| `docker/`, `compose.yaml` | Docker images and the Compose stack (Milestone 1) |
| `elastic/`, `kibana/` | Index templates, pipelines and dashboards as code |
| `tools/shoptools/`, `tools/tests/` | The `shop` CLI and its tests |
| `loadtest/` | Locust virtual shoppers |
| `scripts/` | Bootstrap scripts |
| `data/`, `results/` | Datasets and run outputs (git-ignored, except instructions and summaries) |
| `docs/` | Architecture, decisions (ADRs), setup, evaluation, report |

## Data and attribution

Datasets are never committed. See [`data/README.md`](data/README.md).

- Amazon Shopping Queries Dataset (ESCI), Apache-2.0: <https://github.com/amazon-science/esci-data>
- eCommerce behavior data from multi category store (REES46), via Kaggle:
  <https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store> — used for academic
  analysis only, raw data never redistributed ([ADR-012](docs/decisions/ADR-012-datasets.md))

Prices, stock levels, categories and vendors added to ESCI products are **synthetic**.

## License

[LGPL-3.0-only](LICENSE) (the LGPL supplements the [GPL-3.0](COPYING)).
