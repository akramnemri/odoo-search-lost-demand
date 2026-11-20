"""Shop search queries for Elasticsearch, as pure functions (docs/ai/04_DATA_SEARCH_EVALUATION.md §6).

The engines (names shared with the evaluation protocol, docs/evaluation/protocol.md §6.2):

- `es_plain` — "Elasticsearch out of the box": `multi_match` with default parameters over the
  standard-analyzer subfields `name.std`, `description.std`, `brand.std`; no fuzziness, synonyms, boosts or
  stock rule.
- `es_tuned` — version 0, NOT tuned yet: the shop analyzers of the index (English stemming, synonyms set) on
  `name`, `brand`, `description` with weights 3 / 2 / 1 and typo tolerance (`fuzziness: AUTO`, first letter
  exact). It is the starting point of Task 3.5, which changes it one measured step at a time on dev queries.
- `es_tuned_stock` — `es_tuned` with the in-stock rule of FR3, implementation (a) "tiered", applied to the
  most relevant hits only: Elasticsearch returns the `size` best-scored products, then every in-stock one
  among them comes before every sold-out one, by score within each group (`hit_ids(in_stock_first=True)`).
  The shop's default engine. Cut first, then the stock rule (supervisor's option A, 2026-11-20): sorting by
  stock inside Elasticsearch before the cut let thousands of weak in-stock matches push a sold-out exact
  match out of the results entirely (manual test of Task 3.3).

Every engine applies the same filters: published products of the current website (a product without a
website is on every website), and the selected category with its subcategories. Odoo filters the hits again
with its own rules (controllers/main.py), so these filters only make the hits relevant, never decide access.

Ties are broken by template ID, so the same index answers the same query with the same order (reproducible
evaluation runs). Only document IDs are returned (`_source: false`), and no total is counted: the shop counts
the hits Odoo keeps.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ODOO = "odoo"
ES_PLAIN = "es_plain"
ES_TUNED = "es_tuned"
ES_TUNED_STOCK = "es_tuned_stock"
ES_ENGINES = (ES_PLAIN, ES_TUNED, ES_TUNED_STOCK)
ENGINES = (ODOO, *ES_ENGINES)
DEFAULT_ENGINE = ES_TUNED_STOCK

MAX_QUERY_CHARS = 200  # docs/ai/02_CODING_STANDARDS.md §11

PLAIN_FIELDS = ("name.std", "description.std", "brand.std")
TUNED_FIELDS = ("name^3", "brand^2", "description")


class MalformedResponse(ValueError):
    """Elasticsearch answered, but not with the shape of a search response."""


@dataclass(frozen=True)
class SearchFilters:
    website_id: int
    # The selected category and its subcategories; empty: no category filter.
    category_ids: tuple[int, ...] = ()


def clean_query(text: str | None) -> str:
    """The query sent to Elasticsearch: control and format characters removed, whitespace collapsed, at most
    200 characters. Odoo's own search, used on fallback, still receives the query as the shopper typed it."""
    kept = "".join(
        " " if unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") else char for char in text or ""
    )
    return " ".join(kept.split())[:MAX_QUERY_CHARS].strip()


def _filters(filters: SearchFilters) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = [
        {"term": {"published": True}},
        {
            "bool": {
                "should": [
                    {"bool": {"must_not": {"exists": {"field": "website_ids"}}}},
                    {"term": {"website_ids": filters.website_id}},
                ],
                "minimum_should_match": 1,
            }
        },
    ]
    if filters.category_ids:
        clauses.append({"terms": {"category_ids": sorted(set(filters.category_ids))}})
    return clauses


def _match(engine: str, text: str) -> dict[str, Any]:
    if engine == ES_PLAIN:
        return {"multi_match": {"query": text, "fields": list(PLAIN_FIELDS)}}
    return {
        "multi_match": {
            "query": text,
            "fields": list(TUNED_FIELDS),
            "type": "best_fields",
            "fuzziness": "AUTO",
            "prefix_length": 1,
        }
    }


def build_search(engine: str, text: str, filters: SearchFilters, size: int) -> dict[str, Any]:
    """The `_search` body of one shop search. `text` must already be cleaned (`clean_query`) and not empty."""
    if engine not in ES_ENGINES:
        raise ValueError(f"not an Elasticsearch engine: {engine!r}")
    if not text:
        raise ValueError("empty query: the shop lists products without Elasticsearch")
    body: dict[str, Any] = {
        "query": {"bool": {"must": [_match(engine, text)], "filter": _filters(filters)}},
        "sort": ["_score", {"template_id": "asc"}],
        "size": size,
        "_source": False,
        "track_total_hits": False,
    }
    if stock_first(engine):
        body["docvalue_fields"] = ["in_stock"]  # read from doc values: no `_source` needed
    return body


def stock_first(engine: str) -> bool:
    """True when the engine puts in-stock products first among its hits (FR3)."""
    return engine == ES_TUNED_STOCK


def hit_ids(response: Mapping[str, Any], in_stock_first: bool = False) -> list[int]:
    """Template IDs in Elasticsearch's order, or with `in_stock_first` every in-stock hit before every
    sold-out one (each group keeps Elasticsearch's order); raise MalformedResponse on anything unexpected."""
    try:
        hits: Sequence[Mapping[str, Any]] = response["hits"]["hits"]
        ranked = [(int(hit["_id"]), _in_stock(hit) if in_stock_first else True) for hit in hits]
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise MalformedResponse(f"unexpected search response: {type(error).__name__}") from error
    ids = [template_id for template_id, in_stock in ranked if in_stock]
    ids += [template_id for template_id, in_stock in ranked if not in_stock]
    return list(dict.fromkeys(ids))  # an ID appears once even if two indices answered (never expected)


def _in_stock(hit: Mapping[str, Any]) -> bool:
    value = hit["fields"]["in_stock"][0]
    if not isinstance(value, bool):
        raise ValueError("in_stock is not a boolean")
    return value
