# Engineering log: problems met, causes, fixes, lessons

Newest task last. M1 and M2 problems are in the milestone notes' "Problems met" tables
([M1](../notes/M1.md), [M2](../notes/M2.md)); the most instructive ones are repeated here in one line each so the
report can tell the story of the project in one place.

## Before M3 (summary)

| Task | Problem | Cause | Fix | Lesson |
|---|---|---|---|---|
| 1.1 | A blank `admin/admin` database appeared at every start | `db_name` in `odoo.conf` makes Odoo 19 create it | `db_name` removed, `dbfilter` kept | read the server's start-up code, not only its docs |
| 1.3 | Settings page took 7.7 s with Elasticsearch stopped | the DNS lookup of a stopped container takes 8 s and the client timeout does not cover it | every call in a thread pool with a hard deadline: 2.09 s | a timeout is only as good as the steps it covers |
| 2.3b | Hiding single "Exact" products would make the lost-demand recall ≈ 3 % by construction | most E products are E for one query only | protocol v1.1 (B2): hide all E products of 20 % of the queries | measure the protocol on the data before using it |
| 2.4b | Applying an unchanged stock quantity still created a move | `action_apply_inventory` always moves | adjust only differing products | idempotent imports must compare before writing |

## M3 — Task 3.1 (product index, full rebuild)

| Problem | Cause | Fix | Lesson |
|---|---|---|---|
| An index that points to a missing synonyms set is unusable | Elasticsearch resolves the set when the index is created | the rebuild creates the set first, and never overwrites it | order of creation is part of the design |

## M3 — Task 3.2 (incremental sync, FR1)

Found during the design review (before code), then confirmed in the Odoo 19 source:

| Problem | Cause | Fix | Lesson |
|---|---|---|---|
| The index would say "in stock" for a product the shop shows as sold out | the shop uses the **free** quantity (on hand − reserved, website warehouse); the index used on-hand | index `free_qty`; reservations also trigger a sync; mapping version 2 | index what the user sees, computed the way the application computes it |
| Products that do not track stock would look "out of stock" | their quantity is always 0 | `in_stock` = free quantity > 0 **or** not stock-tracked (Odoo's `_is_sold_out` rule) | copy business rules from the source, including their exceptions |
| A sync write to a missing alias would create a plain index named like the alias | Elasticsearch auto-creates indices on write | bulk requests use `require_alias=true` (verified on the cluster) | defaults that "help" can break invariants (alias = only door) |
| A failing sync job could be switched off by Odoo | Odoo deactivates a cron job after 5 failures over 7 days | the job never raises for an Elasticsearch problem: it logs, rows wait | read how the framework treats failure before choosing to raise |
| A full rebuild could silently lose a change the sync had just sent | Odoo transactions are REPEATABLE READ: the rebuild could read with a snapshot older than the sync's last commit, then the alias swap drops the sync's write | the rebuild takes a PostgreSQL advisory lock on its own cursor, then reads on a *new* cursor; the sync skips while the lock is held; waiting rows go to the new index after the swap | isolation level decides correctness, not just locking |
| After a mapping change, every sync write would be refused one by one | the index behind the alias still has the old mapping | mapping `_meta.definition_version`; the sync waits ("rebuild needed") instead of failing | version the schema the code writes to |

Found by the tests:

| Problem | Cause | Fix | Lesson |
|---|---|---|---|
| 12 module tests errored on the first run; the outbox's own searches started the sync job | the job's method was called `_flush`, which overrides the ORM's `BaseModel._flush()` | renamed `_send_to_index` | check new method names against the framework's base classes |
| `env.flush_model` does not exist | in 19.0 `flush_model` is a model method | `self.flush_model([...])` | never trust remembered APIs (project rule) |

## M3 — Task 3.3 (shop search through Elasticsearch, with fallback)

Found during the two design reviews (before code), by reading the Odoo 19 source and by trying the planned
queries on the real index (read-only, as `shop_tools`, 2026-11-20; observations, not protocol results):

| Problem | Cause | Fix | Lesson |
|---|---|---|---|
| A typo query would show products but an empty category list and no attribute filters | `shop()` builds those from `_get_shop_domain()`, which still matched Odoo's words | override `_get_shop_domain()` too: Odoo's filters without the words, limited to the products found | follow every use of the data you replace, not only the main call |
| With at most 1,000 hits, a category page could miss products of that category ranked lower | the category was only filtered by Odoo, after the cut | the selected category and its subcategories are also filtered in Elasticsearch | filter before cutting, re-check after |
| Pushing the price filter into Elasticsearch would shrink the price slider to the current selection | Odoo computes the slider's range from all matches, ignoring the price filter | price, tags and attributes stay Odoo-only filters | mirror the framework's semantics, not just its results |
| A slow sync job could make shoppers' searches queue | one worker pool of 4 threads served both background jobs and shopper calls | shopper searches got their own 8-thread pool | isolate the latency-critical path |
| The first search after Elasticsearch starts can miss the 500 ms deadline (518 ms measured, cold caches) | caches are empty at start; warm searches took 30–150 ms | accepted: one fallback, the circuit needs 3 failures to open | measure cold and warm paths separately |
| Typo tolerance (`fuzziness: AUTO`) matches far more products ("windex": 36 → 3,018) | each word may differ by up to 2 letters | top results stay right; totals are capped at 1,000; `minimum_should_match` etc. are Task 3.5 experiments | a recall gain has a precision cost: measure it (NDCG) |
| Odoo's search finds a product by its internal reference; the Elasticsearch engines do not | `ref` is indexed but not among the searched fields | left for Task 3.5 (one change at a time); ESCI queries never contain references | list functional gaps, don't hide them |

Found by the tests:

| Problem | Cause | Fix | Lesson |
|---|---|---|---|
| The category-page test saw no product, though the page listed them | on a category page Odoo 19 links a product as `/shop/<category>/<product>` (`product_template.py:1117`, `_get_product_url`); the page parser expected `/shop/<product>` | the test parser accepts both forms. The baseline harness parses only `/shop?search=` pages (no category), so its results are unaffected; the Task 3.4 harness must accept both | check a test's own parser against the real markup when it says "nothing" |
