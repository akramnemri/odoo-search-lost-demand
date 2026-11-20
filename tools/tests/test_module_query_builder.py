"""Host tests of addons/website_sale_lost_demand/services/query_builder.py (pure functions, no Elasticsearch).

The full bodies of the three engines are pinned (snapshot tests, docs/ai/02_CODING_STANDARDS.md §3): any
change to a query must change these tests too, which makes it visible in review and in the experiment log.
"""

from __future__ import annotations

import pytest

from services.query_builder import (
    DEFAULT_ENGINE,
    ES_PLAIN,
    ES_TUNED,
    ES_TUNED_STOCK,
    MAX_QUERY_CHARS,
    ODOO,
    MalformedResponse,
    SearchFilters,
    build_search,
    clean_query,
    hit_ids,
)

FILTERS = SearchFilters(website_id=1)
SHOP_FILTERS = [
    {"term": {"published": True}},
    {
        "bool": {
            "should": [
                {"bool": {"must_not": {"exists": {"field": "website_ids"}}}},
                {"term": {"website_ids": 1}},
            ],
            "minimum_should_match": 1,
        }
    },
]
TUNED_MATCH = {
    "multi_match": {
        "query": "royal blue bedspread",
        "fields": ["name^3", "brand^2", "description"],
        "type": "best_fields",
        "fuzziness": "AUTO",
        "prefix_length": 1,
    }
}


def test_plain_engine_is_elasticsearch_out_of_the_box() -> None:
    assert build_search(ES_PLAIN, "royal blue bedspread", FILTERS, 1000) == {
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": "royal blue bedspread",
                            "fields": ["name.std", "description.std", "brand.std"],
                        }
                    }
                ],
                "filter": SHOP_FILTERS,
            }
        },
        "sort": ["_score", {"template_id": "asc"}],
        "size": 1000,
        "_source": False,
        "track_total_hits": False,
    }


def test_tuned_engine_v0() -> None:
    assert build_search(ES_TUNED, "royal blue bedspread", FILTERS, 50) == {
        "query": {"bool": {"must": [TUNED_MATCH], "filter": SHOP_FILTERS}},
        "sort": ["_score", {"template_id": "asc"}],
        "size": 50,
        "_source": False,
        "track_total_hits": False,
    }


def test_stock_engine_puts_in_stock_products_first_then_score() -> None:
    body = build_search(ES_TUNED_STOCK, "royal blue bedspread", FILTERS, 50)

    assert body["query"] == {"bool": {"must": [TUNED_MATCH], "filter": SHOP_FILTERS}}
    assert body["sort"] == [{"in_stock": "desc"}, "_score", {"template_id": "asc"}]


def test_default_engine_is_the_stock_rule() -> None:
    assert DEFAULT_ENGINE == ES_TUNED_STOCK


def test_category_filter_lists_each_category_once_in_order() -> None:
    body = build_search(ES_PLAIN, "shoes", SearchFilters(website_id=2, category_ids=(9, 4, 9)), 10)

    filters = body["query"]["bool"]["filter"]
    assert filters[-1] == {"terms": {"category_ids": [4, 9]}}
    assert filters[1]["bool"]["should"][1] == {"term": {"website_ids": 2}}


@pytest.mark.parametrize(("engine", "text"), [(ODOO, "shoes"), ("es_magic", "shoes"), (ES_PLAIN, "")])
def test_refuses_what_it_cannot_send(engine: str, text: str) -> None:
    with pytest.raises(ValueError):
        build_search(engine, text, FILTERS, 10)


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        (None, ""),
        ("   ", ""),
        ("  royal   blue\tbedspread ", "royal blue bedspread"),
        ("usb\x00c\x1bcable", "usb c cable"),  # control characters
        ("zero​width", "zero width"),  # format character
        ("café crème", "café crème"),  # letters with accents are kept
    ],
)
def test_clean_query(raw: str | None, cleaned: str) -> None:
    assert clean_query(raw) == cleaned


def test_clean_query_caps_the_length() -> None:
    cleaned = clean_query("a" * 150 + " " + "b" * 150)

    assert len(cleaned) == MAX_QUERY_CHARS
    assert cleaned == "a" * 150 + " " + "b" * 49


def test_hit_ids_keep_the_order_and_drop_repeats() -> None:
    response = {"took": 3, "hits": {"hits": [{"_id": "12"}, {"_id": "7"}, {"_id": "12"}, {"_id": "30"}]}}

    assert hit_ids(response) == [12, 7, 30]


def test_hit_ids_of_no_hits() -> None:
    assert hit_ids({"hits": {"hits": []}}) == []


@pytest.mark.parametrize(
    "response",
    [{}, {"hits": {}}, {"hits": {"hits": [{"_index": "x"}]}}, {"hits": {"hits": [{"_id": "abc"}]}}],
)
def test_hit_ids_refuse_an_odd_answer(response: dict) -> None:
    with pytest.raises(MalformedResponse):
        hit_ids(response)
