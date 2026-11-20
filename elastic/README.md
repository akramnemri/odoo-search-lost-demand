# Elasticsearch as code

Index templates, mappings, analyzers, ingest pipelines, ILM policies and the synonyms seed, as JSON files
applied by `es-setup` or the module. Nothing kept only in Kibana Dev Tools.

- product index (Task 3.1): kept **in the module**, `addons/website_sale_lost_demand/elastic/products/`
  (settings and analyzers, mapping, synonyms seed), because the Odoo container mounts only `addons/` and the
  module builds the index itself (`uv run shop index rebuild` or the button in Website settings)
- `events/` — event data stream (Task 4.1)
