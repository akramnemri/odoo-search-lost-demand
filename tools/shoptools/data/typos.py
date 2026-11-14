"""One seeded typo in a query (docs/evaluation/protocol.md §6.3, docs/ai/04_DATA_SEARCH_EVALUATION.md §9).

The `test-typo` query set (Task 2.3a) and, later, the virtual shoppers (M5) use this same model, so a typo in the
evaluation looks like a typo in the simulated traffic.

Model: pick one word of at least `min_letters` letters (a word is a run of letters; digits, apostrophes and other
signs split words, so "iphone11" holds the word "iphone" and "men's" holds no eligible word), then one edit in it:

- `swap`: exchange two neighbouring letters that differ ("shoe" -> "sohe");
- `delete`: drop one letter;
- `duplicate`: type one letter twice;
- `keyboard-neighbour`: replace one ASCII letter with a key next to it on a US QWERTY keyboard, keeping its case.

Every choice (word, edit, position, replacement key) is uniform and comes from the caller's random generator, in
that order. An edit that cannot apply to the chosen word (a swap in "aaaa") is not offered. Each edit changes the
text, and is exactly one edit in the Damerau-Levenshtein (optimal string alignment) sense.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

OPERATIONS = ("swap", "delete", "duplicate", "keyboard-neighbour")
QWERTY_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


def _keyboard_neighbours() -> dict[str, str]:
    """Each key's neighbours on the staggered layout: same row left/right, and two keys above and below.

    Row r + 1 is shifted right by about half a key, so key i of row r touches keys i - 1 and i of row r + 1,
    and key i of row r + 1 touches keys i and i + 1 of row r ("s" touches "w", "e", "z", "x").
    """
    pairs: list[tuple[str, str]] = []
    for row in QWERTY_ROWS:
        pairs += zip(row, row[1:], strict=False)  # left and right
    for upper, lower in zip(QWERTY_ROWS, QWERTY_ROWS[1:], strict=False):
        pairs += zip(upper, lower, strict=False)  # key i above key i ("s" above "x")
        pairs += zip(upper[1:], lower, strict=False)  # key i + 1 above key i ("d" above "x")
    neighbours: dict[str, set[str]] = {key: set() for row in QWERTY_ROWS for key in row}
    for a, b in pairs:
        neighbours[a].add(b)
        neighbours[b].add(a)
    return {key: "".join(sorted(keys)) for key, keys in neighbours.items()}


KEYBOARD_NEIGHBOURS = _keyboard_neighbours()


@dataclass(frozen=True)
class Typo:
    text: str  # the query with the typo
    operation: str  # one of OPERATIONS
    position: int  # index in the original text of the letter the edit starts at


def make_typo(text: str, rng: random.Random, min_letters: int = 4) -> Typo | None:
    """One edit in one eligible word, or None when the text has no word of `min_letters` letters."""
    words = list(re.finditer(rf"[^\W\d_]{{{min_letters},}}", text))
    if not words:
        return None
    word = rng.choice(words)
    letters = word.group()
    positions = {
        "swap": [i for i in range(len(letters) - 1) if letters[i] != letters[i + 1]],
        "delete": list(range(len(letters))),
        "duplicate": list(range(len(letters))),
        "keyboard-neighbour": [i for i, letter in enumerate(letters) if letter.lower() in KEYBOARD_NEIGHBOURS],
    }
    operation = rng.choice([name for name in OPERATIONS if positions[name]])
    i = rng.choice(positions[operation])
    if operation == "swap":
        edited = letters[:i] + letters[i + 1] + letters[i] + letters[i + 2 :]
    elif operation == "delete":
        edited = letters[:i] + letters[i + 1 :]
    elif operation == "duplicate":
        edited = letters[: i + 1] + letters[i:]
    else:
        replacement = rng.choice(KEYBOARD_NEIGHBOURS[letters[i].lower()])
        edited = letters[:i] + (replacement.upper() if letters[i].isupper() else replacement) + letters[i + 1 :]
    return Typo(text[: word.start()] + edited + text[word.end() :], operation, word.start() + i)
