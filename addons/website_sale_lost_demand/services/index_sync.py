"""Incremental product sync (Task 3.2, FR1): send changed products to the index behind the alias.

Pure Python, no `odoo` import: the Odoo glue (models/index_queue.py) reads the outbox and the products, and
calls `send_changes()` with the raw Elasticsearch client; host tests use a fake client.

Design (docs/ai/01_ARCHITECTURE.md §8, §13):
- one bulk request per batch: an `index` action for every product the shop indexes, a `delete` action for
  every product it no longer indexes (deleted, archived, not for sale). The document ID is the template ID,
  so sending the same product twice is harmless;
- `require_alias=true`: writes go to the alias only. Without it, a write to a missing alias would create a
  plain index called `shop-products` with guessed field types, and the alias could never be created again;
- a refused item is retried later with a growing delay (`retry_delay`); the other items of the batch are
  done. A request that fails as a whole (cluster down, timeout) changes nothing: every row waits.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .product_index import (
    PRODUCTS,
    IndexDefinition,
    IndexNames,
    _body,
    alias_holders,
    bulk_item_errors,
    definition_version_of,
    existing_indices,
)

FIRST_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 3600
# After this many refusals a row is shown as failing (settings page, doctor). It is kept and still retried
# every MAX_RETRY_SECONDS: a change is never dropped silently.
FAILING_AFTER_ATTEMPTS = 10


def retry_delay(attempts: int) -> int:
    """Seconds before the next try of a row refused `attempts` times: 30 s, 60 s, 120 s, ... at most 1 h."""
    if attempts < 1:
        return 0
    return min(FIRST_RETRY_SECONDS * 2 ** (attempts - 1), MAX_RETRY_SECONDS)


def sync_operations(
    alias: str, documents: Iterable[Mapping[str, Any]], deletions: Iterable[int]
) -> list[Mapping[str, Any]]:
    """Bulk body: `index` for each document, then `delete` for each template ID no longer indexed."""
    operations: list[Mapping[str, Any]] = []
    for document in documents:
        operations.append({"index": {"_index": alias, "_id": str(document["template_id"])}})
        operations.append(document)
    for template_id in deletions:
        operations.append({"delete": {"_index": alias, "_id": str(template_id)}})
    return operations


@dataclass
class SyncOutcome:
    """Template IDs the index now reflects, and the refused ones with Elasticsearch's reason."""

    done: set[int] = field(default_factory=set)
    failed: dict[int, str] = field(default_factory=dict)


def send_changes(
    client: Any,
    documents: Sequence[Mapping[str, Any]],
    deletions: Sequence[int],
    names: IndexNames = PRODUCTS,
) -> SyncOutcome:
    """One bulk request through the alias. Client errors (cluster down, timeout) propagate to the caller."""
    template_ids = [int(document["template_id"]) for document in documents] + [int(i) for i in deletions]
    if not template_ids:
        return SyncOutcome()
    response = _body(
        client.bulk(operations=sync_operations(names.alias, documents, deletions), require_alias=True)
    )
    errors = bulk_item_errors(response)
    outcome = SyncOutcome()
    for template_id in template_ids:
        error = errors.get(str(template_id))
        if error is None:
            outcome.done.add(template_id)
        else:
            outcome.failed[template_id] = error
    return outcome


def index_not_ready(client: Any, definition: IndexDefinition, names: IndexNames = PRODUCTS) -> str:
    """Why changes cannot be sent now ("" when they can): no alias yet, or an index of an older definition."""
    holders = alias_holders(existing_indices(client, names), names)
    if not holders:
        return f"no index behind the alias {names.alias} yet: rebuild the product index"
    if len(holders) > 1:
        return f"the alias {names.alias} points to {len(holders)} indices: rebuild the product index"
    version = definition_version_of(client, holders[0])
    if version != definition.version:
        return (
            f"{holders[0]} was built from index definition {version or 1}, the module has "
            f"{definition.version}: rebuild the product index"
        )
    return ""
