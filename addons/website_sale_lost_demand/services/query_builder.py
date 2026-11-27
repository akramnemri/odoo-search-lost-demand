"""Shop search queries for Elasticsearch, as pure functions (docs/ai/04_DATA_SEARCH_EVALUATION.md §6).

The engines (names shared with the evaluation protocol, docs/evaluation/protocol.md §6.2):

- `es_plain` — "Elasticsearch out of the box": `multi_match` with default parameters over the
  standard-analyzer subfields `name.std`, `description.std`, `brand.std`; no fuzziness, synonyms, boosts or
  stock rule.
- `es_tuned` — the shop analyzers of the index (English stemming, synonyms set) with the settings of a
  `TunedConfig`. `TUNED_V0` (Task 3.3, not tuned): `name`, `brand`, `description` with weights 3 / 2 / 1 and
  typo tolerance (`fuzziness: AUTO`, first letter exact). Task 3.5 measures variants of it on the dev queries
  (`uv run shop eval tune`, tools/shoptools/eval/tuning.toml); `TUNED` is the configuration the shop uses.
- `es_tuned_stock` — `es_tuned` with the in-stock rule of FR3. Implementation (a) "tiered", applied to the
  most relevant hits only: Elasticsearch returns the `size` best-scored products, then every in-stock one
  among them comes before every sold-out one, by score within each group (`hit_ids(in_stock_first=True)`).
  The shop's default engine. Cut first, then the stock rule (supervisor's option A, 2026-11-20): sorting by
  stock inside Elasticsearch before the cut let thousands of weak in-stock matches push a sold-out exact
  match out of the results entirely (manual test of Task 3.3). Implementation (b) "boosted" (measured in
  Task 3.5): the score of an in-stock product is multiplied by `stock_factor` (scale-free: scores vary by
  query, roughly 25-50 for the top hits).

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
MATCH_TYPES = ("best_fields", "most_fields", "cross_fields")
TIERED, BOOSTED = "tiered", "boosted"
STOCK_RULES = (TIERED, BOOSTED)


class MalformedResponse(ValueError):
    """Elasticsearch answered, but not with the shape of a search response."""


@dataclass(frozen=True)
class TunedConfig:
    """The settings of the `es_tuned` query (and of `es_tuned_stock`, which adds the stock rule).

    Each field is one lever of docs/ai/04_DATA_SEARCH_EVALUATION.md §6; None leaves the lever out.
    """

    fields: tuple[str, ...] = TUNED_FIELDS  # analysed fields with their weights (`field^weight`)
    match_type: str = "best_fields"  # multi_match type: best_fields, most_fields or cross_fields
    fuzziness: str | None = "AUTO"  # typo tolerance; None: exact words only (required by cross_fields)
    prefix_length: int = 1  # first letters that must be exact when fuzziness is on
    tie_breaker: float | None = None  # best_fields: share of the other fields' scores added (0 to 1)
    minimum_should_match: str | None = None  # how many query words must match, e.g. "2<75%"
    name_phrase_boost: float | None = None  # extra score when the words appear together in the name
    ref_exact_boost: float | None = None  # a query equal to a product's internal reference finds it
    stock_rule: str = TIERED  # es_tuned_stock only: tiered (a) or boosted (b)
    stock_factor: float = 1.0  # boosted rule: in-stock scores are multiplied by this

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("at least one field")
        if self.match_type not in MATCH_TYPES:
            raise ValueError(f"match_type must be one of {MATCH_TYPES}")
        if self.match_type == "cross_fields" and self.fuzziness is not None:
            raise ValueError("cross_fields does not support fuzziness: set fuzziness to None")
        if self.prefix_length < 0:
            raise ValueError("prefix_length must be >= 0")
        if self.tie_breaker is not None and not 0 <= self.tie_breaker <= 1:
            raise ValueError("tie_breaker must be between 0 and 1")
        if self.stock_rule not in STOCK_RULES:
            raise ValueError(f"stock_rule must be one of {STOCK_RULES}")
        if self.stock_factor <= 0:
            raise ValueError("stock_factor must be positive")
        for boost in (self.name_phrase_boost, self.ref_exact_boost):
            if boost is not None and boost <= 0:
                raise ValueError("boosts must be positive")


TUNED_V0 = TunedConfig()
# The configuration the shop uses. Task 3.5 replaces it with the one chosen on the dev queries (ADR-020).
TUNED = TUNED_V0


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


def _tuned_match(text: str, tuned: TunedConfig) -> dict[str, Any]:
    multi_match: dict[str, Any] = {"query": text, "fields": list(tuned.fields), "type": tuned.match_type}
    if tuned.fuzziness is not None:
        multi_match["fuzziness"] = tuned.fuzziness
        multi_match["prefix_length"] = tuned.prefix_length
    if tuned.tie_breaker is not None:
        multi_match["tie_breaker"] = tuned.tie_breaker
    if tuned.minimum_should_match is not None:
        multi_match["minimum_should_match"] = tuned.minimum_should_match
    match = {"multi_match": multi_match}
    if tuned.ref_exact_boost is None:
        return match
    # Either the words match, or the whole query is a product's internal reference (Odoo's own search finds a
    # product by its reference; `ref` is a keyword field, compared without case).
    reference = {"term": {"ref": {"value": text, "case_insensitive": True, "boost": tuned.ref_exact_boost}}}
    return {"bool": {"should": [match, reference], "minimum_should_match": 1}}


def _query(engine: str, text: str, filters: SearchFilters, tuned: TunedConfig) -> dict[str, Any]:
    if engine == ES_PLAIN:
        plain = {"multi_match": {"query": text, "fields": list(PLAIN_FIELDS)}}
        return {"bool": {"must": [plain], "filter": _filters(filters)}}
    query: dict[str, Any] = {"bool": {"must": [_tuned_match(text, tuned)], "filter": _filters(filters)}}
    if tuned.name_phrase_boost is not None:
        query["bool"]["should"] = [
            {"match_phrase": {"name": {"query": text, "boost": tuned.name_phrase_boost}}}
        ]
    if engine == ES_TUNED_STOCK and tuned.stock_rule == BOOSTED:
        return {
            "function_score": {
                "query": query,
                "functions": [{"filter": {"term": {"in_stock": True}}, "weight": tuned.stock_factor}],
                "score_mode": "multiply",
                "boost_mode": "multiply",
            }
        }
    return query


def build_search(
    engine: str, text: str, filters: SearchFilters, size: int, tuned: TunedConfig | None = None
) -> dict[str, Any]:
    """The `_search` body of one shop search. `text` must already be cleaned (`clean_query`) and not empty.
    `tuned` replaces the shop's configuration (`TUNED`) for the evaluation only."""
    if engine not in ES_ENGINES:
        raise ValueError(f"not an Elasticsearch engine: {engine!r}")
    if not text:
        raise ValueError("empty query: the shop lists products without Elasticsearch")
    tuned = tuned or TUNED
    body: dict[str, Any] = {
        "query": _query(engine, text, filters, tuned),
        "sort": ["_score", {"template_id": "asc"}],
        "size": size,
        "_source": False,
        "track_total_hits": False,
    }
    if stock_first(engine, tuned):
        body["docvalue_fields"] = ["in_stock"]  # read from doc values: no `_source` needed
    return body


def stock_first(engine: str, tuned: TunedConfig | None = None) -> bool:
    """True when the engine puts in-stock products first among its hits after the cut (FR3, rule (a))."""
    return engine == ES_TUNED_STOCK and (tuned or TUNED).stock_rule == TIERED


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
