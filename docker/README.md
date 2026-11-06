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
uv run shop db create    # first time only, about 2 min: the shop database (Task 1.2a)
```

Odoo never creates its database by itself: `odoo.conf` has no `db_name` (with it, the 19.0 server creates a blank
database with the login admin/admin at every start). `uv run shop db create` creates it without demo data, installs
the shop apps (eCommerce, stock on the shop, purchase with stock, the Demo payment provider in test mode), names the
company and website "Lost Demand Demo Shop" (USD, generic chart of accounts), sets the `admin` password from
`ODOO_ADMIN_LOGIN_PASSWORD`, creates the integration user `ODOO_INTEGRATION_LOGIN` and writes its JSON-2 API key to
`ODOO_API_KEY`. Odoo's output goes to `local/logs/db-create.log`. `uv run shop db reset` deletes the database and its
filestore and creates it again; it asks you to type the database name first.

## Snapshots

```bash
uv run shop snapshot save baseline       # database + filestore -> local/snapshots/baseline/ (Odoo keeps running)
uv run shop snapshot list
uv run shop snapshot restore baseline    # DESTRUCTIVE: asks you to type the database name
```

A snapshot is `db.dump` (`pg_dump --format=custom`, run in the `db` container so the client matches the
PostgreSQL 16 server), `filestore.tar` and `metadata.toml` (time, git SHA, Odoo image, SHA-256 of both files,
row counts). Restore checks the checksums, stops Odoo, restores into a temporary `shop_restore` database
(`pg_restore --exit-on-error --jobs=4`), unpacks the filestore beside the current one, and only then swaps both
and starts Odoo again; it compares the row counts and checks the API key in `.env`. If a step fails before the
swap, the shop is unchanged. Measured: save 9 s, restore 39–41 s for the 65 MB database of Task 1.2b.
Odoo's own `odoo db dump|load` is not used: the image's pg_dump/psql 18 write `SET transaction_timeout`, which
PostgreSQL 16 rejects, and Odoo's restore does not stop on SQL errors.

`uv run shop env init` writes `.env` (git-ignored) with generated passwords; your Kibana login is
`KIBANA_PERSONAL_USER` / `KIBANA_PERSONAL_PASSWORD` in that file. Odoo: http://127.0.0.1:8069,
Kibana: http://127.0.0.1:5601, Elasticsearch: http://127.0.0.1:9200.

`uv run shop down` stops the stack and keeps the volumes. Never run `docker compose down -v` or remove the
volumes: they hold the database and the indices.
