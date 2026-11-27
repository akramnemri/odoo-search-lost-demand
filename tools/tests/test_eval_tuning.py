"""Tests of tools/shoptools/eval/tuning.py (Task 3.5): the variant file, the dev-typo set, the decision
rule and a full experiment with a fake Elasticsearch. No stack, no network."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from shoptools.eval import metrics, ndcg, tuning

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def query_builder() -> Any:
    return ndcg.load_module_file(REPO_ROOT / ndcg.QUERY_BUILDER, "tuning_test_query_builder")


@pytest.fixture(scope="module")
def builtins(query_builder: Any) -> dict[str, Any]:
    return {"v0": query_builder.TUNED_V0}


def _toml(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


VARIANT = """
[variants.{name}]
stage = {stage}
parent = "{parent}"
engine = "{engine}"
goal = "{goal}"
hypothesis = "h"
changes = {changes}
"""


def _variant_file(tmp_path: Path, *variants: str, budget: int = 15) -> Path:
    return _toml(tmp_path / "tuning.toml", f"budget = {budget}\n" + "".join(variants))


def _v(
    name: str, changes: str, parent: str = "v0", stage: int = 1, engine: str = "es_tuned", goal: str = "none"
) -> str:
    return VARIANT.format(name=name, stage=stage, parent=parent, engine=engine, goal=goal, changes=changes)


# --- the committed, pre-registered file ---


def test_the_committed_variants_all_resolve(builtins: dict[str, Any]) -> None:
    budget, variants = tuning.load_variants(REPO_ROOT / tuning.TUNING_FILE, builtins)

    assert budget == 15
    assert len(variants) <= budget
    for name in variants:
        tuning.resolve(name, variants, builtins)  # a refused setting raises here, not in the middle of a run


def test_resolve_applies_changes_on_the_parent(tmp_path: Path, builtins: dict[str, Any]) -> None:
    path = _variant_file(
        tmp_path,
        _v("a", '{ fuzziness = "none", fields = ["name^2"] }'),
        _v("b", "{ tie_breaker = 0.3 }", parent="a", stage=2),
    )
    _, variants = tuning.load_variants(path, builtins)

    config = tuning.resolve("b", variants, builtins)

    assert (config.fuzziness, config.fields, config.tie_breaker) == (None, ("name^2",), 0.3)
    assert config.prefix_length == builtins["v0"].prefix_length


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        (_v("a", "{ fuzzyness = 1 }"), "unknown setting"),
        (_v("a", '{ match_type = "cross_fields" }'), "does not support fuzziness"),
        (_v("a", "{}", parent="nope"), "parent"),
        (_v("a", "{}", engine="es_plain"), "engine"),
        (_v("a", "{}", goal="speed"), "goal"),
    ],
)
def test_invalid_variants_are_refused(
    tmp_path: Path, builtins: dict[str, Any], variant: str, message: str
) -> None:
    with pytest.raises(tuning.TuneError, match=message):
        _, variants = tuning.load_variants(_variant_file(tmp_path, variant), builtins)
        tuning.resolve("a", variants, builtins)


# --- dev-typo and the reference sample ---


def test_dev_typo_set_is_seeded_and_one_edit_away() -> None:
    queries = [(1, "royal blue bedspreads"), (2, "usb c"), (3, "throttle cable")]

    first = tuning.dev_typo_queries(queries, 20261025, 4)
    second = tuning.dev_typo_queries(queries, 20261025, 4)

    assert first == second
    assert first[1] == (2, "usb c")  # no word of 4 letters: unchanged, like the test-typo set
    assert first[0][1] != "royal blue bedspreads" and first[2][1] != "throttle cable"
    assert [query_id for query_id, _ in first] == [1, 2, 3]


def test_reference_sample_is_seeded() -> None:
    id_map = {template_id: f"B0{template_id:08d}" for template_id in range(1, 200)}

    sample = tuning.reference_sample(id_map, 20261025)

    assert sample == tuning.reference_sample(id_map, 20261025)
    assert len(sample) == tuning.REFERENCE_SAMPLE
    assert all(id_map[template_id] == ref for template_id, ref in sample)


# --- the pre-registered decision rule ---


def _diff(mean: float, odd: float | None = None, even: float | None = None) -> tuning.Difference:
    interval = metrics.Interval(mean=mean, low=mean - 0.01, high=mean + 0.01)
    comparison = metrics.Comparison(first="v", second="parent", queries=300, difference=interval, p_value=0.5)
    return tuning.Difference(
        "dev", comparison, odd_half=mean if odd is None else odd, even_half=mean if even is None else even
    )


def _decide(
    goal: str = "none", dev: float = 0.0, typo: float = 0.0, stage: int = 1, **kwargs: Any
) -> tuning.Outcome:
    variant = tuning.Variant("v", stage, "v0", "es_tuned", goal, "h", {})
    return tuning.decide(
        variant,
        kwargs.get("dev_diff", _diff(dev)),
        _diff(typo),
        kwargs.get("hits", (900.0, 900.0)),
        kwargs.get("reference", (0.0, 0.0)),
        kwargs.get("in_stock", 1.0),
    )


@pytest.mark.parametrize(
    ("kwargs", "decision", "reason"),
    [
        ({"dev": 0.01}, "keep", "not negative on either half"),
        ({"dev": 0.004}, "drop", "under +0.005"),
        ({"dev": -0.006, "goal": "tail", "hits": (900.0, 100.0)}, "drop", "below -0.005"),
        ({"dev": 0.02, "typo": -0.01}, "drop", "dev-typo"),
        ({"dev_diff": _diff(0.01, odd=0.03, even=-0.01)}, "drop", "not robust"),
        ({"goal": "typo", "dev": -0.004, "typo": 0.01}, "keep", "goal typo"),
        ({"goal": "typo", "dev": 0.0, "typo": -0.02}, "drop", "goal typo not met"),
        ({"goal": "tail", "dev": -0.002, "hits": (900.0, 600.0)}, "keep", "goal tail"),
        ({"goal": "tail", "dev": 0.0, "hits": (900.0, 800.0)}, "drop", "goal tail not met"),
        ({"goal": "reference", "reference": (0.0, 0.96)}, "keep", "goal reference"),
        ({"goal": "reference", "reference": (0.92, 0.96)}, "drop", "goal reference not met"),
        ({"stage": 3, "dev": 0.025, "in_stock": 0.97}, "candidate (b)", "supervisor decides"),
        ({"stage": 3, "dev": 0.025, "in_stock": 0.90}, "keep (a)", "in stock"),
        ({"stage": 3, "dev": 0.01, "in_stock": 0.99}, "keep (a)", "in stock"),
    ],
)
def test_decision_rule(kwargs: dict[str, Any], decision: str, reason: str) -> None:
    outcome = _decide(**kwargs)

    assert outcome.decision == decision
    assert reason in outcome.reason


# --- measuring and a full experiment with a fake Elasticsearch ---


class FakeSearch:
    """Template ids per query text; a configuration with fuzziness off finds the exact product first."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, str]] = []

    def __call__(self, tuned: Any, engine: str, text: str) -> tuning.Hits:
        self.calls.append((tuned, engine, text))
        if text.startswith("B0"):  # a reference: found only with the reference lever
            return tuning.Hits(ids=[int(text[2:])] if tuned.ref_exact_boost else [], took_ms=3)
        exact_first = tuned.fuzziness is None
        ids = [101, 102, 103] if exact_first else [102, 101, 103, 104, 105]
        return tuning.Hits(ids=ids, took_ms=4)


