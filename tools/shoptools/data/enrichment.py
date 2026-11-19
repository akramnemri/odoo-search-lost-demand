"""Synthetic enrichment of the ESCI catalog slice (Task 2.3b, docs/ai/04_DATA_SEARCH_EVALUATION.md §4).

ESCI products have a title, description, bullet points, brand and colour, but no category, price, stock or vendor.
A shop needs them, so they are added here, deterministically. Everything this module produces is SYNTHETIC and is
labelled so in the manifest, the enrichment report and (Task 2.4) the shop. It never changes a relevance label.

- category: keyword rules from `categories.toml` (`assign_category`), "Other" when nothing matches;
- list price: log-normal per category, bounded, ending in .99, in integer cents (`draw_price_cents`);
- stock: a whole number drawn on a log scale between two bounds (`draw_stock`); the out-of-stock set gets 0;
- vendor: one of N synthetic vendors, from a hash of the normalized brand, so the same brand always has the same
  vendor (`vendor_for`); a product without a brand uses its product id instead;
- vendor terms: purchase price as a share of the list price, minimum quantity and lead time, drawn per product;
- description: ESCI description and bullet points as plain text, HTML removed, capped (`plain_description`).

Random draws come from the caller's generator (one stream per field, slice_builder.py). Prices use floating-point
maths (`random.lognormvariate`) before rounding to cents; on the same machine and Python the result is identical.
"""

from __future__ import annotations

import hashlib
import html
import math
import random
import re
import tomllib
from dataclasses import dataclass
from functools import cached_property, lru_cache
from html.parser import HTMLParser
from pathlib import Path

from shoptools.data.normalize import normalize_query

OTHER = "Other"
TITLE_WEIGHT = 3
BULLET_WEIGHT = 1
MAX_PHRASE_WORDS = 3


class CategoryRulesError(Exception):
    """categories.toml is missing a field, repeats a category or has an empty keyword."""


@dataclass(frozen=True)
class Category:
    name: str
    price_median: float
    price_sigma: float
    keywords: tuple[str, ...]  # folded, space-separated words


@dataclass(frozen=True)
class CategoryRules:
    categories: tuple[Category, ...]  # in file order: earlier wins a tie
    other: Category

    @cached_property
    def keyword_index(self) -> dict[str, list[int]]:
        """keyword -> positions of the categories listing it (a keyword listed twice counts twice)."""
        index: dict[str, list[int]] = {}
        for position, category in enumerate(self.categories):
            for keyword in category.keywords:
                index.setdefault(keyword, []).append(position)
        return index

    @cached_property
    def phrase_starts(self) -> frozenset[str]:
        """First words of the keywords of two words or more: only these can start a longer phrase."""
        return frozenset(keyword.split()[0] for keyword in self.keyword_index if " " in keyword)

    def by_name(self, name: str) -> Category:
        if name == self.other.name:
            return self.other
        return next(category for category in self.categories if category.name == name)

    @property
    def names(self) -> list[str]:
        return [category.name for category in self.categories] + [self.other.name]


def load_category_rules(path: Path) -> CategoryRules:
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        categories = tuple(
            Category(
                str(row["name"]),
                float(row["price_median"]),
                float(row["price_sigma"]),
                tuple(" ".join(words(keyword)) for keyword in row["keywords"]),
            )
            for row in parsed["category"]
        )
        other_row = parsed["other"]
        other = Category(str(other_row["name"]), float(other_row["price_median"]), float(other_row["price_sigma"]), ())
    except (OSError, KeyError, TypeError, ValueError) as error:  # tomllib.TOMLDecodeError is a ValueError
        raise CategoryRulesError(f"category rules {path} are not valid: {error}") from error
    names = [category.name for category in categories] + [other.name]
    if len(names) != len(set(names)):
        raise CategoryRulesError(f"category rules {path} repeat a category name")
    for category in categories:
        if not category.keywords or any(not keyword for keyword in category.keywords):
            raise CategoryRulesError(f"category {category.name!r} has no keyword or an empty one")
        if any(len(keyword.split()) > MAX_PHRASE_WORDS for keyword in category.keywords):
            raise CategoryRulesError(f"category {category.name!r} has a phrase of more than {MAX_PHRASE_WORDS} words")
        if any(price <= 0 for price in (category.price_median, category.price_sigma)):
            raise CategoryRulesError(f"category {category.name!r} needs a positive price_median and price_sigma")
    return CategoryRules(categories, other)


