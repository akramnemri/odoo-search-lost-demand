# Docker

The stack is defined in `../compose.yaml` (project name `odoo-search-lost-demand`). Versions: `docs/setup/VERSIONS.md`.

- `odoo/` — our Odoo image: `FROM` the pinned `odoo:19.0` dated tag + the pinned Elasticsearch client
  (`requirements.txt`, the full set pinned). `odoo.conf` is a template without secrets; `entrypoint.sh` fills it from
  the container environment at start, then runs the official entrypoint.
- `es-setup/` — `setup.sh`, run once per `docker compose up` in the Elasticsearch image: asserts the Basic license,
  sets the `kibana_system` password, creates the roles and users of `docs/ai/01_ARCHITECTURE.md` §5.2.
  Safe to re-run; passwords always follow `.env`.

## First start

```bash
uv run shop env init
docker compose pull      # first time only, about 2.3 GB
uv run shop up           # = docker compose up -d --wait; `--no-kibana` to save memory
uv run shop status
```

`uv run shop env init` writes `.env` (git-ignored) with generated passwords; your Kibana login is
`KIBANA_PERSONAL_USER` / `KIBANA_PERSONAL_PASSWORD` in that file. Odoo: http://127.0.0.1:8069,
Kibana: http://127.0.0.1:5601, Elasticsearch: http://127.0.0.1:9200.

`uv run shop down` stops the stack and keeps the volumes. Never run `docker compose down -v` or remove the
volumes: they hold the database and the indices.
