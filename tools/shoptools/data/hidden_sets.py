"""Hidden sets and out-of-stock set (Task 2.3b; docs/evaluation/protocol.md v1.1 §4, option B2).

Why queries and not single products: in ESCI a query has several Exact (E) products (median 7 in our slice), and
almost every E product is the E target of one query only. Hiding single products leaves each query with other E
products, so the shopper still finds what was asked for and nothing is lost: by construction the report could only
flag ~3 % of hidden products (measured 2026-11-14, STATUS). Lost demand is when the shop has *nothing* that matches.
So a hidden set is built from **hidden queries**: all E products of each chosen query are hidden.

- hidden-test: `query_share` of the test queries (140 of 700), stratified by category, stream `hidden-test`;
- hidden-dev: `query_share` of the dev queries (60 of 300), stratified, stream `hidden-dev`; a dev query sharing an
  E product with hidden-test is not a candidate, so the two product sets are disjoint;
- out-of-stock: `share` of the products in neither hidden set, drawn uniformly among the E products of queries that
  are not hidden (products nobody searches for would never show an out-of-stock signal), stream `out-of-stock`.

Stratum of a query = the most frequent category among its E products (ties: the category listed first). Each stratum
gets its proportional share of the hidden queries (largest remainder, ties by category order).
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass


@dataclass(frozen=True)
class HiddenSet:
    name: str
    queries: list[int]  # sorted
    pairs: list[tuple[int, str]]  # (query id, product id), sorted: every E product of every hidden query
    candidates: int  # queries of the set that could be drawn
    excluded_overlap: int  # queries not drawable because they share an E product with an earlier hidden set
    per_stratum: dict[str, tuple[int, int]]  # category -> (candidate queries, hidden queries)

    @property
    def products(self) -> set[str]:
        return {product_id for _, product_id in self.pairs}


def exact_targets(judgments: Iterable[tuple[int, str, str]]) -> dict[int, set[str]]:
    """(query id, product id, label) -> E products per query (queries without an E product are left out)."""
    targets: dict[int, set[str]] = {}
    for query_id, product_id, label in judgments:
        if label == "E":
            targets.setdefault(query_id, set()).add(product_id)
    return targets


def query_strata(targets: dict[int, set[str]], category_of: dict[str, str], order: Sequence[str]) -> dict[int, str]:
    rank = {name: position for position, name in enumerate(order)}
    return {query_id: _majority_category(products, category_of, rank) for query_id, products in targets.items()}


def _majority_category(products: set[str], category_of: dict[str, str], rank: dict[str, int]) -> str:
    counts = Counter(category_of[product_id] for product_id in products)
    return min(counts, key=lambda name: (-counts[name], rank[name]))


def allocate(available: dict[str, int], total: int, order: Sequence[str]) -> dict[str, int]:
    """Proportional shares of `total` (largest remainder); never more than a stratum has."""
    pool = sum(available.values())
    total = min(total, pool)
    if pool == 0:
        return dict.fromkeys(available, 0)
    quotas = {name: total * count / pool for name, count in available.items()}
    shares = {name: math.floor(quota) for name, quota in quotas.items()}
    rank = {name: position for position, name in enumerate(order)}
    by_remainder = sorted(available, key=lambda name: (-(quotas[name] - shares[name]), rank[name]))
    for name in by_remainder[: total - sum(shares.values())]:
        shares[name] += 1
    return shares


def draw_hidden_set(
    name: str,
    set_queries: Sequence[int],
    targets: dict[int, set[str]],
    strata: dict[int, str],
    query_share: float,
    rng: random.Random,
    order: Sequence[str],
    forbidden_products: AbstractSet[str] = frozenset(),
) -> HiddenSet:
    """`query_share` of `set_queries` (rounded), stratified; only queries with E products none of them forbidden."""
    with_targets = [query_id for query_id in sorted(set_queries) if query_id in targets]
    candidates = [query_id for query_id in with_targets if not targets[query_id] & forbidden_products]
    by_stratum: dict[str, list[int]] = {category: [] for category in order}
    for query_id in candidates:
        by_stratum[strata[query_id]].append(query_id)
    wanted = round(query_share * len(set_queries))
    shares = allocate({category: len(ids) for category, ids in by_stratum.items()}, wanted, order)
    chosen: list[int] = []
    for category in order:  # fixed order, so the stream is consumed the same way every time
        if shares[category]:
            chosen += rng.sample(by_stratum[category], shares[category])
    pairs = sorted((query_id, product_id) for query_id in chosen for product_id in targets[query_id])
    return HiddenSet(
        name=name,
        queries=sorted(chosen),
        pairs=pairs,
        candidates=len(candidates),
        excluded_overlap=len(with_targets) - len(candidates),
        per_stratum={
            category: (len(by_stratum[category]), shares[category]) for category in order if by_stratum[category]
        },
    )


def draw_out_of_stock(
    targets: dict[int, set[str]],
    hidden_queries: set[int],
    hidden_products: set[str],
    catalog_size: int,
    share: float,
    rng: random.Random,
) -> tuple[list[str], int]:
    """(sorted out-of-stock product ids, number of candidates). Size: `share` of the products in no hidden set."""
    candidates = sorted(
        {
            product_id
            for query_id, products in targets.items()
            if query_id not in hidden_queries
            for product_id in products
        }
        - hidden_products
    )
    wanted = round(share * (catalog_size - len(hidden_products)))
    return sorted(rng.sample(candidates, min(wanted, len(candidates)))), len(candidates)
