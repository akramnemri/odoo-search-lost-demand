from __future__ import annotations

import random
from pathlib import Path

import pytest
from conftest import REPO_ROOT

from shoptools.data import enrichment as en

RULES_TEXT = """
[[category]]
name = "Electronics"
price_median = 30.0
price_sigma = 0.9
keywords = ["phone case", "cable", "charger"]

[[category]]
name = "Clothing"
price_median = 25.0
price_sigma = 0.6
keywords = ["shirt", "t shirt", "dress", "cable knit"]

[[category]]
name = "Shoes"
price_median = 50.0
price_sigma = 0.6
keywords = ["shoe", "sneaker"]

[other]
name = "Other"
price_median = 20.0
price_sigma = 0.9
"""


@pytest.fixture
def rules(tmp_path: Path) -> en.CategoryRules:
    path = tmp_path / "categories.toml"
    path.write_text(RULES_TEXT, encoding="utf-8")
    return en.load_category_rules(path)


@pytest.mark.parametrize(
    ("word", "folded"),
    [
        ("shoes", "shoe"),
        ("batteries", "battery"),
        ("boxes", "box"),
        ("watches", "watch"),
        ("glasses", "glass"),
        ("dress", "dress"),
        ("bus", "bus"),
        ("iris", "iris"),
        ("gas", "gas"),
        ("toys", "toy"),
    ],
)
def test_fold_word(word: str, folded: str) -> None:
    assert en.fold_word(word) == folded


def test_words_normalize_split_and_fold() -> None:
    assert en.words("Men's T-Shirts, 2 Pack!") == ["men", "s", "t", "shirt", "2", "pack"]
    assert en.words(None) == []


def test_title_beats_bullet_points_and_phrases_count(rules: en.CategoryRules) -> None:
    assert (
        en.assign_category("Running Shoes", "USB cable included", rules) == "Shoes"
    )  # 3 (title) > 1 (bullets)
    assert en.assign_category("Basic Tee", "A soft shirt", rules) == "Clothing"  # bullets alone decide
    assert en.assign_category("iPhone Phone Cases", None, rules) == "Electronics"  # a phrase, folded
    assert en.assign_category("Mystery item", "Nothing to see", rules) == "Other"
    assert en.assign_category("", None, rules) == "Other"


def test_a_tie_goes_to_the_category_listed_first(rules: en.CategoryRules) -> None:
    # "cable" scores 3 for Electronics, "dress" 3 for Clothing: Electronics is listed first.
    assert en.assign_category("Dress cable", None, rules) == "Electronics"
    # "cable knit" (Clothing) and "cable" (Electronics) both match: 6 for Clothing, 3 for Electronics.
    assert en.assign_category("Cable knit dress", None, rules) == "Clothing"


def test_keywords_in_finds_words_and_phrases_only(rules: en.CategoryRules) -> None:
    assert en.keywords_in("Cable knit T-shirt and a phone", rules) == {
        "cable",
        "cable knit",
        "t shirt",
        "shirt",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (RULES_TEXT.replace('name = "Shoes"', 'name = "Clothing"'), "repeat a category"),
        (RULES_TEXT.replace('["shoe", "sneaker"]', '["shoe", "!!"]'), "empty one"),
        (RULES_TEXT.replace('["shoe", "sneaker"]', '["one two three four"]'), "more than 3 words"),
        (RULES_TEXT.replace("price_sigma = 0.6", "price_sigma = 0", 1), "positive price"),
        ("[[category]]\nname = 'x'\n", "not valid"),
    ],
)
def test_invalid_rules_are_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "categories.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(en.CategoryRulesError, match=message):
        en.load_category_rules(path)


def test_project_rules_load_without_a_keyword_in_two_categories() -> None:
    rules = en.load_category_rules(REPO_ROOT / "tools" / "shoptools" / "data" / "categories.toml")

    assert rules.other.name == "Other"
    shared = {keyword: cats for keyword, cats in rules.keyword_index.items() if len(set(cats)) > 1}
    assert shared == {}


def test_prices_are_bounded_whole_dollars_ending_in_99(rules: en.CategoryRules) -> None:
    rng = random.Random(1)
    category = rules.by_name("Electronics")
    prices = [en.draw_price_cents(category, rng, 2, 999) for _ in range(2000)]

    assert all(price % 100 == 99 for price in prices)
    assert min(prices) >= 299
    assert max(prices) <= 99_999
    assert 2_000 < sorted(prices)[1000] < 4_500  # median near the category's $30
    first, again = (en.draw_price_cents(category, random.Random(7), 2, 999) for _ in range(2))
    assert first == again


def test_stock_is_within_bounds() -> None:
    rng = random.Random(2)
    values = [en.draw_stock(rng, 3, 150) for _ in range(2000)]

    assert min(values) >= 3
    assert max(values) <= 150
    assert sum(1 for value in values if value <= 21) > 900  # log scale: about half below the geometric middle


def test_same_brand_same_vendor() -> None:
    assert en.vendor_for("Nike", "A1", 20) == en.vendor_for("  NIKE ", "B2", 20)
    assert 1 <= en.vendor_for("Nike", "A1", 20) <= 20
    unbranded = {en.vendor_for(None, f"P{n}", 20) for n in range(200)}
    assert len(unbranded) > 10  # spread by product id, not all on one vendor
    assert en.vendor_name(3) == "Synthetic Vendor 03"


def test_vendor_terms_are_within_bounds() -> None:
    rng = random.Random(3)
    for _ in range(500):
        price, min_qty, lead_days = en.draw_vendor_terms(2_999, rng, (0.55, 0.75), (1, 10), (2, 14))
        assert round(2_999 * 0.55) <= price <= round(2_999 * 0.75)
        assert 1 <= min_qty <= 10
        assert 2 <= lead_days <= 14


def test_strip_html() -> None:
    assert (
        en.strip_html("<p>Soft <b>cotton</b></p><ul><li>Machine wash</li></ul>") == "Soft cotton Machine wash"
    )
    assert en.strip_html("&lt;b&gt;Bold&lt;/b&gt; text") == "Bold text"
    assert en.strip_html("Fish &amp; chips") == "Fish & chips"
    assert en.strip_html("  plain   text ") == "plain text"
    assert en.strip_html(None) == ""


def test_plain_description_joins_and_caps() -> None:
    assert en.plain_description("<p>Nice</p>", "First\nSecond", 100) == "Nice\nFirst\nSecond"
    assert en.plain_description(None, None, 100) == ""
    long = en.plain_description("word " * 100, None, 120)
    assert len(long) <= 120
    assert not long.endswith(" ")
    assert long.split()[-1] == "word"  # cut at a word boundary
