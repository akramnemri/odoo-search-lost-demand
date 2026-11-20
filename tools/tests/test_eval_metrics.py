"""Tests of tools/shoptools/eval/metrics.py against hand-computed values (roadmap Task 3.4)."""

from __future__ import annotations

import math

import pytest

from shoptools.data.slice_builder import derived_rng
from shoptools.eval import metrics

# One query's judgments: a = Exact, b = Substitute, c = Complement, d = Irrelevant (ESCI gains).
JUDGED = {"a": 1.0, "b": 0.1, "c": 0.01, "d": 0.0}
# Ideal order a, b, c, d: 1.0/log2(2) + 0.1/log2(3) + 0.01/log2(4) + 0 = 1 + 0.0630930 + 0.005
IDEAL = 1.0 + 0.1 / math.log2(3) + 0.01 / 2


def test_gains_are_the_esci_convention() -> None:
    assert metrics.GAINS == {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}


def test_dcg_by_hand() -> None:
    # 0.1/log2(2) + 0/log2(3) + 1.0/log2(4) = 0.1 + 0 + 0.5
    assert metrics.dcg([0.1, 0.0, 1.0]) == pytest.approx(0.6)


def test_dcg_stops_at_the_cutoff() -> None:
    assert metrics.dcg([1.0] * 12) == pytest.approx(sum(1 / math.log2(rank + 1) for rank in range(1, 11)))


def test_ndcg_by_hand() -> None:
    # Ranking b, x (unjudged), a: DCG 0.6 (above), IDCG 1.0680930.
    assert metrics.ndcg(["b", "x", "a"], JUDGED) == pytest.approx(0.6 / IDEAL)
    assert metrics.ndcg(["b", "x", "a"], JUDGED) == pytest.approx(0.561749, abs=1e-6)


def test_ideal_ranking_scores_one_and_empty_ranking_zero() -> None:
    assert metrics.ndcg(["a", "b", "c", "d"], JUDGED) == pytest.approx(1.0)
    assert metrics.ndcg([], JUDGED) == 0.0


def test_a_product_counts_once() -> None:
    assert metrics.ndcg(["a", "a"], {"a": 1.0, "e": 1.0}) == pytest.approx(1.0 / (1.0 + 1.0 / math.log2(3)))


def test_query_without_relevant_judgment_has_no_ndcg() -> None:
    assert metrics.ndcg(["d"], {"d": 0.0}) is None
    assert metrics.condensed_ndcg(["d"], {"d": 0.0}) is None


def test_judged_share_of_the_top_results() -> None:
    assert metrics.judged(["b", "x", "a"], JUDGED) == pytest.approx(2 / 3)
    assert metrics.judged([f"x{i}" for i in range(15)], JUDGED) == 0.0
    assert metrics.judged([], JUDGED) is None


def test_condensed_ndcg_by_hand() -> None:
    # Unjudged x removed: b, a -> 0.1/log2(2) + 1.0/log2(3) = 0.1 + 0.6309298
    assert metrics.condensed_ndcg(["b", "x", "a"], JUDGED) == pytest.approx((0.1 + 1 / math.log2(3)) / IDEAL)


def test_score_of_one_query() -> None:
    result = metrics.score(7, ["b", "x", "a"], JUDGED)

    assert result.query_id == 7
    assert result.results == 3
    assert result.ndcg == pytest.approx(0.6 / IDEAL)


def test_bootstrap_of_constant_values_is_that_value() -> None:
    interval = metrics.bootstrap_interval([0.4] * 50, derived_rng(1, "t"), resamples=200)

    assert (interval.mean, interval.low, interval.high) == pytest.approx((0.4, 0.4, 0.4))


def test_bootstrap_is_reproducible_and_contains_the_mean() -> None:
    values = [i / 99 for i in range(100)]
    first = metrics.bootstrap_interval(values, derived_rng(20261025, "ndcg-bootstrap"), resamples=1000)
    second = metrics.bootstrap_interval(values, derived_rng(20261025, "ndcg-bootstrap"), resamples=1000)

    assert first == second
    assert first.low < first.mean < first.high
    # The mean of 100 values spread evenly on [0, 1] has a standard error of about 0.029: ±1.96 SE ≈ ±0.057.
    assert first.high - first.low == pytest.approx(0.114, abs=0.02)


def test_randomization_without_difference() -> None:
    assert metrics.randomization_p([0.0] * 20, derived_rng(1, "p"), permutations=500) == 1.0


def test_randomization_with_a_clear_difference() -> None:
    # 30 queries all better by 0.2: only the 2 permutations with every sign equal reach |mean| 0.2 (2 / 2^30).
    p = metrics.randomization_p([0.2] * 30, derived_rng(1, "p"), permutations=2000)

    assert p == pytest.approx(1 / 2001)


def test_randomization_is_two_sided() -> None:
    rng_a, rng_b = derived_rng(5, "p"), derived_rng(5, "p")
    values = [0.3, -0.1, 0.2, 0.05, -0.2, 0.4, 0.1, 0.0]

    assert metrics.randomization_p(values, rng_a, 500) == metrics.randomization_p(
        [-value for value in values], rng_b, 500
    )


def test_holm_by_hand() -> None:
    # Sorted 0.01, 0.03, 0.04 -> 3 × 0.01 = 0.03; 2 × 0.03 = 0.06; 1 × 0.04 = 0.04, kept monotone at 0.06.
    assert metrics.holm({"a": 0.01, "b": 0.04, "c": 0.03}) == pytest.approx({"a": 0.03, "c": 0.06, "b": 0.06})
    assert metrics.holm({"a": 0.6, "b": 0.7}) == {"a": 1.0, "b": 1.0}


def test_compare_pairs_the_shared_queries() -> None:
    first = {1: 0.5, 2: 0.7, 3: 0.9, 4: 1.0}
    second = {1: 0.4, 2: 0.6, 3: 0.8}  # query 4 not scored by the second engine

    comparison = metrics.compare(
        "es_tuned", "es_plain", first, second, derived_rng(1, "b"), derived_rng(1, "p")
    )

    assert comparison.queries == 3
    assert comparison.difference.mean == pytest.approx(0.1)
    assert comparison.p_value == pytest.approx(
        0.25, abs=0.1
    )  # only 8 sign patterns: 2 of them are as extreme


def test_empty_inputs_are_refused() -> None:
    with pytest.raises(ValueError):
        metrics.mean([])
    with pytest.raises(ValueError):
        metrics.bootstrap_interval([], derived_rng(1, "b"))
    with pytest.raises(ValueError):
        metrics.randomization_p([], derived_rng(1, "p"))
