"""Product index (Task 3.1): its definition, the documents, and the full rebuild behind an alias.

Pure Python, no `odoo` import: the Odoo glue (models/product_index.py) reads the products and calls
`rebuild()` with the raw Elasticsearch client; host tests use a fake client.

Design (docs/ai/01_ARCHITECTURE.md §8, docs/ai/04_DATA_SEARCH_EVALUATION.md §5):
- settings, analyzers and mapping are files in `elastic/products/` of this module (the Odoo container
  mounts only `addons/`); the synonyms set `shop-synonyms` is created from `synonyms-seed.json` only when
  it is missing, so the rules managed later in Odoo (Task 3.6) are never overwritten;
- a rebuild loads every product into a new index `shop-products-v<N+1>`, checks the document count, then moves
  the alias `shop-products` to it in one atomic `_aliases` call. Previous indices are kept: only the
  supervisor deletes indices. When anything fails before the swap, the alias stays where it was;
- `mappings.json` carries `_meta.definition_version`: the incremental sync (Task 3.2, services/index_sync.py)
  writes only into an index built from the current definition, otherwise its changes wait for a rebuild.
"""

from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SYNONYMS_SET = "shop-synonyms"
DEFINITION_DIR = Path(__file__).resolve().parent.parent / "elastic" / "products"
FAILURES_SHOWN = 3  # bulk errors quoted in a message; the rest are counted
SYNONYMS_SETS_PAGE = 1000  # GET _synonyms answers 10 sets by default


@dataclass(frozen=True)
class IndexNames:
    """The alias the shop reads, the prefix of its versioned indices, and the synonyms set they search with
    (tests use their own set, so they never change the shop's synonyms)."""

    alias: str
    prefix: str
    synonyms_set: str = SYNONYMS_SET

    def versioned(self, version: int) -> str:
        return f"{self.prefix}{version}"

    def version_of(self, index: str) -> int | None:
        match = re.fullmatch(re.escape(self.prefix) + r"(\d+)", index)
        return int(match.group(1)) if match else None


PRODUCTS = IndexNames(alias="shop-products", prefix="shop-products-v")


class RebuildError(Exception):
    """The rebuild stopped before the alias swap; the alias still points to the previous index."""


def _body(response: Any) -> Mapping[str, Any]:
    # As es_client._body: the real client returns ObjectApiResponse (JSON in `.body`); fakes return dicts.
    body = getattr(response, "body", response)
    return body if isinstance(body, Mapping) else {}


# --- definition ---


@dataclass(frozen=True)
class IndexDefinition:
    settings: dict[str, Any]
    mappings: dict[str, Any]
    synonyms_seed: list[dict[str, str]]

    @property
    def version(self) -> int:
        """`_meta.definition_version` of the mapping: raised whenever a field or analyzer changes."""
        return int(self.mappings["_meta"]["definition_version"])


