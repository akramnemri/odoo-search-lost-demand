from __future__ import annotations

import random

from shoptools.data import hidden_sets as hs

ORDER = ["Shoes", "Clothing", "Other"]


def test_exact_targets_keep_only_e_labels() -> None:
    judgments = [(1, "A", "E"), (1, "B", "S"), (2, "C", "I"), (3, "D", "E"), (3, "E", "E")]
    assert hs.exact_targets(judgments) == {1: {"A"}, 3: {"D", "E"}}


def test_query_stratum_is_the_majority_category_ties_by_order() -> None:
    category_of = {"A": "Clothing", "B": "Clothing", "C": "Shoes", "D": "Other", "E": "Shoes"}
    targets = {1: {"A", "B", "C"}, 2: {"D", "E"}}

    assert hs.query_strata(targets, category_of, ORDER) == {1: "Clothing", 2: "Shoes"}


def test_allocate_is_proportional_and_exact() -> None:
    assert hs.allocate({"Shoes": 50, "Clothing": 30, "Other": 20}, 10, ORDER) == {
        "Shoes": 5,
        "Clothing": 3,
        "Other": 2,
    }
    shares = hs.allocate({"Shoes": 7, "Clothing": 7, "Other": 7}, 10, ORDER)
    assert sum(shares.values()) == 10
    assert shares == {"Shoes": 4, "Clothing": 3, "Other": 3}  # equal remainders: the earlier category first
    assert hs.allocate({"Shoes": 2, "Clothing": 0, "Other": 1}, 10, ORDER) == {
        "Shoes": 2,
        "Clothing": 0,
        "Other": 1,
    }
    assert hs.allocate({"Shoes": 0}, 3, ["Shoes"]) == {"Shoes": 0}


def scenario() -> tuple[dict[int, set[str]], dict[int, str]]:
    """20 queries with 1–4 E products each; queries 0–9 are 'Shoes', 10–19 'Clothing'."""
    targets = {query_id: {f"P{query_id}-{n}" for n in range(1 + query_id % 4)} for query_id in range(20)}
    strata = {query_id: "Shoes" if query_id < 10 else "Clothing" for query_id in range(20)}
    return targets, strata


def test_hidden_set_hides_every_e_product_of_its_queries() -> None:
    targets, strata = scenario()
    hidden = hs.draw_hidden_set("hidden-test", list(range(20)), targets, strata, 0.2, random.Random(1), ORDER)

    assert len(hidden.queries) == 4
    assert hidden.per_stratum == {"Shoes": (10, 2), "Clothing": (10, 2)}
    assert hidden.products == set().union(*(targets[query_id] for query_id in hidden.queries))
    assert hidden.pairs == sorted(hidden.pairs)
    again = hs.draw_hidden_set("hidden-test", list(range(20)), targets, strata, 0.2, random.Random(1), ORDER)
    assert again == hidden


def test_a_query_sharing_a_forbidden_product_is_not_drawn() -> None:
    targets, strata = scenario()
    targets[5] |= {"SHARED"}
    hidden = hs.draw_hidden_set(
        "hidden-dev",
        list(range(20)),
        targets,
        strata,
        0.5,
        random.Random(2),
        ORDER,
        forbidden_products={"SHARED"},
    )

    assert 5 not in hidden.queries
    assert hidden.excluded_overlap == 1
    assert hidden.candidates == 19
    assert len(hidden.queries) == 10


def test_queries_without_an_exact_product_are_never_drawn() -> None:
    targets, strata = scenario()
    del targets[0]
    hidden = hs.draw_hidden_set("hidden-test", list(range(20)), targets, strata, 1.0, random.Random(3), ORDER)

    assert 0 not in hidden.queries
    assert len(hidden.queries) == 19  # 20 wanted, only 19 have something to hide


def test_out_of_stock_comes_from_searched_products_outside_hidden_sets() -> None:
    targets, strata = scenario()
    hidden = hs.draw_hidden_set("hidden-test", list(range(20)), targets, strata, 0.2, random.Random(4), ORDER)
    chosen, candidates = hs.draw_out_of_stock(
        targets, set(hidden.queries), hidden.products, 100, 0.1, random.Random(5)
    )

    searched = {
        p for query_id, products in targets.items() if query_id not in hidden.queries for p in products
    }
    assert set(chosen) <= searched
    assert not set(chosen) & hidden.products
    assert candidates == len(searched - hidden.products)
    assert len(chosen) == round(0.1 * (100 - len(hidden.products)))
    assert chosen == sorted(chosen)


def test_out_of_stock_is_capped_by_the_candidates() -> None:
    targets = {1: {"A"}, 2: {"B"}}
    chosen, candidates = hs.draw_out_of_stock(targets, {1}, {"A"}, 1000, 0.5, random.Random(6))

    assert (chosen, candidates) == (["B"], 1)
