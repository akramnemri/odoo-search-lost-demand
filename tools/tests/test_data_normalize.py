from __future__ import annotations

import pytest

from shoptools.data.normalize import normalize_query


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("  iPhone   Case!! ", "iphone case"),
        ("\t usb \n c cable ", "usb c cable"),  # tabs, newlines and no-break spaces collapse
        ("Ｎｉｋｅ shoes", "nike shoes"),  # NFKC: full-width letters
        ("ﬁlter", "filter"),  # NFKC: the "fi" ligature
        ("Straße", "strasse"),  # case-fold, not lower(): "ß" folds to "ss"
        ("STRASSE", "strasse"),
        ("-- . shoes!", "shoes"),  # punctuation and spaces at both ends
        ("¿qué es?", "qué es"),  # accents kept, Spanish marks stripped
        ('"3.5" drill"', '3.5" drill'),  # only the ends: the inch mark inside stays
        ("men's shoes", "men's shoes"),
        ("c++", "c++"),  # "+" is a symbol, not punctuation
        ("$20 gift card", "$20 gift card"),
        ("<email> help", "<email> help"),  # the module's personal-data masks keep their brackets
        ("!!!", ""),
        ("", ""),
    ],
)
def test_normalize_query(raw: str, normalized: str) -> None:
    assert normalize_query(raw) == normalized


def test_normalize_query_is_idempotent() -> None:
    for raw in ("  iPhone   Case!! ", "-- . shoes!", '"3.5" drill"', "Straße"):
        once = normalize_query(raw)
        assert normalize_query(once) == once
