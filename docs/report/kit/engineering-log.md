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
