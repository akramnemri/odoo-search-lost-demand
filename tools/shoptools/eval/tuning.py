"""`uv run shop eval tune <variant>`: one relevance-tuning experiment on the dev queries (Task 3.5).

An experiment compares a variant of the `es_tuned` query with its parent (tools/shoptools/eval/tuning.toml,
pre-registered in docs/evaluation/experiments.md), both through Elasticsearch directly (`direct` mode) with
the module's own query code (`query_builder.py`, `TunedConfig`). Measured for each, on two query sets:

- `dev` — the 300 dev queries (protocol §3);
- `dev-typo` — the same queries with one seeded typo each, made at run time with the protocol's typo model
  (`shoptools/data/typos.py`, stream `dev-typos`), so typo tolerance is judged without touching the test sets;

NDCG@10 with its interval, the paired difference variant − parent (interval, randomization p, and the
difference on each half of dev: odd and even query ids), queries with no result, mean hits (capped at 1,000:
the weak tail), the share of in-stock products in the top 10, Elasticsearch's `took` p95, and reference@1
(50 seeded products searched by their internal reference).

The decision follows the pre-registered rule (`decide`): it is computed, never chosen by hand. Outputs: a run
folder `results/tune-<variant>-<UTC time>/` (`run.json`, `scores.json`, git-ignored) and the generated table
`results/summary/tuning-dev.md` (latest run of each variant). Dev data only; at most `budget` variants.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from shoptools import snapshot
from shoptools.data import slice_builder
from shoptools.data.typos import make_typo
from shoptools.eval import metrics, ndcg

TUNING_FILE = Path("tools") / "shoptools" / "eval" / "tuning.toml"
SUMMARY_FILE = Path("results") / "summary" / "tuning-dev.md"
GOALS = ("none", "typo", "tail", "reference")
TUNED_ENGINES = ("es_tuned", "es_tuned_stock")
DEV, DEV_TYPO = "dev", "dev-typo"
REFERENCE_SAMPLE = 50

# The pre-registered rule (docs/evaluation/experiments.md, plan D2 and D4).
MIN_GAIN = 0.005  # a relevance change is kept from +0.005 dev NDCG ...
MAX_LOSS = 0.005  # ... and nothing may lose more than this (dev, or dev-typo unless the goal is typos)
TAIL_DROP = 0.25  # "tail" goal: mean hits down by at least 25 %
REFERENCE_TARGET = 0.9  # "reference" goal: 90 % of the sampled products first when searched by reference
STOCK_GAIN = 0.02  # rule (b) is a candidate only from +0.02 dev NDCG over rule (a) ...
STOCK_SHARE = 0.95  # ... with at least 95 % in-stock products in the top 10


class TuneError(Exception):
    """The experiment cannot run; the message says what to do."""


@dataclass(frozen=True)
class Variant:
    name: str
    stage: int
    parent: str
    engine: str
    goal: str
    hypothesis: str
    changes: dict[str, Any]


def load_variants(path: Path, builtins: Mapping[str, Any]) -> tuple[int, dict[str, Variant]]:
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        budget = int(parsed["budget"])
        entries = parsed["variants"]
    except (OSError, KeyError, ValueError) as error:  # tomllib.TOMLDecodeError is a ValueError
        raise TuneError(f"{path} is not valid: {error}") from error
    variants: dict[str, Variant] = {}
    for name, entry in entries.items():
        try:
            variant = Variant(
                name=name,
                stage=int(entry["stage"]),
                parent=str(entry["parent"]),
                engine=str(entry["engine"]),
                goal=str(entry["goal"]),
                hypothesis=str(entry["hypothesis"]),
                changes=dict(entry["changes"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TuneError(f"variant {name}: {error!r} missing or invalid") from error
        if variant.engine not in TUNED_ENGINES:
            raise TuneError(f"variant {name}: engine must be one of {TUNED_ENGINES}")
        if variant.goal not in GOALS:
            raise TuneError(f"variant {name}: goal must be one of {GOALS}")
        if variant.parent not in builtins and variant.parent not in variants:
            raise TuneError(
                f"variant {name}: parent {variant.parent!r} must be v0 or a variant defined above"
            )
        variants[name] = variant
    return budget, variants


def _value(key: str, value: Any) -> Any:
    if value == "none":
        return None
    if key == "fields":
        return tuple(value)
    return value


def resolve(name: str, variants: Mapping[str, Variant], builtins: Mapping[str, Any]) -> Any:
    """The `TunedConfig` of a builtin (`v0`) or of a variant: its parent's with its changes applied."""
    if name in builtins:
        return builtins[name]
    variant = variants[name]
    parent = resolve(variant.parent, variants, builtins)
    known = set(parent.__dataclass_fields__)
    unknown = set(variant.changes) - known
    if unknown:
        raise TuneError(f"variant {name}: unknown setting(s) {sorted(unknown)}; known: {sorted(known)}")
    try:
        return replace(parent, **{key: _value(key, value) for key, value in variant.changes.items()})
    except (TypeError, ValueError) as error:
        raise TuneError(f"variant {name}: {error}") from error


