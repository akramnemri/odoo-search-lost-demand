from __future__ import annotations

import random
import re
from collections import Counter

from conftest import edit_distance

from shoptools.data.typos import KEYBOARD_NEIGHBOURS, OPERATIONS, make_typo

QUERIES = [
    "iphone 11 case",
    "Women's Running Shoes size 8",
    "usb c to hdmi adapter 4k",
    "LEGO star wars",
    "aaaa batteries",
    "café au lait mugs",
]


def test_edit_distance_helper() -> None:
    assert edit_distance("shoe", "shoe") == 0
    assert edit_distance("shoe", "sohe") == 1  # swap
    assert edit_distance("shoe", "she") == 1
    assert edit_distance("shoe", "shooe") == 1
    assert edit_distance("shoe", "shpe") == 1
    assert edit_distance("shoe", "hsoe") == 1
    assert edit_distance("shoe", "ohse") == 2


def test_every_typo_is_exactly_one_edit_in_one_eligible_word() -> None:
    rng = random.Random(1)
    operations: Counter[str] = Counter()
    for _ in range(400):
        for query in QUERIES:
            typo = make_typo(query, rng)
            assert typo is not None
            assert edit_distance(query, typo.text) == 1, (query, typo)
            assert query[typo.position].isalpha()
            # Only letters of a word of >= 4 letters change: digits and short words stay as they were.
            eligible = [m.span() for m in re.finditer(r"[^\W\d_]{4,}", query)]
            assert any(start <= typo.position < end for start, end in eligible)
            operations[typo.operation] += 1
    assert set(operations) == set(OPERATIONS)


def test_no_eligible_word_means_no_typo() -> None:
    rng = random.Random(1)
    for query in ("tv 4k", "men's hat", "123456", "", "abc-def"):
        assert make_typo(query, rng) is None
    assert make_typo("men's hat", rng, min_letters=3) is not None


def test_letters_next_to_digits_form_a_word() -> None:
    rng = random.Random(3)
    for _ in range(100):
        typo = make_typo("iphone11", rng)
        assert typo is not None
        assert typo.text.endswith("11")
        assert typo.position < 6


def test_swap_is_not_offered_when_it_would_change_nothing() -> None:
    rng = random.Random(5)
    seen = {make_typo("aaaa", rng).operation for _ in range(300)}
    assert "swap" not in seen
    assert seen == {"delete", "duplicate", "keyboard-neighbour"}


def test_keyboard_neighbour_keeps_the_case() -> None:
    rng = random.Random(7)
    replaced = [
        typo
        for typo in (make_typo("SHOE", rng) for _ in range(300))
        if typo.operation == "keyboard-neighbour"
    ]
    assert replaced
    for typo in replaced:
        assert typo.text.isupper()
        original = "SHOE"[typo.position].lower()
        assert typo.text[typo.position].lower() in KEYBOARD_NEIGHBOURS[original]


def test_keyboard_neighbours_follow_the_qwerty_layout() -> None:
    assert KEYBOARD_NEIGHBOURS["s"] == "adewxz"
    assert KEYBOARD_NEIGHBOURS["q"] == "aw"
    assert KEYBOARD_NEIGHBOURS["m"] == "jkn"
    assert len(KEYBOARD_NEIGHBOURS) == 26
    for key, neighbours in KEYBOARD_NEIGHBOURS.items():
        assert key not in neighbours
        assert all(key in KEYBOARD_NEIGHBOURS[other] for other in neighbours)  # adjacency is symmetric


def test_same_seed_same_typos() -> None:
    first = [make_typo(query, random.Random(42)) for query in QUERIES]
    second = [make_typo(query, random.Random(42)) for query in QUERIES]
    assert first == second
