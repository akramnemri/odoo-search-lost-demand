# ADR-019 — Catalog import through Odoo's JSON-2 API

- Status: Accepted (2026-11-14, supervisor; Task 2.4 plan)
- Date: 2026-11-14
- Source: `docs/ai/05_ROADMAP.md` Task 2.4 ("JSON-2 API, or an in-container ORM script if measurably faster — decide
  in the plan, ADR")

## Context
About 20,000 products, 23 categories and 20 vendors must go into the shop database, idempotently (a second run
creates nothing) and resumably. Two ways exist: Odoo's public JSON-2 API (`POST /json/2/<model>/<method>`, bearer API
key; XML-RPC and JSON-RPC are deprecated in 19.0 and removed in 22) as the integration user, or a Python script run
inside the `odoo` container with `odoo shell`, writing through the ORM directly.

## Decision
The importer (`uv run shop import catalog`, `tools/shoptools/catalog_import.py`) uses **JSON-2**, in batches of 200
products per `create` call, after one `search_read` per batch to find what exists by `default_code`.

- It is the public, supported integration path: Odoo's access rights and business rules apply to every record, as
  for a real shop integration, and the integration user's rights are proven by the import itself.
- It needs no code inside the container and no shell access to the database.
- Records are found again by stable keys (`default_code` = ESCI id, vendor `ref`, category name), so a stopped run
  resumes without a checkpoint file.

**Switch condition:** if the full import, measured on `--limit 200` and `--limit 2000`, would take more than 30
minutes, the supervisor is asked before anything else is done (an in-container ORM script would then be considered).

## Consequences
Every product write goes through HTTP and a transaction per call; timing is measured and recorded (Task 2.4a, 2.4b).
The integration user needs create rights on products, vendor prices, both category models, partners and stock
quants; `shop db create` checks them (`odoodb.WRITE_MODELS`).

## Revisit when
The measured full-import time exceeds 30 minutes, or Odoo changes the JSON-2 API.