def test_measure(query_builder: Any) -> None:
    search = FakeSearch()
    judgments = {1: {"P1": 1.0}, 2: {"P1": 1.0}}
    esci_of = {101: "P1", 102: "P2", 103: "P3"}

    result = tuning.measure(
        "x",
        search,
        query_builder.TUNED_V0,
        "es_tuned",
        "dev",
        [(1, "a"), (2, "b")],
        judgments,
        esci_of,
        {102},
        21,
        7,
    )

    assert result.per_query[1] == pytest.approx(
        1 / metrics.ideal_dcg({"P1": 1.0}) * (1 / 1.5849625007)
    )  # rank 2
    assert result.mean_hits == 5
    assert result.in_stock_top10 == pytest.approx(4 / 5)  # 102 is sold out
    assert result.no_result == 0


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Two dev queries judged on P1 (template 101); 60 products so the reference sample (50) can be drawn."""
    processed = tmp_path / "data" / "processed"
    queries = [(1, "blue lamp shade"), (2, "garden chair")]
    _write_parquet(
        processed / "queries-dev.parquet",
        [{"query_id": qid, "query": text, "query_normalized": text} for qid, text in queries],
    )
    _write_parquet(
        processed / "qrels.parquet",
        [
            {"query_set": "dev", "query_id": qid, "product_id": "P1", "esci_label": "E", "gain": 1.0}
            for qid, _ in queries
        ],
    )
    _write_parquet(
        processed / "odoo_id_map.parquet",
        [{"product_id": f"P{n}", "template_id": 100 + n, "variant_id": 200 + n} for n in range(1, 61)],
    )
    outputs = {
        name: {"sha256": hashlib.sha256((processed / name).read_bytes()).hexdigest()}
        for name in ("queries-dev.parquet", "qrels.parquet")
    }
    (processed / "slice-manifest.json").write_text(json.dumps({"outputs": outputs}), encoding="utf-8")
    for relative in (
        ndcg.SLICE_CONFIG,
        ndcg.QUERY_BUILDER,
        ndcg.MODULE_CONFIG,
        tuning.TUNING_FILE,
        Path("compose.yaml"),
    ):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, tmp_path / relative)
    return tmp_path


def _context() -> tuning.Context:
    facts = ndcg.ShopFacts(1, 21, "19.0.0.5.0", 6, "9.5.5", "shop-products-v5", 2, 6, 1)
    return tuning.Context(search=FakeSearch(), sold_out={105}, facts=facts)


def test_full_experiment_writes_the_run_and_the_table(repo: Path) -> None:
    lines: list[str] = []

    assert tuning.run_tune(repo, "e01-exact-words", write=lines.append, context=_context()) == 0

    (folder,) = sorted((repo / "results").glob("tune-e01-exact-words-*"))
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert run["kind"] == "tune"
    assert run["configs"]["variant"]["fuzziness"] is None
    assert set(run["result"]) >= {"dev", "dev-typo", "reference", "decision", "reason"}
    assert (
        run["result"]["dev"]["diff"]["mean"] > 0
    )  # the fake ranks the exact product first without fuzziness
    table = (repo / tuning.SUMMARY_FILE).read_text(encoding="utf-8")
    assert "`e01-exact-words`" in table and "Variants run: 1 of a budget of 15." in table
    assert "Decision:" in "".join(lines)


def test_budget_is_enforced(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = (repo / tuning.TUNING_FILE).read_text(encoding="utf-8").replace("budget = 15", "budget = 1")
    (repo / tuning.TUNING_FILE).write_text(text, encoding="utf-8")
    assert tuning.run_tune(repo, "e01-exact-words", write=lambda _: None, context=_context()) == 0
    assert (
        tuning.run_tune(repo, "e01-exact-words", write=lambda _: None, context=_context()) == 0
    )  # re-run: allowed

    assert tuning.run_tune(repo, "e02-prefix-0", write=lambda _: None, context=_context()) == 1
    assert "budget" in capsys.readouterr().err


def test_unknown_variant(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert tuning.run_tune(repo, "e99", write=lambda _: None, context=_context()) == 1
    assert "unknown variant" in capsys.readouterr().err


def test_table_is_rewritten_from_the_run_folders(repo: Path) -> None:
    assert tuning.run_tune(repo, "e01-exact-words", write=lambda _: None, context=_context()) == 0
    (repo / tuning.SUMMARY_FILE).unlink()

    assert tuning.run_tune(repo, None, write=lambda _: None, table_only=True) == 0
    assert "`e01-exact-words`" in (repo / tuning.SUMMARY_FILE).read_text(encoding="utf-8")


def test_table_needs_a_run(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert tuning.run_tune(repo, None, write=lambda _: None, table_only=True) == 1
    assert "nothing to tabulate" in capsys.readouterr().err