def load_definition(folder: Path = DEFINITION_DIR) -> IndexDefinition:
    """Read the three JSON files; raise ValueError when they do not fit together."""

    def read(name: str) -> Any:
        return json.loads((folder / name).read_text(encoding="utf-8"))

    settings, mappings, seed = read("settings.json"), read("mappings.json"), read("synonyms-seed.json")
    filters = settings.get("analysis", {}).get("filter", {}).values()
    sets = {f.get("synonyms_set") for f in filters if f.get("type") in ("synonym", "synonym_graph")}
    if sets != {SYNONYMS_SET}:
        raise ValueError(
            f"settings.json must use the synonyms set {SYNONYMS_SET!r} only, found {sorted(sets)}"
        )
    if mappings.get("dynamic") != "strict":
        raise ValueError("mappings.json must be strict: an unknown field is a bug, not a new column")
    version = mappings.get("_meta", {}).get("definition_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("mappings.json needs a positive integer _meta.definition_version")
    if not isinstance(seed, list) or any(
        not isinstance(rule, dict) or not rule.get("id") or not rule.get("synonyms") for rule in seed
    ):
        raise ValueError('synonyms-seed.json must be a list of {"id": ..., "synonyms": ...} rules')
    return IndexDefinition(settings, mappings, seed)


# --- documents ---


@dataclass(frozen=True)
class ProductValues:
    """What the index needs from one product template, as plain Python (read by the Odoo glue)."""

    template_id: int
    name: str
    ref: str | None = None
    description: str | None = None
    brand: str | None = None
    categories: Sequence[tuple[int, str]] = ()
    price: float = 0.0
    # What the shop can still sell: on hand minus reserved, in the website's warehouse (website_sale_stock
    # `_get_product_available_qty`), summed over the variants. Products that do not track stock
    # (`is_storable=False`) are never sold out in the shop, whatever this says.
    free_qty: float = 0.0
    is_storable: bool = True
    published: bool = False
    website_id: int | None = None  # None: the product is on every website
    updated_at: datetime | None = None  # naive UTC, as Odoo stores it


def _text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def build_document(product: ProductValues) -> dict[str, Any]:
    """One index document. Empty texts are left out (a strict mapping accepts missing fields).

    `website_ids` is empty for a product shown on every website: shop queries match it with
    "no website_ids, or the current one" (Task 3.3).
    """
    document: dict[str, Any] = {
        "template_id": product.template_id,
        "name": product.name.strip(),
        "categories": [name for _, name in product.categories],
        "category_ids": [category_id for category_id, _ in product.categories],
        "price": round(product.price, 2),
        "free_qty": product.free_qty,
        # Same rule as website_sale_stock `_is_sold_out`: only stock-tracked products can be sold out.
        "in_stock": product.free_qty > 0 or not product.is_storable,
        "published": product.published,
        "website_ids": [product.website_id] if product.website_id else [],
    }
    for field, value in (
        ("ref", product.ref),
        ("description", product.description),
        ("brand", product.brand),
    ):
        text = _text(value)
        if text is not None:
            document[field] = text
    if product.updated_at is not None:
        document["updated_at"] = product.updated_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return document


def bulk_operations(index: str, documents: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Bulk body: one `index` action per document, the template ID as its ID (a rebuild is idempotent)."""
    operations: list[Mapping[str, Any]] = []
    for document in documents:
        operations.append({"index": {"_index": index, "_id": str(document["template_id"])}})
        operations.append(document)
    return operations


def bulk_item_errors(response: Mapping[str, Any]) -> dict[str, str]:
    """Document ID -> `<error type>: <reason>` for every refused item of a bulk response.

    A `delete` of a document that is not there answers 404 `not_found` without an `error`: not a failure.
    """
    if not response.get("errors"):
        return {}
    errors: dict[str, str] = {}
    for item in response.get("items", []):
        result = next(iter(item.values()), {})
        error = result.get("error")
        if error:
            reason = error.get("reason", "") if isinstance(error, Mapping) else str(error)
            kind = error.get("type", "error") if isinstance(error, Mapping) else "error"
            errors[str(result.get("_id"))] = f"{kind}: {reason}"
    return errors


def bulk_failures(response: Mapping[str, Any]) -> list[str]:
    """`<id>: <error type>: <reason>` for every refused item of a bulk response."""
    return [f"{doc_id}: {error}" for doc_id, error in bulk_item_errors(response).items()]


# --- indices and alias ---


def existing_indices(client: Any, names: IndexNames = PRODUCTS) -> dict[str, list[str]]:
    """Versioned indices of `names` and the aliases each one carries; no match is an empty answer."""
    body = _body(client.indices.get_alias(index=names.prefix + "*"))
    return {
        index: sorted((value or {}).get("aliases", {}))
        for index, value in body.items()
        if names.version_of(index) is not None
    }


def next_index(existing: Iterable[str], names: IndexNames = PRODUCTS) -> str:
    versions = [names.version_of(index) for index in existing]
    return names.versioned(max((v for v in versions if v is not None), default=0) + 1)


def alias_holders(indices: Mapping[str, Sequence[str]], names: IndexNames = PRODUCTS) -> list[str]:
    return sorted(index for index, aliases in indices.items() if names.alias in aliases)


def swap_actions(
    new_index: str, holders: Sequence[str], names: IndexNames = PRODUCTS
) -> list[dict[str, Any]]:
    """Remove the alias from every holder and add it to the new index: applied together, atomically."""
    actions: list[dict[str, Any]] = [
        {"remove": {"index": holder, "alias": names.alias}} for holder in holders if holder != new_index
    ]
    actions.append({"add": {"index": new_index, "alias": names.alias}})
    return actions


def ensure_synonyms_set(client: Any, seed: list[dict[str, str]], set_name: str = SYNONYMS_SET) -> bool:
    """Create the synonyms set from the seed when it is missing; True when created. Never overwrites: the
    rules themselves come from Odoo (`lost_demand.synonym`, Task 3.6), pushed by the sync job."""
    body = _body(client.synonyms.get_synonyms_sets(size=SYNONYMS_SETS_PAGE))
    if any(entry.get("synonyms_set") == set_name for entry in body.get("results", [])):
        return False
    client.synonyms.put_synonym(id=set_name, synonyms_set=seed)
    return True


def settings_for(settings: Mapping[str, Any], set_name: str) -> dict[str, Any]:
    """The index settings with the synonym filters pointing to `set_name` (the file names the shop's)."""
    copied = copy.deepcopy(dict(settings))
    for definition in copied.get("analysis", {}).get("filter", {}).values():
        if definition.get("type") in ("synonym", "synonym_graph"):
            definition["synonyms_set"] = set_name
    return copied


@dataclass(frozen=True)
class IndexStatus:
    """What the alias points to, for the settings page and the count check."""

    indices: tuple[str, ...] = ()  # normally one
    documents: int | None = None
    error: str = ""
    definition_version: int | None = None  # `_meta.definition_version` of the index behind the alias

    @property
    def exists(self) -> bool:
        return bool(self.indices)


def definition_version_of(client: Any, index: str) -> int | None:
    """The `_meta.definition_version` an index was built with; None for indices built before Task 3.2."""
    for value in _body(client.indices.get_mapping(index=index)).values():
        version = (value or {}).get("mappings", {}).get("_meta", {}).get("definition_version")
        return int(version) if isinstance(version, int) else None
    return None


def read_status(client: Any, names: IndexNames = PRODUCTS) -> IndexStatus:
    holders = alias_holders(existing_indices(client, names), names)
    if not holders:
        return IndexStatus()
    count = _body(client.count(index=names.alias)).get("count")
    version = definition_version_of(client, holders[0]) if len(holders) == 1 else None
    return IndexStatus(tuple(holders), int(count) if count is not None else None, "", version)


# --- rebuild ---


@dataclass(frozen=True)
class RebuildResult:
    index: str
    previous: tuple[str, ...]
    documents: int
    seconds: float
    synonyms_created: bool

    def summary(self, names: IndexNames = PRODUCTS) -> str:
        before = ", ".join(self.previous) if self.previous else "nothing"
        return (
            f"{self.documents:,} products indexed into {self.index} in {self.seconds:.0f} s; "
            f"alias {names.alias} moved from {before}."
        )


def rebuild(
    client: Any,
    definition: IndexDefinition,
    batches: Iterable[Sequence[ProductValues]],
    expected: int,
    names: IndexNames = PRODUCTS,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[[int], None] | None = None,
) -> RebuildResult:
    """Build `<prefix><N+1>` from `batches`, check it holds `expected` documents, then swap the alias.

    Raises RebuildError (alias untouched) when Elasticsearch refuses documents or the count differs; the
    half-built index is kept for inspection and the next rebuild takes the next version number.
    """
    started = clock()
    created = ensure_synonyms_set(client, definition.synonyms_seed, names.synonyms_set)
    indices = existing_indices(client, names)
    previous = tuple(alias_holders(indices, names))
    new_index = next_index(indices, names)
    settings = settings_for(definition.settings, names.synonyms_set)
    client.indices.create(index=new_index, settings=settings, mappings=definition.mappings)

    sent = 0
    for batch in batches:
        documents = [build_document(product) for product in batch]
        if not documents:
            continue
        failures = bulk_failures(_body(client.bulk(operations=bulk_operations(new_index, documents))))
        if failures:
            shown = "; ".join(failures[:FAILURES_SHOWN])
            raise RebuildError(
                f"Elasticsearch refused {len(failures)} products in {new_index} (first: {shown}). "
                f"The alias {names.alias} was not moved."
            )
        sent += len(documents)
        if progress is not None:
            progress(sent)

    client.indices.refresh(index=new_index)
    count = int(_body(client.count(index=new_index)).get("count", -1))
    if not count == sent == expected:
        raise RebuildError(
            f"{new_index} holds {count:,} documents, {sent:,} were sent and Odoo has {expected:,} products "
            f"to index (did products change during the rebuild?). The alias {names.alias} was not moved."
        )
    client.indices.update_aliases(actions=swap_actions(new_index, previous, names))
    return RebuildResult(new_index, previous, count, clock() - started, created)