def dev_typo_queries(
    queries: Sequence[tuple[int, str]], seed: int, min_letters: int
) -> list[tuple[int, str]]:
    """The dev queries with one seeded typo each (protocol §6.3 model; unchanged without a long word)."""
    rng = slice_builder.derived_rng(seed, "dev-typos")
    typed = []
    for query_id, text in queries:
        typo = make_typo(text, rng, min_letters)
        typed.append((query_id, typo.text if typo is not None else text))
    return typed


def reference_sample(
    id_map: Mapping[int, str], seed: int, size: int = REFERENCE_SAMPLE
) -> list[tuple[int, str]]:
    """Seeded products (template id, internal reference = ESCI product id) for the reference check."""
    rng = slice_builder.derived_rng(seed, "ref-check")
    return sorted(rng.sample(sorted(id_map.items()), size))


# --- searching ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hits:
    ids: list[int]  # template ids, Elasticsearch's order (stock rule applied), at most max_hits
    took_ms: int | None


Search = Callable[[Any, str, str], Hits]  # (TunedConfig, engine, text) -> hits


def es_search(es: ndcg.EsPost, query_builder: ModuleType, website_id: int, max_hits: int) -> Search:
    def search(tuned: Any, engine: str, text: str) -> Hits:
        clean = query_builder.clean_query(text)
        if not clean:
            return Hits(ids=[], took_ms=None)
        filters = query_builder.SearchFilters(website_id=website_id)
        body = query_builder.build_search(engine, clean, filters, max_hits, tuned=tuned)
        response = es(f"/{ndcg.PRODUCT_ALIAS}/_search", body)
        try:
            ids = query_builder.hit_ids(response, in_stock_first=query_builder.stock_first(engine, tuned))
        except ValueError as error:
            raise TuneError(f"unexpected Elasticsearch answer: {error}") from error
        took = response.get("took")
        return Hits(ids=ids, took_ms=took if isinstance(took, int) else None)

    return search


def sold_out_ids(es: ndcg.EsPost) -> set[int]:
    response = es(
        f"/{ndcg.PRODUCT_ALIAS}/_search",
        {"query": {"term": {"in_stock": False}}, "size": 10_000, "_source": False},
    )
    return {int(hit["_id"]) for hit in response["hits"]["hits"]}


# --- measuring ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SetResult:
    query_set: str
    ndcg: metrics.Interval
    per_query: dict[int, float]  # query id -> NDCG@10
    no_result: int
    mean_hits: float
    in_stock_top10: float  # share of in-stock products among the top-10 results
    took_p95: float | None


def _p95(values: Sequence[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)])  # nearest rank


