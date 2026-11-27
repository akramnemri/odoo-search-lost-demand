"""Search synonyms (Task 3.6, FR2): rule validation, word forms, and the Elasticsearch synonyms set.

Odoo is the source of truth (`lost_demand.synonym`); the synonyms set `shop-synonyms` is a copy. The index's
search analyzer reads the set at search time (`synonym_graph`, `updateable: true`), and Elasticsearch reloads
it by itself when the set changes: a new rule works for the next search, without reindexing.

Why Odoo adds word forms: the search analyzer applies synonyms *before* stemming (elastic/products/
settings.json), so a rule only matches the exact forms it lists — "sneakers, trainers" would not expand
"trainer". Applying synonyms after stemming would match every form but merge unrelated words ("trainers" is
stemmed to "train": a toy train would bring sneakers; measured on the cluster, 2026-11-27). So each term is
sent with its simple singular or plural form, and the administrator sees the exact line sent.

Elasticsearch accepts almost any text as a rule (it stored "=>" as a rule in the same check), so the rules are
validated here, with messages an administrator can act on.

Over-broad rules ("laptop, pc") are softened by the query, not here: `query_builder` scores the typed words a
second time without synonyms (`literal_boost`), so products that match what the shopper typed come first.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

EQUIVALENT, ONE_WAY = "equivalent", "one_way"
RULE_TYPES = (EQUIVALENT, ONE_WAY)
RULE_ID_PREFIX = "ld-"
MAX_TERMS = 10  # per side of a rule: a long list is usually several rules, or an over-broad one
MAX_TERM_CHARS = 60
MAX_RULES = 10_000  # read back at once (GET _synonyms/<set> answers 10 rules by default)
# Characters of the Solr synonym syntax that Elasticsearch parses; a term holding one would change the rule.
RESERVED = ("=>", "#", "\\", "\n", "\r", "\t")
_ALNUM = re.compile(r"[^\W_]", re.UNICODE)


class InvalidRule(ValueError):
    """The rule cannot be sent; the message tells the administrator what to change."""


def split_terms(text: str | None) -> list[str]:
    """Terms of a comma-separated list: trimmed, lower case, inner spaces collapsed, empty ones dropped."""
    return [" ".join(part.split()).lower() for part in (text or "").split(",") if part.strip()]


def check_term(term: str) -> None:
    for reserved in RESERVED:
        if reserved in term:
            shown = {"\n": "a line break", "\r": "a line break", "\t": "a tab"}.get(reserved, f'"{reserved}"')
            raise InvalidRule(f'"{term}" contains {shown}, which the synonym syntax reserves; remove it.')
    if len(term) > MAX_TERM_CHARS:
        raise InvalidRule(f'"{term[:20]}…" is longer than {MAX_TERM_CHARS} characters: use a shorter term.')
    if not _ALNUM.search(term):
        raise InvalidRule(f'"{term}" has no letter or digit: a search never contains it as a word.')


def word_forms(term: str) -> list[str]:
    """The term and the simple English singular or plural of its last word (letters only, 3 or more).

    Deliberately simple and visible: the administrator sees every form in the line sent to search.
    """
    words = term.split(" ")
    last = words[-1]
    forms = [last]
    if len(last) >= 3 and last.isalpha():
        if last.endswith("ies") and len(last) > 4:
            forms.append(last[:-3] + "y")
        elif last.endswith(("ses", "xes", "zes", "ches", "shes")):
            forms.append(last[:-2])
        elif last.endswith("s") and not last.endswith("ss"):
            forms.append(last[:-1])
        elif last.endswith("y") and last[-2] not in "aeiou":
            forms.append(last[:-1] + "ies")
        elif last.endswith(("s", "x", "z", "ch", "sh")):
            forms.append(last + "es")
        else:
            forms.append(last + "s")
    return list(dict.fromkeys(" ".join([*words[:-1], form]) for form in forms))


def _expanded(terms: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(form for term in terms for form in word_forms(term)))


@dataclass(frozen=True)
class Rule:
    """A validated rule: what the administrator wrote, normalised."""

    rule_type: str
    terms: tuple[str, ...]  # equivalent: all the words; one-way: what the shopper types
    targets: tuple[str, ...] = ()  # one-way only: what to search for as well

    def line(self) -> str:
        """The rule in Elasticsearch's (Solr) synonym syntax, with the word forms added."""
        typed = _expanded(self.terms)
        if self.rule_type == EQUIVALENT:
            return ", ".join(typed)
        # One-way: the typed words keep their own meaning and also search the targets.
        return f"{', '.join(typed)} => {', '.join(_expanded([*self.terms, *self.targets]))}"