# --- category ------------------------------------------------------------------------------------------------


@lru_cache(maxsize=200_000)  # the same words come back in thousands of titles and bullet points
def fold_word(word: str) -> str:
    """A simple singular, enough for keyword matching: boxes -> box, batteries -> battery, shoes -> shoe."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: str | None) -> list[str]:
    """Normalized (04 §8.1), split into runs of letters and digits ("t-shirt" -> t, shirt), folded."""
    return [fold_word(word) for word in re.findall(r"[^\W_]+", normalize_query(text or ""))]


def keywords_in(text: str | None, rules: CategoryRules) -> set[str]:
    """The keywords (single words and phrases of up to MAX_PHRASE_WORDS words) that occur in the text."""
    tokens = words(text)
    index, starts = rules.keyword_index, rules.phrase_starts
    found = set()
    for start, token in enumerate(tokens):
        if token in index:
            found.add(token)
        if token in starts:
            for size in range(2, min(MAX_PHRASE_WORDS, len(tokens) - start) + 1):
                phrase = " ".join(tokens[start : start + size])
                if phrase in index:
                    found.add(phrase)
    return found


def assign_category(title: str | None, bullet_points: str | None, rules: CategoryRules) -> str:
    """Best keyword score: 3 per keyword in the title, 1 per keyword only in the bullet points; ties: file order."""
    in_title = keywords_in(title, rules)
    in_bullets = keywords_in(bullet_points, rules) - in_title
    scores = [0] * len(rules.categories)
    for keywords, weight in ((in_title, TITLE_WEIGHT), (in_bullets, BULLET_WEIGHT)):
        for keyword in keywords:
            for position in rules.keyword_index[keyword]:
                scores[position] += weight
    best_name, best_score = rules.other.name, 0
    for category, score in zip(rules.categories, scores, strict=True):
        if score > best_score:  # strictly greater: an earlier category keeps a tie
            best_name, best_score = category.name, score
    return best_name


# --- prices, stock, vendors ------------------------------------------------------------------------------------


def draw_price_cents(category: Category, rng: random.Random, minimum: int, maximum: int) -> int:
    """Log-normal around the category median, clamped to [minimum, maximum] whole dollars, then x.99."""
    dollars = rng.lognormvariate(math.log(category.price_median), category.price_sigma)
    whole = min(max(math.floor(dollars), minimum), maximum)
    return whole * 100 + 99


def draw_stock(rng: random.Random, minimum: int, maximum: int) -> int:
    """Uniform on a log scale: as many products with 3–10 units as with 40–150, like a small shop's shelves."""
    return round(math.exp(rng.uniform(math.log(minimum), math.log(maximum))))


def vendor_for(brand: str | None, product_id: str, vendor_count: int) -> int:
    """Vendor number 1..N. Same normalized brand -> same vendor; no brand -> spread by product id."""
    key = normalize_query(brand or "")
    key = f"brand:{key}" if key else f"product:{product_id}"
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % vendor_count + 1


def vendor_name(number: int) -> str:
    return f"Synthetic Vendor {number:02d}"


def draw_vendor_terms(
    list_price_cents: int,
    rng: random.Random,
    share: tuple[float, float],
    min_qty: tuple[int, int],
    lead_days: tuple[int, int],
) -> tuple[int, int, int]:
    """(purchase price in cents, minimum order quantity, lead time in days)."""
    price = round(list_price_cents * rng.uniform(*share))
    return price, rng.randint(*min_qty), rng.randint(*lead_days)


# --- description -----------------------------------------------------------------------------------------------


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "li", "div"}:
            self.parts.append(" ")


def strip_html(text: str | None) -> str:
    text = text or ""
    if "&lt;" in text:  # markup escaped once more in the source: unescape it, then parse it
        text = html.unescape(text)
    if "<" not in text and "&" not in text:  # plain text (most bullet points): no parser needed
        return " ".join(text.split())
    parser = _TextOnly()
    parser.feed(text)
    parser.close()
    return " ".join("".join(parser.parts).split())


def plain_description(description: str | None, bullet_points: str | None, max_chars: int) -> str:
    """Description, then the bullet points one per line, as plain text, cut at a word boundary."""
    parts = [strip_html(description)]
    parts += [strip_html(line) for line in (bullet_points or "").splitlines()]
    text = "\n".join(part for part in parts if part)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    return cut[: cut.rfind(" ")] if " " in cut else cut