def measure(
    label: str,
    search: Search,
    tuned: Any,
    engine: str,
    query_set: str,
    queries: Sequence[tuple[int, str]],
    judgments: Mapping[int, Mapping[str, float]],
    esci_of: Mapping[int, str],
    sold_out: set[int],
    page_size: int,
    seed: int,
) -> SetResult:
    per_query: dict[int, float] = {}
    no_result, hits_total, top10, top10_in_stock, took = 0, 0, 0, 0, []
    for query_id, text in queries:
        hits = search(tuned, engine, text)
        page = hits.ids[:page_size]
        ranking = [esci_of.get(template_id, f"odoo-template-{template_id}") for template_id in page]
        value = metrics.ndcg(ranking, judgments.get(query_id, {}))
        if value is not None:
            per_query[query_id] = value
        no_result += int(not hits.ids)
        hits_total += len(hits.ids)
        top10 += len(page[: metrics.CUTOFF])
        top10_in_stock += sum(1 for template_id in page[: metrics.CUTOFF] if template_id not in sold_out)
        if hits.took_ms is not None:
            took.append(hits.took_ms)
    if not per_query:
        raise TuneError(f"{label}: no query could be scored")
    rng = slice_builder.derived_rng(seed, f"tune-bootstrap:{label}:{query_set}")
    return SetResult(
        query_set=query_set,
        ndcg=metrics.bootstrap_interval(list(per_query.values()), rng),
        per_query=per_query,
        no_result=no_result,
        mean_hits=hits_total / len(queries),
        in_stock_top10=top10_in_stock / top10 if top10 else 1.0,
        took_p95=_p95(took),
    )


@dataclass(frozen=True)
class Difference:
    query_set: str
    comparison: metrics.Comparison
    odd_half: float  # mean difference over odd query ids
    even_half: float


def difference(variant: SetResult, parent: SetResult, name: str, seed: int) -> Difference:
    comparison = metrics.compare(
        name,
        "parent",
        variant.per_query,
        parent.per_query,
        slice_builder.derived_rng(seed, f"tune-difference:{name}:{variant.query_set}"),
        slice_builder.derived_rng(seed, f"tune-permutation:{name}:{variant.query_set}"),
    )
    shared = sorted(set(variant.per_query) & set(parent.per_query))

    def half(remainder: int) -> float:
        chosen = [query for query in shared if query % 2 == remainder]
        return metrics.mean([variant.per_query[query] - parent.per_query[query] for query in chosen])

    return Difference(variant.query_set, comparison, odd_half=half(1), even_half=half(0))


def reference_at_1(search: Search, tuned: Any, engine: str, sample: Sequence[tuple[int, str]]) -> float:
    found = sum(1 for template_id, ref in sample if search(tuned, engine, ref).ids[:1] == [template_id])
    return found / len(sample)


@dataclass(frozen=True)
class Outcome:
    decision: str  # keep, drop, candidate (b), keep (a)
    reason: str


def decide(
    variant: Variant,
    dev: Difference,
    typo: Difference,
    hits: tuple[float, float],  # (parent, variant) mean hits on dev
    reference: tuple[float, float],  # (parent, variant) reference@1
    in_stock_top10: float,  # variant, dev
) -> Outcome:
    """The pre-registered rule (experiments.md): computed, never chosen by hand."""
    gain = dev.comparison.difference.mean
    typo_gain = typo.comparison.difference.mean
    if variant.stage == 3:
        if gain >= STOCK_GAIN and in_stock_top10 >= STOCK_SHARE:
            return Outcome(
                "candidate (b)", f"+{gain:.4f} with {in_stock_top10:.1%} in stock: supervisor decides"
            )
        return Outcome(
            "keep (a)", f"rule (b) needs +{STOCK_GAIN} and {STOCK_SHARE:.0%} in stock in the top 10"
        )
    if gain < -MAX_LOSS:
        return Outcome("drop", f"dev NDCG {gain:+.4f}, below -{MAX_LOSS}")
    if variant.goal != "typo" and typo_gain < -MAX_LOSS:
        return Outcome("drop", f"dev-typo NDCG {typo_gain:+.4f}, below -{MAX_LOSS} (typo tolerance, FR2)")
    if gain >= MIN_GAIN and dev.odd_half >= 0 and dev.even_half >= 0:
        return Outcome("keep", f"dev NDCG {gain:+.4f}, not negative on either half")
    if variant.goal == "typo" and typo_gain >= MIN_GAIN:
        return Outcome("keep", f"goal typo: dev-typo NDCG {typo_gain:+.4f}")
    if variant.goal == "tail" and hits[1] <= (1 - TAIL_DROP) * hits[0]:
        return Outcome("keep", f"goal tail: mean hits {hits[0]:.0f} -> {hits[1]:.0f}")
    if variant.goal == "reference" and reference[1] >= REFERENCE_TARGET > reference[0]:
        return Outcome("keep", f"goal reference: reference@1 {reference[0]:.0%} -> {reference[1]:.0%}")
    if gain >= MIN_GAIN:
        return Outcome("drop", f"dev NDCG {gain:+.4f} but negative on one half (not robust)")
    return Outcome("drop", f"dev NDCG {gain:+.4f}: under +{MIN_GAIN}, goal {variant.goal} not met")