def parse_rule(rule_type: str, terms_text: str | None, targets_text: str | None = None) -> Rule:
    """Validate what the administrator wrote; raise InvalidRule with a clear message."""
    if rule_type not in RULE_TYPES:
        raise InvalidRule(f"Unknown rule type {rule_type!r}.")
    terms = split_terms(terms_text)
    targets = split_terms(targets_text) if rule_type == ONE_WAY else []
    for term in [*terms, *targets]:
        check_term(term)
    if rule_type == EQUIVALENT and len(terms) < 2:
        raise InvalidRule(
            'A "same meaning" rule needs at least two terms, separated by commas: "sofa, couch".'
        )
    if rule_type == ONE_WAY and (not terms or not targets):
        raise InvalidRule("A one-way rule needs the words shoppers type and the words to also search for.")
    for side in (terms, targets):
        if len(side) > MAX_TERMS:
            raise InvalidRule(
                f"At most {MAX_TERMS} terms per list: split a long list into several rules, and check that "
                "every term really means the same thing (a broad rule changes many searches)."
            )
        duplicates = sorted({term for term in side if side.count(term) > 1})
        if duplicates:
            raise InvalidRule(f"Repeated term: {', '.join(duplicates)}.")
    overlap = sorted(set(terms) & set(targets))
    if overlap:
        raise InvalidRule(f"{', '.join(overlap)} is both typed and searched for: list it once, as typed.")
    return Rule(rule_type, tuple(terms), tuple(targets))


# --- the Elasticsearch set ----------------------------------------------------------------------------------


def rule_id(record_id: int) -> str:
    return f"{RULE_ID_PREFIX}{record_id}"


def desired_set(rules: Iterable[tuple[int, Rule]]) -> list[dict[str, str]]:
    """The set Elasticsearch should hold: one entry per active rule, by Odoo id."""
    return [{"id": rule_id(record_id), "synonyms": rule.line()} for record_id, rule in sorted(rules)]


def _canonical(line: str) -> str:
    sides = line.split("=>")
    return " => ".join(", ".join(term.strip() for term in side.split(",") if term.strip()) for side in sides)


def same_rules(actual: Sequence[Mapping[str, Any]], desired: Sequence[Mapping[str, Any]]) -> bool:
    def as_map(entries: Sequence[Mapping[str, Any]]) -> dict[str, str]:
        return {str(entry.get("id")): _canonical(str(entry.get("synonyms", ""))) for entry in entries}

    return as_map(actual) == as_map(desired)


def _body(response: Any) -> Mapping[str, Any]:
    body = getattr(response, "body", response)
    return body if isinstance(body, Mapping) else {}


def read_set(client: Any, set_name: str, missing_errors: tuple[type[Exception], ...] = ()) -> list[dict]:
    """The rules Elasticsearch holds now; an empty list when the set does not exist."""
    try:
        body = _body(client.synonyms.get_synonym(id=set_name, size=MAX_RULES))
    except missing_errors as error:
        if _status(error) == 404:
            return []
        raise
    return list(body.get("synonyms_set", []))


def _status(error: Exception) -> int | None:
    # elasticsearch-py's ApiError carries the HTTP status in `meta.status`; fakes may set `status_code`.
    meta = getattr(error, "meta", None)
    return getattr(meta, "status", None) or getattr(error, "status_code", None)


@dataclass(frozen=True)
class SyncResult:
    rules: int  # active rules in Odoo
    pushed: bool  # the set was replaced (it differed)


def sync_set(
    client: Any,
    set_name: str,
    desired: list[dict[str, str]],
    missing_errors: tuple[type[Exception], ...] = (),
) -> SyncResult:
    """Make the set equal to `desired`: one comparison, and one replacement of the whole set if it differs.

    Replacing the whole set is atomic and also repairs a set that was lost or edited by hand; Elasticsearch
    reloads the search analyzers of every index that uses it.
    """
    if same_rules(read_set(client, set_name, missing_errors), desired):
        return SyncResult(rules=len(desired), pushed=False)
    client.synonyms.put_synonym(id=set_name, synonyms_set=desired)
    return SyncResult(rules=len(desired), pushed=True)
