"""Query normalization (docs/ai/04_DATA_SEARCH_EVALUATION.md §8.1, docs/evaluation/protocol.md §6.1).

One definition for the whole project: the slice builder uses it to remove test queries that duplicate a dev
query (Task 2.3a), and the module uses the same rule when it stores search events (M4). The module cannot import
`shoptools` (it runs inside the Odoo container), so M4 copies this function into the module's `services/` and adds a
test that both give the same output on the same examples. Change both or neither.

Rule, in this order:
1. Unicode NFKC (full-width letters, ligatures and compatibility forms become their plain form);
2. case-fold (stronger than lower(): "Straße" and "STRASSE" match);
3. trim and collapse every run of whitespace into one space;
4. strip punctuation (Unicode categories P*) and spaces at both ends, so "-- . shoes!" gives "shoes".

No stemming, no accent removal and no punctuation removal inside the text: the buyer reads normalized queries in
the "customers asked for" list. Symbols are not punctuation, so "c++", "$20" and the `<email>` / `<phone>` masks the
module puts in place of personal data (M4) keep their characters.
"""

from __future__ import annotations

import unicodedata


def normalize_query(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    collapsed = " ".join(folded.split())
    start, end = 0, len(collapsed)
    while start < end and _is_edge(collapsed[start]):
        start += 1
    while end > start and _is_edge(collapsed[end - 1]):
        end -= 1
    return collapsed[start:end]


def _is_edge(character: str) -> bool:
    return character == " " or unicodedata.category(character).startswith("P")
