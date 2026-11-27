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
    stock_first,
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

# TUNED_V1 (Task 3.5, ADR-020): v0 + tie_breaker 0.3, either the words or the internal reference.
V1_MATCH = {
    "bool": {
        "should": [
            {"multi_match": {**TUNED_MATCH["multi_match"], "tie_breaker": 0.3}},
            {"term": {"ref": {"value": "royal blue bedspread", "case_insensitive": True, "boost": 10.0}}},
        ],
        "minimum_should_match": 1,
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
    from services.query_builder import TUNED_V0

    assert build_search(ES_TUNED, "royal blue bedspread", FILTERS, 50, tuned=TUNED_V0) == {
        "query": {"bool": {"must": [TUNED_MATCH], "filter": SHOP_FILTERS}},
        "sort": ["_score", {"template_id": "asc"}],
        "size": 50,
        "_source": False,
        "track_total_hits": False,
    }


def test_tuned_engine_v1_is_the_shops() -> None:
    assert build_search(ES_TUNED, "royal blue bedspread", FILTERS, 50) == {
        "query": {"bool": {"must": [V1_MATCH], "filter": SHOP_FILTERS}},
        "sort": ["_score", {"template_id": "asc"}],
        "size": 50,
        "_source": False,
        "track_total_hits": False,
    }


def test_stock_engine_cuts_by_score_and_reads_the_stock_flag() -> None:
    """Option A (2026-11-20): Elasticsearch ranks by score only; the stock rule applies after the cut."""
    assert build_search(ES_TUNED_STOCK, "royal blue bedspread", FILTERS, 50) == {
        "query": {"bool": {"must": [V1_MATCH], "filter": SHOP_FILTERS}},
        "sort": ["_score", {"template_id": "asc"}],
        "size": 50,
        "_source": False,
        "track_total_hits": False,
        "docvalue_fields": ["in_stock"],
    }
    assert stock_first(ES_TUNED_STOCK)
    assert not stock_first(ES_TUNED)
    assert not stock_first(ES_PLAIN)


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


def _hit(template_id: int, in_stock: bool) -> dict:
    return {"_id": str(template_id), "fields": {"in_stock": [in_stock]}}


def test_in_stock_first_keeps_the_score_order_within_each_group() -> None:
    response = {"hits": {"hits": [_hit(35, False), _hit(7, True), _hit(9, False), _hit(2, True)]}}

    assert hit_ids(response, in_stock_first=True) == [7, 2, 35, 9]
    assert hit_ids(response) == [35, 7, 9, 2]  # without the rule: Elasticsearch's order


@pytest.mark.parametrize(
    "hit",
    [
        {"_id": "1"},
        {"_id": "1", "fields": {}},
        {"_id": "1", "fields": {"in_stock": []}},
        {"_id": "1", "fields": {"in_stock": ["yes"]}},
    ],
)
def test_in_stock_first_refuses_a_hit_without_the_flag(hit: dict) -> None:
    with pytest.raises(MalformedResponse):
        hit_ids({"hits": {"hits": [hit]}}, in_stock_first=True)


# --- TunedConfig: the levers of Task 3.5 ---


def _tuned_body(**changes: object) -> dict:
    from dataclasses import replace

    from services.query_builder import TUNED_V0

    return build_search(ES_TUNED, "blue lamp", FILTERS, 10, tuned=replace(TUNED_V0, **changes))


def test_v1_is_v0_with_the_two_kept_changes() -> None:
    from dataclasses import replace

    from services.query_builder import TUNED, TUNED_V0, TUNED_V1

    assert TUNED == TUNED_V1 == replace(TUNED_V0, tie_breaker=0.3, ref_exact_boost=10.0)
    assert TUNED_V1.stock_rule == "tiered"  # rule (a) stays (experiments.md, stage 3)


def test_exact_words_leave_fuzziness_out() -> None:
    match = _tuned_body(fuzziness=None)["query"]["bool"]["must"][0]["multi_match"]

    assert "fuzziness" not in match and "prefix_length" not in match


def test_match_type_tie_breaker_and_minimum_words() -> None:
    match = _tuned_body(match_type="most_fields", tie_breaker=0.3, minimum_should_match="2<75%")["query"][
        "bool"
    ]["must"][0]["multi_match"]

    assert (match["type"], match["tie_breaker"], match["minimum_should_match"]) == (
        "most_fields",
        0.3,
        "2<75%",
    )


def test_name_phrase_bonus_is_optional_score() -> None:
    query = _tuned_body(name_phrase_boost=2.0)["query"]["bool"]

    assert query["should"] == [{"match_phrase": {"name": {"query": "blue lamp", "boost": 2.0}}}]
    assert "minimum_should_match" not in query  # the phrase only adds score, it is not required


def test_reference_match_is_an_alternative_to_the_words() -> None:
    core = _tuned_body(ref_exact_boost=10.0)["query"]["bool"]["must"][0]["bool"]

    assert core["minimum_should_match"] == 1
    assert core["should"][1] == {
        "term": {"ref": {"value": "blue lamp", "case_insensitive": True, "boost": 10.0}}
    }


def test_boosted_stock_rule_multiplies_in_stock_scores_and_keeps_elasticsearch_order() -> None:
    from dataclasses import replace

    from services.query_builder import BOOSTED, TUNED_V0

    tuned = replace(TUNED_V0, stock_rule=BOOSTED, stock_factor=1.5)
    body = build_search(ES_TUNED_STOCK, "blue lamp", FILTERS, 10, tuned=tuned)

    scored = body["query"]["function_score"]
    assert scored["functions"] == [{"filter": {"term": {"in_stock": True}}, "weight": 1.5}]
    assert (scored["score_mode"], scored["boost_mode"]) == ("multiply", "multiply")
    assert "docvalue_fields" not in body
    assert not stock_first(ES_TUNED_STOCK, tuned)
    # The boost belongs to the stock engine only.
    assert "function_score" not in build_search(ES_TUNED, "blue lamp", FILTERS, 10, tuned=tuned)["query"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"match_type": "cross_fields"}, "does not support fuzziness"),
        ({"match_type": "phrase"}, "match_type"),
        ({"fields": ()}, "at least one field"),
        ({"prefix_length": -1}, "prefix_length"),
        ({"tie_breaker": 1.5}, "tie_breaker"),
        ({"stock_rule": "random"}, "stock_rule"),
        ({"stock_factor": 0}, "stock_factor"),
        ({"name_phrase_boost": -1.0}, "boosts"),
    ],
)
def test_invalid_settings_are_refused(changes: dict, message: str) -> None:
    from dataclasses import replace

    from services.query_builder import TUNED_V0

    with pytest.raises(ValueError, match=message):
        replace(TUNED_V0, **changes)
