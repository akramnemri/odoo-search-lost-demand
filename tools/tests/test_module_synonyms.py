"""Host tests of addons/website_sale_lost_demand/services/synonyms.py (Task 3.6): validation, word forms, the
line sent to Elasticsearch, and the set comparison and push with a fake client."""

from __future__ import annotations

from typing import Any

import pytest

from services.synonyms import (
    EQUIVALENT,
    MAX_TERMS,
    ONE_WAY,
    InvalidRule,
    Rule,
    desired_set,
    parse_rule,
    read_set,
    same_rules,
    split_terms,
    sync_set,
    word_forms,
)


def test_split_terms_normalises() -> None:
    assert split_terms("  Sneakers ,trainers,, Running   Shoes ") == ["sneakers", "trainers", "running shoes"]
    assert split_terms(None) == []


@pytest.mark.parametrize(
    ("term", "forms"),
    [
        ("trainers", ["trainers", "trainer"]),
        ("sneaker", ["sneaker", "sneakers"]),
        ("couch", ["couch", "couches"]),
        ("boxes", ["boxes", "box"]),
        ("batteries", ["batteries", "battery"]),
        ("battery", ["battery", "batteries"]),
        ("day", ["day", "days"]),  # vowel before y: a plain s
        ("glass", ["glass", "glasses"]),
        ("hooded sweatshirt", ["hooded sweatshirt", "hooded sweatshirts"]),  # the last word only
        ("tv", ["tv"]),  # too short to guess
        ("4k", ["4k"]),  # not only letters
    ],
)
def test_word_forms(term: str, forms: list[str]) -> None:
    assert word_forms(term) == forms


def test_equivalent_line_lists_every_form_once() -> None:
    rule = parse_rule(EQUIVALENT, "Sneakers, trainers, sneaker")

    assert rule.line() == "sneakers, sneaker, trainers, trainer"


def test_one_way_line_keeps_the_typed_words() -> None:
    rule = parse_rule(ONE_WAY, "torch", "flashlight")

    assert rule == Rule(ONE_WAY, ("torch",), ("flashlight",))
    assert rule.line() == "torch, torches => torch, torches, flashlight, flashlights"


@pytest.mark.parametrize(
    ("rule_type", "terms", "targets", "message"),
    [
        (EQUIVALENT, "sofa", None, "at least two terms"),
        (EQUIVALENT, "sofa, couch => settee", None, "reserves"),
        (EQUIVALENT, "sofa, #couch", None, "reserves"),
        (EQUIVALENT, "sofa, ---", None, "no letter or digit"),
        (EQUIVALENT, "sofa, " + "x" * 61, None, "longer than"),
        (EQUIVALENT, "sofa, couch, Sofa", None, "Repeated term: sofa"),
        (EQUIVALENT, ", ".join(f"word{i}" for i in range(MAX_TERMS + 1)), None, "At most"),
        (ONE_WAY, "torch", None, "needs the words"),
        (ONE_WAY, "torch", "flashlight, torch", "both typed and searched"),
        ("both_ways", "a, b", None, "Unknown rule type"),
    ],
)
def test_invalid_rules_have_clear_messages(
    rule_type: str, terms: str, targets: str | None, message: str
) -> None:
    with pytest.raises(InvalidRule, match=message):
        parse_rule(rule_type, terms, targets)


def test_targets_are_ignored_for_same_meaning_rules() -> None:
    assert parse_rule(EQUIVALENT, "sofa, couch", "settee").targets == ()


def test_desired_set_is_keyed_by_odoo_id() -> None:
    rules = [(7, parse_rule(EQUIVALENT, "sofa, couch")), (3, parse_rule(EQUIVALENT, "tv, television"))]

    assert desired_set(rules) == [
        {"id": "ld-3", "synonyms": "tv, television, televisions"},
        {"id": "ld-7", "synonyms": "sofa, sofas, couch, couches"},
    ]


def test_same_rules_ignores_spacing_and_order_of_entries() -> None:
    desired = [{"id": "ld-1", "synonyms": "a, b => a, b, c"}, {"id": "ld-2", "synonyms": "x, y"}]
    actual = [{"id": "ld-2", "synonyms": "x,y"}, {"id": "ld-1", "synonyms": "a,b=>a,b,c"}]

    assert same_rules(actual, desired)
    assert not same_rules(actual[:1], desired)
    assert not same_rules([{"id": "ld-2", "synonyms": "x, z"}, actual[1]], desired)


class NotFound(Exception):
    def __init__(self) -> None:
        super().__init__("not found")
        self.status_code = 404


class FakeSynonyms:
    def __init__(self, rules: list[dict[str, str]] | None) -> None:
        self.rules = rules  # None: the set does not exist
        self.puts: list[tuple[str, list[dict[str, str]]]] = []

    def get_synonym(self, id: str, size: int) -> dict[str, Any]:
        if self.rules is None:
            raise NotFound()
        return {"count": len(self.rules), "synonyms_set": list(self.rules)}

    def put_synonym(self, id: str, synonyms_set: list[dict[str, str]]) -> dict[str, Any]:
        self.puts.append((id, synonyms_set))
        self.rules = list(synonyms_set)
        return {"result": "updated"}


class FakeClient:
    def __init__(self, rules: list[dict[str, str]] | None) -> None:
        self.synonyms = FakeSynonyms(rules)


DESIRED = [{"id": "ld-1", "synonyms": "sofa, sofas, couch, couches"}]


def test_sync_pushes_only_when_the_set_differs() -> None:
    client = FakeClient([{"id": "ld-1", "synonyms": "sofa, couch"}])

    first = sync_set(client, "shop-synonyms", DESIRED)
    second = sync_set(client, "shop-synonyms", DESIRED)

    assert (first.pushed, second.pushed, second.rules) == (True, False, 1)
    assert client.synonyms.puts == [("shop-synonyms", DESIRED)]


def test_sync_repairs_a_missing_set() -> None:
    client = FakeClient(None)

    assert read_set(client, "shop-synonyms", (NotFound,)) == []
    assert sync_set(client, "shop-synonyms", DESIRED, (NotFound,)).pushed


def test_sync_empties_the_set_when_every_rule_is_removed() -> None:
    client = FakeClient(DESIRED)

    assert sync_set(client, "shop-synonyms", []).pushed
    assert client.synonyms.rules == []


def test_other_errors_are_not_mistaken_for_a_missing_set() -> None:
    class Down(Exception):
        status_code = 503

    class Broken(FakeSynonyms):
        def get_synonym(self, id: str, size: int) -> dict[str, Any]:
            raise Down("unavailable")

    client = FakeClient([])
    client.synonyms = Broken([])

    with pytest.raises(Down):
        read_set(client, "shop-synonyms", (Down,))
