# 02 — Coding Standards: Maintainability, Reliability, Reproducibility

Act as a senior Python / Odoo / Elasticsearch engineer and reviewer.

These rules apply to every line you write in this repository.

## Core principle

Write code for another competent developer who will debug it six months from now, probably a student
preparing a defense the next morning, with little context.

Prefer understandable code over compact code.
Prefer explicit logic over magic.
Prefer a small robust solution over a clever general framework.
Prefer a result someone else can reproduce over a result that only works on your machine.

---

## 1. Python (everywhere)

- Python version: the one pinned in `docs/setup/VERSIONS.md` (host tools match the Odoo image's Python minor version).
- Formatting and linting with `ruff` (configured in `pyproject.toml`); run through pre-commit.
- Type hints on every function in `services/` (module) and `tools/`. In Odoo models, add them where they help.
- `pathlib` for paths, never string concatenation. Paths are relative to the repository root or configured.
- `dataclasses` (or plain typed dicts) for value objects such as events, search results, signals.
- No mutable global state, except where documented (the per-process circuit breaker in the module).
- Time: store and send UTC (`@timestamp` in ISO-8601 with timezone). Convert only for display.
- Money in the data pipeline: decimal strings or integer cents; never accumulate floats for totals.
- No `print` in library code; use `logging`. CLI commands may print user-facing output.

## 2. Odoo module rules

### 2.1 Structure and manifest

- Module version `19.0.MAJOR.MINOR.PATCH`; bump it whenever data files, models or views change.
- `depends` lists only what the module really needs. Verify module names in `.odoo-src/addons/` before adding them.
- `external_dependencies = {"python": ["elasticsearch"]}`; the package is installed in our Odoo image at the pinned version.
- Every model has access rights in `security/ir.model.access.csv`. Missing access rights are a bug, not a warning.

### 2.2 Inheritance, never modification

- Extend with `_inherit` (models) and by inheriting controller classes (routes). Always call `super()` unless you are
  deliberately replacing behavior; then write a comment explaining why and what the original did.
- Never monkey-patch Odoo functions. Never copy an Odoo method body into our module to change one line:
  call `super()` and adjust input or output instead. If that is impossible, explain it in the plan before coding.
- QWeb: inherit templates with small, precise `xpath` expressions. Never replace a whole standard template.
- Before overriding, open the method in `.odoo-src/` (19.0) and cite file + line range in the plan.

### 2.3 ORM and database

- ORM first. Raw SQL only for a measured need (for example `FOR UPDATE SKIP LOCKED` when draining an outbox), always
  parameterized, never built with string formatting, with a comment explaining why.
- Work in batches: `create()` with a list of values, `write()` on recordsets, `read()`/`search_read()` with explicit fields.
  No `browse()` + `write()` inside loops over thousands of records.
- `sudo()` only where a technical operation must bypass access rights (scheduled jobs, event capture for public users),
  with a comment. Never `sudo()` to hide a missing access right.
- No `cr.commit()` in request code. In scheduled jobs that process batches, commit per batch only through the batch/progress
  mechanism of `ir.cron` if 19.0 provides one (check `odoo/addons/base/models/ir_cron.py`), otherwise with a commented
  explicit commit and an idempotent design.
- Scheduled actions must be idempotent and safe to run twice in parallel (row locking or a run lock).
- Stored computed fields only when they are searched or grouped on.

### 2.4 Views, menus and UI

- Every new model has list and form views (and search view filters for state). Menus under Purchase (buyer features)
  and Website/Inventory configuration (administrator features).
- User-facing strings are wrapped for translation the way the 19.0 source does, even though the shop is English-only.
- Frontend JavaScript only when a server-side solution is impossible. Odoo 19's website JS framework differs from older
  tutorials: read existing 19.0 code before writing any.

### 2.5 Odoo tests

- `TransactionCase` for model logic, `HttpCase` for routes (`url_open`) — browser tours only if really needed.
- Tag tests (`post_install`, `-at_install`, plus `es` for tests that need a real Elasticsearch).
- Unit tests replace the Elasticsearch service with a fake implementing the same interface. No network in unit tests.
- Integration tests use a unique index prefix per run and delete their indices at the end.

## 3. Elasticsearch rules

- **Everything as code:** index templates, mappings, analyzers, ingest pipelines, ILM policies and synonyms seeds are JSON
  files in `elastic/`, applied by `es-setup` or by the module. Experiments in Kibana Dev Tools are allowed, but anything kept
  is codified before the task ends.
- Explicit mappings. Event mapping uses `"dynamic": "strict"` so unknown fields fail loudly.
- Single-node cluster: `number_of_replicas: 0` everywhere (otherwise the cluster stays yellow).
- Product indices are versioned (`shop-products-v<N>`) behind an alias; a mapping change means a new version + rebuild + alias swap.
- Query DSL is built by pure functions in `services/query_builder.py` (unit-tested; snapshot the generated JSON for key cases).
- Every request has a timeout. Shopper-facing search: short (default 500 ms total) then fallback. Background bulk: longer,
  with retries and backoff.
- Search requests return only what is needed (`_source: false` or a field list, `size` = page size, `track_total_hits` set on purpose).
- Bulk writes: use the client's bulk helpers, chunk (e.g. 500–2,000 docs), and **inspect per-item errors** — a bulk request
  can return 200 while some documents failed.
- Idempotent writes: fixed `_id` (product template ID, event UUID); `op_type: create` for events.
- Never use `refresh=true` or `wait_for` in request paths (tests and probes only).
- Log `took` for searches; it feeds the speed evaluation.
- Before using any feature, confirm it works on the Basic license (pinned version docs + a quick check on the running cluster)
  and add it to the feature-license table in `docs/setup/VERSIONS.md`.
- The Python client major version equals the server major version (pinned together).

## 4. Kibana rules

- Data views and dashboards are exported as saved-object NDJSON in `kibana/` and imported by `uv run shop kibana import`.
- Dashboards use indexed fields, not heavy runtime fields. Each panel title says what it measures and the unit.
- Default dashboard filters exclude `traffic: eval` and `traffic: probe`; REES46 panels filter on `source: rees46`.

## 5. Data pipeline and tools

- **Streaming, not loading.** REES46 (~110 M rows) and ESCI must never be loaded whole into memory. Read in chunks or
  with lazy/streaming readers. Memory budget for any tool: under 2 GB RAM, so it runs on 8 GB laptops.
- **Raw data is immutable.** `data/raw/` is never modified; transformations write to `data/interim/` or `data/processed/`.
- **Deterministic.** Every random choice uses a seed from a config file; the same inputs + seed produce byte-identical outputs
  (tested by hashing outputs).
- **Idempotent and resumable.** Imports and replays can be stopped and restarted without duplicates (upsert keys,
  checkpoint files).
- **Fast feedback.** Every long command supports `--limit N` and `--dry-run`, shows progress with an ETA, and prints a
  summary (counts, duration, output paths).
- **Atomic outputs.** Write to a temporary file then rename, so an interrupted run never leaves a half-written file that looks valid.
- **Checksums and provenance.** Downloaded files are recorded in `data/manifest.toml` (source URL, version or commit,
  SHA-256, size, license, download date). The doctor verifies them.
- **Columnar intermediates.** Parquet for intermediate data; CSV only for small human-readable outputs.
- Document every transformation (input, rule, output) in `04_DATA_SEARCH_EVALUATION.md` or the module docstring.

## 6. Locust (virtual shoppers)

- One user class per behavior; weighted tasks; think times; a seeded random generator per user.
- Validate responses (`catch_response=True`): check status and a content marker. A 200 OK error page is a failure.
- Group URLs in statistics (`name="/shop?search=[q]"`), otherwise statistics explode with one line per query.
- Handle Odoo sessions and CSRF tokens like a browser would. Parse only what the shopper model needs.
- Send the load-test key and run ID headers so events are tagged `traffic=virtual` with the run ID.
- Headless runs write CSV/HTML reports into `results/<run-id>/`.

## 7. Evaluation code

- Metrics (NDCG@10, recall/precision, percentiles, bootstrap confidence intervals) are implemented once in
  `shoptools/eval/metrics.py` and unit-tested against hand-computed examples.
- Every run creates `results/<run-id>/run.json` with: git SHA (and dirty flag), command, config, seed, versions of the stack,
  data checksums, machine profile, start/end time. No metadata, no result.
- Figures and tables for the report are generated by scripts from run folders, never edited by hand.

## 8. External boundaries

Treat Elasticsearch, Odoo's external API, Kaggle, GitHub/Git LFS and the embedding service as unreliable:

- validate inputs and outputs;
- credentials from the environment only;
- explicit timeouts;
- retries only for idempotent operations, with backoff and a maximum;
- errors mapped to clear messages ("Elasticsearch unreachable at http://127.0.0.1:9200 — is the stack up? run `uv run shop doctor`");
- log the operation and identifiers, never secrets.

## 9. Error handling

- No empty `except`. No bare `except:`. Catch the narrowest exception that makes sense.
- Do not silently turn unexpected errors into empty results. The **only** silent-looking path allowed is the shopper search
  fallback, and it logs a warning (once per breaker opening) and tags the event `engine=odoo_fallback`.
- Shoppers never see stack traces. Backend users get `UserError` with an actionable message for validation problems.
- CLI commands exit with a non-zero code on failure and print what to do next.

```python
try:
    hits = es_search(query, timeout=settings.search_timeout)
except SearchUnavailable as error:
    breaker.record_failure()
    _logger.warning("shop search fallback to Odoo native search: %s (search_id=%s)", error, search_id)
    return super()._shop_lookup(...)  # placeholder name: use the real 19.0 method
```

## 10. Logging

- Odoo: `_logger = logging.getLogger(__name__)`. Tools: standard `logging` with the run ID in every record.
- Include identifiers that help debugging: `search_id`, `event_id`, `run_id`, batch sizes, durations, `took_ms`.
- Never log: passwords, API keys, Kaggle tokens, raw session IDs, full event payloads, full queries in bulk.
- Levels mean something: `error` needs action, `warning` = degraded but handled, `info` = milestones (job finished, rebuild done),
  `debug` = local investigation only.

## 11. Security and privacy

- Secrets come from the environment, are validated at startup, and never reach templates, the browser or logs.
- Controller parameters are validated: `sid` must be a UUID, `pos` a small positive integer, queries capped at 200 characters
  and stripped of control characters.
- QWeb: escaped output only for anything derived from user input (never mark user input as safe HTML).
- POST routes keep Odoo's CSRF protection.
- Header-based switches (`engine`, `traffic`, `run_id`) are honored only with the correct load-test key.
- Mask email-like and phone-like patterns in stored queries. Keep events free of personal data (`01` §9).

## 12. Comments and naming

Comments explain **why**, not what.

Good:

```python
# Shop routes may run on a read-only cursor in 19.0, so search events use a separate short-lived cursor.
```

Bad:

```python
# Loop over the events.
```

Use domain names: `normalize_query`, `build_tuned_search_query`, `flush_event_outbox`, `detect_zero_result_queries`,
`propose_restock`, `rebuild_product_index`. Avoid `process_data`, `helper2`, `utils.py` dumping grounds, `manager`.
Glossary of domain terms: `docs/glossary.md` (lost demand, zero-result search, unsatisfied search, normalized query,
restock proposal, asked-for entry, outbox, alias swap, traffic type, run).

## 13. File responsibility

Split files by responsibility. Do not keep a 1,000-line file because it works.
Do not create 50 tiny files because abstraction feels professional.
Split when it makes a boundary clearer, testable, reusable, or substantially easier to debug.

## 14. State handling

Represent important states explicitly, with allowed transitions tested:

```text
proposal:     draft -> approved -> ordered ; draft -> dismissed
asked_for:    new -> handled | ignored ; handled -> new (if the problem comes back)
signal:       active -> resolved (when the condition disappears for a full window)
outbox row:   pending -> (sent = deleted) ; pending -> failed (attempts >= max, kept for inspection)
run:          running -> done | failed
breaker:      closed -> open (after N failures) -> half_open (after cooldown) -> closed | open
```

## 15. Performance

Avoid: N+1 queries, reading all products to reindex one, unbounded result sets, Elasticsearch calls inside loops,
synchronous network calls in shopper requests (other than the one search call), loading datasets into memory,
Kibana panels over unbounded time ranges. Measure before optimizing; budgets are in `01` §14.

## 16. Dependency discipline

Before adding a dependency (Python package, Odoo module, Docker image, Kibana plugin):

1. check whether Odoo, Elasticsearch, the standard library or an existing dependency already does it;
2. verify it is maintained, has a compatible license, and works with the pinned versions;
3. prefer mature focused libraries; no package for a five-line helper;
4. state the reason in the plan; add it to the right `uv` dependency group or to the Odoo image with a pinned version.

The Odoo image gets only what the module needs at runtime (the Elasticsearch client). Data science libraries stay on the host.

## 17. Tests

Tests protect behavior, not implementation details. Priorities:

- fallback when Elasticsearch is down or slow (shop still answers);
- no event lost or duplicated across retries; no event written when an order is not confirmed;
- index freshness and correctness after create/update/unpublish/stock changes;
- access rights for buyer / manager / administrator / public;
- query normalization and PII masking;
- lost-demand detection on crafted event sets (known answer);
- proposal and RFQ creation (draft only, grouped by vendor, no duplicates);
- metrics implementation (NDCG known values);
- determinism of the slice builder (same seed → same hash);
- REES46 mapping to the canonical schema.

For every meaningful feature, ask:

```text
What can a wrong implementation silently lose, duplicate, mis-rank, mis-measure or expose?
```

Cover those failure modes first.

## 18. Simplicity review (before every task report)

- Can another developer understand it quickly? Is the control flow obvious?
- Is every abstraction necessary?
- What happens if Elasticsearch is down? Slow? Returns an error for some documents?
- Can an event or an index update be lost? Duplicated? Arrive late?
- Does it still work with 10 million events? With 20,000 products? On an 8 GB laptop?
- Did I override Odoo correctly (read the 19.0 source, called `super()`, kept access rules)?
- Is any secret or personal data reachable in code, logs, events or the browser?
- Is the result reproducible from a committed script, a seed and recorded versions?
- Is there an easy way to reproduce a failure?

If two approaches are equally robust, use the simpler one.