# --- the run ------------------------------------------------------------------------------------------------


def _short(value: float | None, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_summary(runs: Sequence[Mapping[str, Any]], budget: int) -> str:
    lines = [
        "# Relevance tuning on the dev queries (Task 3.5)",
        "",
        "Generated by `uv run shop eval tune` (tools/shoptools/eval/tuning.py) from the latest run of each",
        "variant; do not edit by hand.",
        "Pre-registered variants and rule: `tools/shoptools/eval/tuning.toml`,",
        "`docs/evaluation/experiments.md`. Direct mode (Elasticsearch, the module's query code);",
        "**dev data only**.",
        f"Variants run: {len(runs)} of a budget of {budget}.",
        "",
        "Δ = variant − parent, NDCG@10 on the 300 dev queries, 95 % bootstrap interval, two-sided paired "
        "randomization p; halves = Δ on odd / even query ids; dev-typo = the dev queries with one seeded "
        "typo.",
        "",
        "| Stage | Variant | Parent | Dev NDCG parent → variant | Δ dev [95 % CI], p | Halves | Δ dev-typo "
        "| Mean hits | Ref@1 | In stock top 10 | took p95 | Decision |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in sorted(runs, key=lambda item: (item["variant"]["stage"], item["variant"]["name"])):
        variant, result = run["variant"], run["result"]
        dev, typo = result["dev"], result["dev-typo"]
        git = run["git_sha"][:7] + ("-dirty" if run["git_dirty"] else "")
        lines.append(
            f"| {variant['stage']} | `{variant['name']}` ({git}) | `{variant['parent']}` | "
            f"{dev['parent']['ndcg']['mean']:.4f} → {dev['variant']['ndcg']['mean']:.4f} | "
            f"{dev['diff']['mean']:+.4f} [{dev['diff']['low']:+.4f}, {dev['diff']['high']:+.4f}], "
            f"p {dev['diff']['p']:.3f} | {dev['diff']['odd']:+.4f} / {dev['diff']['even']:+.4f} | "
            f"{typo['diff']['mean']:+.4f} | "
            f"{dev['parent']['mean_hits']:.0f} → {dev['variant']['mean_hits']:.0f} | "
            f"{result['reference']['parent']:.0%} → {result['reference']['variant']:.0%} | "
            f"{dev['variant']['in_stock_top10']:.1%} | {_short(dev['variant']['took_p95'], 0)} ms | "
            f"**{result['decision']}** — {result['reason']} |"
        )
    lines += [
        "",
        "Changes of each variant (relative to its parent):",
        "",
    ]
    for run in sorted(runs, key=lambda item: (item["variant"]["stage"], item["variant"]["name"])):
        variant = run["variant"]
        changes = json.dumps(variant["changes"], sort_keys=True)
        lines.append(f"- `{variant['name']}`: `{changes}` — {variant['hypothesis']}")
    lines.append("")
    return "\n".join(lines)


def _set_record(result: SetResult) -> dict[str, Any]:
    return {
        "ndcg": asdict(result.ndcg),
        "no_result": result.no_result,
        "mean_hits": result.mean_hits,
        "in_stock_top10": result.in_stock_top10,
        "took_p95": result.took_p95,
    }


def _diff_record(diff: Difference) -> dict[str, Any]:
    interval = diff.comparison.difference
    return {
        "mean": interval.mean,
        "low": interval.low,
        "high": interval.high,
        "p": diff.comparison.p_value,
        "odd": diff.odd_half,
        "even": diff.even_half,
    }


def latest_runs(repo_root: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted((repo_root / "results").glob("tune-*/run.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("kind") == "tune":
            latest[run["variant"]["name"]] = run  # sorted by folder name = by time: the last one wins
    return list(latest.values())


@dataclass
class Context:
    """What an experiment talks to; tests replace it with fakes."""

    search: Search
    sold_out: set[int]
    facts: ndcg.ShopFacts
    max_hits: int = 1000


def connect(repo_root: Path, query_builder: ModuleType) -> Context:
    from shoptools.catalog_import import CatalogImportError, json2_caller
    from shoptools.envfile import parse_env

    env_path = repo_root / ".env"
    if not env_path.is_file():
        raise TuneError(".env is missing: run `uv run shop env init`")
    password = parse_env(env_path.read_text(encoding="utf-8")).get("SHOP_TOOLS_ES_PASSWORD", "")
    if not password:
        raise TuneError(".env has no SHOP_TOOLS_ES_PASSWORD: run `uv run shop env init`")
    es = ndcg.es_caller(password)
    try:
        facts = ndcg.read_shop_facts(json2_caller(repo_root), es)
    except (CatalogImportError, ndcg.NdcgError) as error:
        raise TuneError(str(error)) from error
    config = ndcg.load_module_file(repo_root / ndcg.MODULE_CONFIG, "lost_demand_module_config")
    max_hits = int(config.OPTIONAL_NUMBERS["SEARCH_MAX_HITS"][0])
    return Context(
        search=es_search(es, query_builder, facts.website_id, max_hits),
        sold_out=sold_out_ids(es),
        facts=facts,
        max_hits=max_hits,
    )


def run_tune(
    repo_root: Path,
    name: str | None,
    list_only: bool = False,
    write: Callable[[str], None] | None = None,
    context: Context | None = None,
) -> int:
    write = write or ndcg._print
    try:
        return _run(repo_root, name, list_only, write, context)
    except (TuneError, ndcg.NdcgError) as error:
        print(f"shop eval tune: {error}", file=sys.stderr)
        return 1


def _run(
    repo_root: Path,
    name: str | None,
    list_only: bool,
    write: Callable[[str], None],
    context: Context | None,
) -> int:
    query_builder = ndcg.load_module_file(repo_root / ndcg.QUERY_BUILDER, "lost_demand_query_builder")
    builtins = {"v0": query_builder.TUNED_V0}
    budget, variants = load_variants(repo_root / TUNING_FILE, builtins)
    done = {run["variant"]["name"]: run for run in latest_runs(repo_root)}
    if list_only or not name:
        write(f"Variants ({len(done)} of a budget of {budget} run):\n")
        for variant in variants.values():
            state = done[variant.name]["result"]["decision"] if variant.name in done else "not run"
            write(f"  stage {variant.stage}  {variant.name:<24} parent {variant.parent:<20} {state}\n")
        return 0
    if name not in variants:
        raise TuneError(f"unknown variant {name!r}: see `uv run shop eval tune --list`")
    if name not in done and len(done) >= budget:
        raise TuneError(f"the budget of {budget} experiments is used: report, do not add runs (plan D3)")
    variant = variants[name]
    tuned = resolve(name, variants, builtins)
    parent = resolve(variant.parent, variants, builtins)

    started_at = datetime.now(UTC)
    started = time.monotonic()
    try:
        slice_config = slice_builder.load_config(repo_root / ndcg.SLICE_CONFIG)
    except slice_builder.SliceError as error:
        raise TuneError(str(error)) from error
    seed = slice_config.seed
    dev = ndcg.read_dev_set(repo_root)
    sets = {DEV: dev.queries, DEV_TYPO: dev_typo_queries(dev.queries, seed, slice_config.min_word_letters)}
    try:
        esci_of = ndcg.read_id_map(repo_root)
    except ndcg.BaselineError as error:
        raise TuneError(str(error)) from error
    context = context or connect(repo_root, query_builder)
    write(f"Experiment {name} (stage {variant.stage}, parent {variant.parent}, engine {variant.engine})\n")

    results: dict[str, dict[str, SetResult]] = {}
    for role, config in (("parent", parent), ("variant", tuned)):
        results[role] = {}
        for query_set, queries in sets.items():
            results[role][query_set] = measure(
                f"{name}:{role}",
                context.search,
                config,
                variant.engine,
                query_set,
                queries,
                dev.judgments,
                esci_of,
                context.sold_out,
                context.facts.page_size,
                seed,
            )
            write(f"  {role} {query_set}: NDCG@10 {results[role][query_set].ndcg.mean:.4f}\n")
    diffs = {
        query_set: difference(results["variant"][query_set], results["parent"][query_set], name, seed)
        for query_set in sets
    }
    sample = reference_sample(esci_of, seed)
    reference = (
        reference_at_1(context.search, parent, variant.engine, sample),
        reference_at_1(context.search, tuned, variant.engine, sample),
    )
    outcome = decide(
        variant,
        diffs[DEV],
        diffs[DEV_TYPO],
        (results["parent"][DEV].mean_hits, results["variant"][DEV].mean_hits),
        reference,
        results["variant"][DEV].in_stock_top10,
    )

    git = snapshot.git_sha(repo_root)
    run_id = f"tune-{name}-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    meta = {
        "run_id": run_id,
        "kind": "tune",
        "git_sha": git.removesuffix("-dirty"),
        "git_dirty": git.endswith("-dirty"),
        "command": f"uv run shop eval tune {name}",
        "variant": asdict(variant),
        "configs": {"parent": asdict(parent), "variant": asdict(tuned)},
        "tuning_sha256": hashlib.sha256((repo_root / TUNING_FILE).read_bytes()).hexdigest(),
        "query_builder_sha256": hashlib.sha256((repo_root / ndcg.QUERY_BUILDER).read_bytes()).hexdigest(),
        "seed": seed,
        "data": dev.checksums,
        "shop": asdict(context.facts),
        "sold_out_documents": len(context.sold_out),
        "max_hits": context.max_hits,
        "machine": ndcg._machine(repo_root),
        "result": {
            query_set: {
                "parent": _set_record(results["parent"][query_set]),
                "variant": _set_record(results["variant"][query_set]),
                "diff": _diff_record(diffs[query_set]),
            }
            for query_set in sets
        }
        | {
            "reference": {"parent": reference[0], "variant": reference[1], "sample": len(sample)},
            "decision": outcome.decision,
            "reason": outcome.reason,
        },
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round(time.monotonic() - started, 1),
    }
    folder = repo_root / "results" / run_id
    scores = {
        role: {query_set: result.per_query for query_set, result in by_set.items()}
        for role, by_set in results.items()
    }
    ndcg._write_text(folder / "scores.json", json.dumps(scores, indent=1) + "\n")
    ndcg._write_text(folder / "run.json", json.dumps(meta, indent=2) + "\n")
    runs = latest_runs(repo_root)
    ndcg._write_text(repo_root / SUMMARY_FILE, render_summary(runs, budget))
    dev_diff = diffs[DEV].comparison.difference
    write(
        f"  Δ dev {dev_diff.mean:+.4f} [{dev_diff.low:+.4f}, {dev_diff.high:+.4f}], "
        f"Δ dev-typo {diffs[DEV_TYPO].comparison.difference.mean:+.4f}, reference@1 "
        f"{reference[0]:.0%} -> {reference[1]:.0%}\n  Decision: {outcome.decision} — {outcome.reason}\n"
        f"Done in {meta['seconds']:.0f} s. Table: {SUMMARY_FILE.as_posix()}; run folder: results/{run_id}/\n"
    )
    return 0
