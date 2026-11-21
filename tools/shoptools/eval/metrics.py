"""Search-quality metrics and their statistics (protocol §6.1 and §6.5), as pure functions.

- Gains (ESCI convention): Exact 1.0, Substitute 0.1, Complement 0.01, Irrelevant 0. The slice stores each
  judgment's gain in `qrels.parquet` (column `gain`); `GAINS` is checked against it when a run starts.
- NDCG@10: `DCG@10 = Σ_{i=1..10} gain_i / log2(i + 1)` over the ranking; `IDCG@10` = the DCG of the query's
  judged products in their ideal order. A product without a judgment for this query counts 0. A query with
  IDCG = 0 (no relevant judged product) has no NDCG: it is excluded and counted.
- judged@10: the share of the top 10 that is judged for the query (over the results shown, at most 10;
  no value for a query with no result).
- Condensed NDCG@10 (Sakai 2007): NDCG@10 of the ranking with unjudged products removed first. It checks that
  unjudged results do not change the order of the engines; it uses the ranking's depth as given (the harness
  keeps one shop page, 21 products).
- Mean with a 95 % percentile bootstrap interval (10,000 resamples of queries, seeded).
- Paired comparison of two engines on the same queries: mean difference with its bootstrap interval, a
  two-sided paired randomization (sign-flip) test, and Holm's correction over the comparisons.

Every random draw comes from a `random.Random` the caller passes (a seeded stream, protocol §3), so the same
inputs give the same numbers on every machine with the pinned Python.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

GAINS: Mapping[str, float] = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
CUTOFF = 10
RESAMPLES = 10_000
PERMUTATIONS = 10_000
LEVEL = 0.95


def dcg(gains: Sequence[float], k: int = CUTOFF) -> float:
    """Discounted cumulative gain of the first `k` gains (rank 1 has discount log2(2) = 1)."""
    return sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains[:k]))


def ideal_dcg(judgments: Mapping[str, float], k: int = CUTOFF) -> float:
    return dcg(sorted(judgments.values(), reverse=True), k)


def _unique(ranking: Sequence[str]) -> list[str]:
    # A product counts once, at its first position (two links to one product must not double its gain).
    return list(dict.fromkeys(ranking))


def ndcg(ranking: Sequence[str], judgments: Mapping[str, float], k: int = CUTOFF) -> float | None:
    """NDCG@k of one ranking (product IDs, best first); None when the query has no relevant judged product."""
    ideal = ideal_dcg(judgments, k)
    if ideal <= 0:
        return None
    return dcg([judgments.get(product, 0.0) for product in _unique(ranking)], k) / ideal


def judged(ranking: Sequence[str], judgments: Mapping[str, float], k: int = CUTOFF) -> float | None:
    top = _unique(ranking)[:k]
    if not top:
        return None
    return sum(1 for product in top if product in judgments) / len(top)


def condensed_ndcg(ranking: Sequence[str], judgments: Mapping[str, float], k: int = CUTOFF) -> float | None:
    return ndcg([product for product in _unique(ranking) if product in judgments], judgments, k)


@dataclass(frozen=True)
class QueryScore:
    query_id: int
    ndcg: float | None
    judged: float | None
    condensed: float | None
    results: int  # products in the ranking (at most one shop page)


def score(query_id: int, ranking: Sequence[str], judgments: Mapping[str, float]) -> QueryScore:
    return QueryScore(
        query_id=query_id,
        ndcg=ndcg(ranking, judgments),
        judged=judged(ranking, judgments),
        condensed=condensed_ndcg(ranking, judgments),
        results=len(_unique(ranking)),
    )


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean of no values")
    return math.fsum(values) / len(values)


@dataclass(frozen=True)
class Interval:
    mean: float
    low: float
    high: float


def bootstrap_interval(
    values: Sequence[float], rng: random.Random, resamples: int = RESAMPLES, level: float = LEVEL
) -> Interval:
    """Percentile bootstrap: resample the values with replacement `resamples` times; the interval holds the
    middle `level` of the resampled means (sorted, positions floor(R·α/2) and ceil(R·(1 − α/2)) − 1)."""
    if not values:
        raise ValueError("bootstrap of no values")
    size = len(values)
    means = sorted(math.fsum(rng.choices(values, k=size)) / size for _ in range(resamples))
    alpha = 1 - level
    low = means[math.floor(resamples * alpha / 2)]
    high = means[math.ceil(resamples * (1 - alpha / 2)) - 1]
    return Interval(mean=mean(values), low=low, high=high)


def randomization_p(
    differences: Sequence[float], rng: random.Random, permutations: int = PERMUTATIONS
) -> float:
    """Two-sided paired randomization test: under "no difference" each query's difference is as likely to have
    either sign. p = (1 + #permutations whose |mean| ≥ observed |mean|) / (1 + permutations)."""
    if not differences:
        raise ValueError("test of no values")
    size = len(differences)
    observed = abs(math.fsum(differences)) - 1e-12  # tolerance: an equal sum counts as "at least as large"
    extreme = 0
    for _ in range(permutations):
        signs = rng.getrandbits(size)
        total = math.fsum(value if signs >> index & 1 else -value for index, value in enumerate(differences))
        if abs(total) >= observed:
            extreme += 1
    return (1 + extreme) / (1 + permutations)


def holm(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values (step-down, kept monotone, capped at 1)."""
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for position, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - position) * value))
        adjusted[name] = running
    return adjusted


@dataclass(frozen=True)
class Comparison:
    first: str
    second: str
    queries: int
    difference: Interval  # mean of (first − second) per query, with its bootstrap interval
    p_value: float
    p_holm: float | None = None  # set when the comparison is one of the protocol's corrected family


def compare(
    first: str,
    second: str,
    first_scores: Mapping[int, float],
    second_scores: Mapping[int, float],
    bootstrap_rng: random.Random,
    permutation_rng: random.Random,
) -> Comparison:
    """Paired comparison over the queries both engines scored."""
    shared = sorted(set(first_scores) & set(second_scores))
    differences = [first_scores[query] - second_scores[query] for query in shared]
    return Comparison(
        first=first,
        second=second,
        queries=len(shared),
        difference=bootstrap_interval(differences, bootstrap_rng),
        p_value=randomization_p(differences, permutation_rng),
    )
