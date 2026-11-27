"""`uv run shop eval ndcg`: NDCG@10 of the shop's search engines on the dev queries (Task 3.4, protocol §6).

Modes (protocol §6.2):

- `http` — what a shopper sees: page 1 of the real `/shop?search=...` page (anonymous, read-only). The engine
  is chosen with the evaluation headers of Task 3.3 (`X-Lost-Demand-Key` = `LOAD_TEST_KEY` of `.env`,
  `X-Lost-Demand-Engine`); the response names the engine that answered (`X-Lost-Demand-Engine-Used`). If
  Elasticsearch failed and Odoo answered instead (`odoo_fallback`), the query is tried once more after a
  pause; a second fallback stops the run: mixing Odoo's results into an Elasticsearch row would corrupt it.
- `direct` — Elasticsearch only, as `shop_tools`, with **the module's own query code**
  (`addons/website_sale_lost_demand/services/query_builder.py`, loaded from its file: no copy that could
  drift),
  the same 1,000-hit cut and stock rule, cut to one shop page. Fast, for the tuning loop (Task 3.5). Odoo's
  filters are not applied: on the evaluation catalog every product is published, so both modes should agree;
  `both` measures it (the protocol's consistency check).
- `both` — `direct`, then `http`, and the consistency of the two per engine.

Each ranking keeps one shop page (`shop_ppg`, 21 products): NDCG@10 and judged@10 use the first 10, condensed
NDCG@10 the whole page. Products are mapped back to ESCI ids with `data/processed/odoo_id_map.parquet`.

Only the dev set is accepted: the test sets are run once, after the freeze (Task 8.2, protocol §3 and §8).
Inputs are checked against `data/processed/slice-manifest.json` before anything runs.

Outputs: `results/ndcg-<set>-<mode>-<UTC time>/` with `run.json` (docs/ai/04 §12), `rankings.jsonl` and
`scores.json` (git-ignored); the generated table `results/summary/ndcg-<set>-<mode>.md` (committed), written
only by a full run (no `--limit`).
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from shoptools import odoodb, snapshot, stack
from shoptools.data import slice_builder
from shoptools.doctor.system import RealSystem
from shoptools.envfile import parse_env
from shoptools.eval import metrics
from shoptools.eval.baseline_search import (
    ENGINE_HEADER,
    ENGINE_USED_HEADER,
    KEY_HEADER,
    BaselineError,
    parse_shop_page,
    read_id_map,
)

DEV = "dev"
REFUSED_SETS = ("test", "test-typo")
ODOO = "odoo"
DEFAULT_ENGINES = (ODOO, "es_plain", "es_tuned")
ALL_ENGINES = (*DEFAULT_ENGINES, "es_tuned_stock")
# The protocol's corrected family (§6.5); other pairs would be descriptive only.
FAMILY = (("es_tuned", "es_plain"), ("es_tuned", ODOO), ("es_plain", ODOO))
HTTP, DIRECT, BOTH = "http", "direct", "both"
MODES = (HTTP, DIRECT, BOTH)

MODULE_SERVICES = Path("addons") / "website_sale_lost_demand" / "services"
QUERY_BUILDER = MODULE_SERVICES / "query_builder.py"
MODULE_CONFIG = MODULE_SERVICES / "config.py"
SUMMARY_DIR = Path("results") / "summary"
SLICE_MANIFEST = slice_builder.PROCESSED_DIR / "slice-manifest.json"
DATA_FILES = (slice_builder.DEV_FILE, slice_builder.QRELS_FILE)
SLICE_CONFIG = Path("tools") / "shoptools" / "data" / "slice.toml"
PRODUCT_ALIAS = "shop-products"
TIMEOUT_SECONDS = 30
RETRY_PAUSE_SECONDS = 2.0
PROGRESS_EVERY = 50
_ODOO_IMAGE = re.compile(r"^\s*image:\s*(odoo-search-lost-demand/odoo:\S+)\s*$", re.MULTILINE)


class NdcgError(Exception):
    """The run cannot go on; the message says what to do."""


@dataclass(frozen=True)
class Ranking:
    products: list[str]  # ESCI product ids, best first (one shop page)
    engine_used: str
    fuzzy_term: str | None = None  # Odoo replaced the query by a similar word (engine odoo)
    took_ms: int | None = None  # Elasticsearch's own time (direct mode)


Fetch = Callable[[str, str], Ranking]  # (engine, query text) -> ranking


# --- inputs -------------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class DevSet:
    queries: list[tuple[int, str]]  # (query id, text as the shopper typed it), by query id
    judgments: dict[int, dict[str, float]]  # query id -> {ESCI product id: gain}
    checksums: dict[str, str]


def read_dev_set(repo_root: Path) -> DevSet:
    """The dev queries and their judgments, after checking the files against the slice manifest and the
    stored gains against the protocol's."""
    import pyarrow.parquet as pq

    processed = repo_root / slice_builder.PROCESSED_DIR
    try:
        manifest = json.loads((repo_root / SLICE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise NdcgError(
            f"{SLICE_MANIFEST.as_posix()} unreadable ({error}): run `uv run shop data build-slice`"
        ) from error
    checksums: dict[str, str] = {}
    for name in DATA_FILES:
        path = processed / name
        if not path.is_file():
            raise NdcgError(f"{path} is missing: run `uv run shop data build-slice`")
        checksums[name] = _sha256(path)
        expected = manifest.get("outputs", {}).get(name, {}).get("sha256")
        if checksums[name] != expected:
            raise NdcgError(f"{name} does not match {SLICE_MANIFEST.as_posix()}: rebuild the slice")
    queries = sorted(
        (int(row["query_id"]), str(row["query"]))
        for row in pq.read_table(processed / slice_builder.DEV_FILE).to_pylist()
    )
    judgments: dict[int, dict[str, float]] = {}
    for row in pq.read_table(processed / slice_builder.QRELS_FILE).to_pylist():
        if row["query_set"] != DEV:
            continue  # the test judgments are never read (protocol §3)
        if metrics.GAINS.get(row["esci_label"]) != row["gain"]:
            raise NdcgError(f"qrels gain {row['gain']} for label {row['esci_label']} is not the protocol's")
        judgments.setdefault(int(row["query_id"]), {})[str(row["product_id"])] = float(row["gain"])
    return DevSet(queries=queries, judgments=judgments, checksums=checksums)


def load_module_file(path: Path, name: str) -> ModuleType:
    """Import one of the module's pure service files by path (they use no relative imports)."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise NdcgError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


# --- fetching rankings --------------------------------------------------------------------------------------


def http_fetcher(key: str, esci_of: Mapping[int, str], base_url: str = stack.ODOO_URL) -> Fetch:
    def fetch(engine: str, query: str) -> Ranking:
        url = f"{base_url}/shop?{urllib.parse.urlencode({'search': query})}"
        request = urllib.request.Request(url, headers={KEY_HEADER: key, ENGINE_HEADER: engine})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8", errors="replace")
                used = response.headers.get(ENGINE_USED_HEADER) or ""
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise NdcgError(
                f"the shop did not answer ({error}): is the stack up? `uv run shop status`"
            ) from error
        try:
            page = parse_shop_page(body)
        except BaselineError as error:
            raise NdcgError(str(error)) from error
        products = [
            esci_of.get(template_id, f"odoo-template-{template_id}") for template_id in page.template_ids
        ]
        return Ranking(products=products, engine_used=used, fuzzy_term=page.fuzzy_term)

    return fetch


EsPost = Callable[[str, Mapping[str, Any] | None], Mapping[str, Any]]  # (path, body or None for GET) -> JSON


def es_caller(password: str, base_url: str = stack.ELASTICSEARCH_URL) -> EsPost:
    """Read-only calls as `shop_tools` (role in docker/es-setup/setup.sh: read on shop-*)."""
    auth = "Basic " + base64.b64encode(f"shop_tools:{password}".encode()).decode()

    def call(path: str, body: Mapping[str, Any] | None) -> Mapping[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            base_url + path,
            data=data,
            headers={"Content-Type": "application/json", "Authorization": auth},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise NdcgError(f"Elasticsearch call {path} failed ({error}): `uv run shop doctor`") from error

    return call


def direct_fetcher(
    es: EsPost,
    query_builder: ModuleType,
    website_id: int,
    max_hits: int,
    depth: int,
    esci_of: Mapping[int, str],
) -> Fetch:
    """The module's query, sent to Elasticsearch directly; the module's cut and stock rule, one page kept."""

    def fetch(engine: str, query: str) -> Ranking:
        if engine == ODOO:
            raise NdcgError("engine odoo exists only in http mode")
        text = query_builder.clean_query(query)
        if not text:
            return Ranking(products=[], engine_used=engine)
        filters = query_builder.SearchFilters(website_id=website_id)
        response = es(
            f"/{PRODUCT_ALIAS}/_search", query_builder.build_search(engine, text, filters, max_hits)
        )
        try:
            ids = query_builder.hit_ids(response, in_stock_first=query_builder.stock_first(engine))[:depth]
        except ValueError as error:  # MalformedResponse
            raise NdcgError(f"unexpected Elasticsearch answer: {error}") from error
        took = response.get("took")
        products = [esci_of.get(template_id, f"odoo-template-{template_id}") for template_id in ids]
        return Ranking(products=products, engine_used=engine, took_ms=took if isinstance(took, int) else None)

    return fetch


# --- the state of the shop, for run.json --------------------------------------------------------------------


@dataclass(frozen=True)
class ShopFacts:
    website_id: int
    page_size: int  # shop_ppg: products per page
    module_version: str
    published_products: int
    elasticsearch: str
    index: str  # the index behind the alias
    definition_version: int | None
    documents: int
    sold_out_documents: int


Call = Callable[[str, str, dict[str, Any]], Any]  # JSON-2 (model, method, body)


def read_shop_facts(call: Call, es: EsPost) -> ShopFacts:
    try:
        (website,) = call("website", "search_read", {"domain": [], "fields": ["id", "shop_ppg"], "limit": 1})
        (module,) = call(
            "ir.module.module",
            "search_read",
            {"domain": [["name", "=", "website_sale_lost_demand"]], "fields": ["installed_version"]},
        )
        published = call(
            "product.template",
            "search_count",
            {"domain": [["is_published", "=", True], ["sale_ok", "=", True]]},
        )
    except odoodb.SetupError as error:
        raise NdcgError(f"reading the shop over JSON-2 failed ({error}): `uv run shop doctor`") from error
    aliases = es(f"/_alias/{PRODUCT_ALIAS}", None)
    if len(aliases) != 1:
        raise NdcgError(f"alias {PRODUCT_ALIAS} must point to exactly one index: `uv run shop index rebuild`")
    (index,) = aliases
    mapping = es(f"/{index}/_mapping", None)
    meta = mapping.get(index, {}).get("mappings", {}).get("_meta", {})
    return ShopFacts(
        website_id=int(website["id"]),
        page_size=int(
            website.get("shop_ppg") or 21
        ),  # Odoo's own default (website_sale controllers/main.py:312)
        module_version=str(module.get("installed_version") or ""),
        published_products=int(published),
        elasticsearch=str(es("/", None).get("version", {}).get("number", "")),
        index=index,
        definition_version=meta.get("definition_version"),
        documents=int(es(f"/{PRODUCT_ALIAS}/_count", {"query": {"match_all": {}}})["count"]),
        sold_out_documents=int(
            es(f"/{PRODUCT_ALIAS}/_count", {"query": {"term": {"in_stock": False}}})["count"]
        ),
    )


# --- one run ------------------------------------------------------------------------------------------------


@dataclass
class ModeResult:
    mode: str
    rankings: dict[str, dict[int, Ranking]] = field(default_factory=dict)  # engine -> query id -> ranking
    retried: list[tuple[str, int]] = field(default_factory=list)  # (engine, query id) answered by the
    # fallback once, then by the engine: a missed 500 ms deadline worth looking at (Task 3.3)


def _modes(mode: str) -> tuple[str, ...]:
    return (DIRECT, HTTP) if mode == BOTH else (mode,)


def _engines_for(mode: str, engines: Sequence[str]) -> list[str]:
    return [engine for engine in engines if not (mode == DIRECT and engine == ODOO)]


def _fetch_checked(
    fetch: Fetch, engine: str, query: str, sleep: Callable[[float], None]
) -> tuple[Ranking, bool]:
    """The ranking of `engine`; one retry when another engine answered (Elasticsearch fallback)."""
    ranking = fetch(engine, query)
    if ranking.engine_used == engine:
        return ranking, False
    sleep(RETRY_PAUSE_SECONDS)
    ranking = fetch(engine, query)
    if ranking.engine_used != engine:
        answered = ranking.engine_used or "no engine header (is LOAD_TEST_KEY active in the odoo container?)"
        raise NdcgError(
            f"engine {engine} was not used for {query!r} twice (answered by {answered}): run stopped, "
            "nothing written. Check `uv run shop doctor`; after `uv run shop env init`, run "
            "`docker compose up -d odoo`"
        )
    return ranking, True


def collect(
    mode: str,
    fetch: Fetch,
    engines: Sequence[str],
    queries: Sequence[tuple[int, str]],
    write: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ModeResult:
    result = ModeResult(mode=mode)
    active = _engines_for(mode, engines)
    for engine in active:  # warm-up, not counted: a cold cache must not cause a fallback (Task 3.3)
        _fetch_checked(fetch, engine, queries[0][1], sleep)
    total = len(queries) * len(active)
    done = 0
    started = clock()
    for engine in active:
        result.rankings[engine] = {}
        for query_id, text in queries:
            ranking, retried = _fetch_checked(fetch, engine, text, sleep)
            result.rankings[engine][query_id] = ranking
            if retried:
                result.retried.append((engine, query_id))
            done += 1
            if done % PROGRESS_EVERY == 0 or done == total:
                elapsed = clock() - started
                left = elapsed / done * (total - done)
                write(f"  {mode}: {done}/{total} rankings, {elapsed:.0f} s, about {left:.0f} s left\n")
    return result


@dataclass(frozen=True)
class EngineSummary:
    engine: str
    scored: int  # queries with an NDCG (excluded: no relevant judged product)
    excluded: int
    ndcg: metrics.Interval
    judged: float | None  # mean over queries with at least one result
    condensed: float
    no_result: int  # queries for which the engine showed nothing


def summarise(
    result: ModeResult, judgments: Mapping[int, Mapping[str, float]], seed: int
) -> tuple[dict[str, list[metrics.QueryScore]], list[EngineSummary], list[metrics.Comparison]]:
    scores: dict[str, list[metrics.QueryScore]] = {}
    summaries: list[EngineSummary] = []
    per_engine: dict[str, dict[int, float]] = {}
    for engine, rankings in result.rankings.items():
        scores[engine] = [
            metrics.score(query_id, ranking.products, judgments.get(query_id, {}))
            for query_id, ranking in sorted(rankings.items())
        ]
        valid = [item for item in scores[engine] if item.ndcg is not None]
        if not valid:
            raise NdcgError(f"no query of engine {engine} could be scored")
        per_engine[engine] = {item.query_id: item.ndcg for item in valid if item.ndcg is not None}
        judged_values = [item.judged for item in valid if item.judged is not None]
        rng = slice_builder.derived_rng(seed, f"ndcg-bootstrap:{engine}")
        summaries.append(
            EngineSummary(
                engine=engine,
                scored=len(valid),
                excluded=len(scores[engine]) - len(valid),
                ndcg=metrics.bootstrap_interval(list(per_engine[engine].values()), rng),
                judged=metrics.mean(judged_values) if judged_values else None,
                condensed=metrics.mean([item.condensed for item in valid if item.condensed is not None]),
                no_result=sum(1 for item in scores[engine] if item.results == 0),
            )
        )
    comparisons = [
        metrics.compare(
            first,
            second,
            per_engine[first],
            per_engine[second],
            slice_builder.derived_rng(seed, f"ndcg-difference:{first}-{second}"),
            slice_builder.derived_rng(seed, f"ndcg-permutation:{first}-{second}"),
        )
        for first, second in FAMILY
        if first in per_engine and second in per_engine
    ]
    adjusted = metrics.holm({f"{item.first}-{item.second}": item.p_value for item in comparisons})
    comparisons = [replace(item, p_holm=adjusted[f"{item.first}-{item.second}"]) for item in comparisons]
    return scores, summaries, comparisons


@dataclass(frozen=True)
class Consistency:
    engine: str
    queries: int
    same_top10: int  # queries whose top 10 is identical in both modes
    ndcg_direct: float
    ndcg_http: float


def consistency(
    direct: ModeResult, http: ModeResult, judgments: Mapping[int, Mapping[str, float]]
) -> list[Consistency]:
    rows = []
    for engine, direct_rankings in direct.rankings.items():
        http_rankings = http.rankings.get(engine)
        if http_rankings is None:
            continue
        shared = sorted(set(direct_rankings) & set(http_rankings))
        same = sum(
            1
            for query_id in shared
            if direct_rankings[query_id].products[: metrics.CUTOFF]
            == http_rankings[query_id].products[: metrics.CUTOFF]
        )

        def mean_ndcg(rankings: Mapping[int, Ranking], queries: Sequence[int] = tuple(shared)) -> float:
            values = [metrics.ndcg(rankings[query].products, judgments.get(query, {})) for query in queries]
            return metrics.mean([value for value in values if value is not None])

        rows.append(
            Consistency(engine, len(shared), same, mean_ndcg(direct_rankings), mean_ndcg(http_rankings))
        )
    return rows


# --- writing ------------------------------------------------------------------------------------------------


def _write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, target)


def _interval(interval: metrics.Interval) -> str:
    return f"{interval.mean:.4f} [{interval.low:.4f}, {interval.high:.4f}]"


def _signed(interval: metrics.Interval) -> str:
    return f"{interval.mean:+.4f} [{interval.low:+.4f}, {interval.high:+.4f}]"


def render_summary(
    meta: Mapping[str, Any],
    sections: Sequence[tuple[str, list[EngineSummary], list[metrics.Comparison]]],
    agreement: Sequence[Consistency],
) -> str:
    git = str(meta["git_sha"])
    short = git[:7] + ("-dirty" if meta["git_dirty"] else "")
    lines = [
        f"# NDCG@10 on the {meta['config']['set']} queries — mode {meta['config']['mode']}",
        "",
        "Generated by `uv run shop eval ndcg` (tools/shoptools/eval/ndcg.py); do not edit by hand.",
        f"Run `{meta['run_id']}` at commit `{short}`, {meta['started_at']}, {meta['seconds']} s. "
        "**Dev queries only: a tuning baseline, not a reported result** (the test set is run once, "
        "Task 8.2).",
        "",
        f"- Queries: {meta['queries']} dev queries; gains E 1.0, S 0.1, C 0.01, I 0; one shop page "
        f"({meta['shop']['page_size']} products) per query; 95 % percentile bootstrap intervals "
        f"({metrics.RESAMPLES:,} resamples), paired randomization tests "
        f"({metrics.PERMUTATIONS:,} permutations), "
        f"seed {meta['seed']}.",
        f"- Engines: `es_tuned` is version 0, **not tuned yet** (Task 3.5 tunes it); `query_builder.py` "
        f"SHA-256 `{meta['config']['query_builder_sha256'][:12]}…`. Index `{meta['shop']['index']}` "
        f"(definition {meta['shop']['definition_version']}), {meta['shop']['documents']:,} documents, "
        f"{meta['shop']['sold_out_documents']:,} sold out; module {meta['shop']['module_version']}.",
        f"- Catalog: {meta['shop']['published_products']:,} published products (all judged for some query: "
        "few unrelated products, protocol §10).",
        "",
    ]
    for mode, summaries, comparisons in sections:
        lines += [
            f"## Mode `{mode}`",
            "",
            "| Engine | Queries scored | NDCG@10 [95 % CI] | judged@10 | condensed NDCG@10 "
            "| queries with no result |",
            "|---|---|---|---|---|---|",
        ]
        for item in summaries:
            judged = f"{item.judged:.3f}" if item.judged is not None else "—"
            lines.append(
                f"| `{item.engine}` | {item.scored} (+{item.excluded} excluded) | {_interval(item.ndcg)} | "
                f"{judged} | {item.condensed:.4f} | {item.no_result} |"
            )
        if comparisons:
            lines += [
                "",
                "| Comparison | Queries | Mean difference [95 % CI] | p (randomization) | p (Holm) |",
                "|---|---|---|---|---|",
            ]
            for item in comparisons:
                holm = f"{item.p_holm:.4f}" if item.p_holm is not None else "—"
                lines.append(
                    f"| `{item.first}` − `{item.second}` | {item.queries} | {_signed(item.difference)} | "
                    f"{item.p_value:.4f} | {holm} |"
                )
        lines.append("")
    if agreement:
        lines += [
            "## Consistency of the two modes (protocol §6.2)",
            "",
            "| Engine | Queries | Same top 10 in both modes | NDCG@10 direct | NDCG@10 http |",
            "|---|---|---|---|---|",
        ]
        for row in agreement:
            lines.append(
                f"| `{row.engine}` | {row.queries} | {row.same_top10} ({row.same_top10 / row.queries:.1%}) | "
                f"{row.ndcg_direct:.4f} | {row.ndcg_http:.4f} |"
            )
        lines.append("")
    if meta.get("fallback_retries"):
        retried = ", ".join(f"{engine} query {query_id}" for engine, query_id in meta["fallback_retried"])
        lines.append(
            f"Fallback retries in http mode: {meta['fallback_retries']} ({retried}), each answered by the "
            "engine on the retry; the scores use the retry's ranking."
        )
        lines.append("")
    return "\n".join(lines)


def _command(set_name: str, engines: Sequence[str], mode: str, limit: int | None) -> str:
    parts = ["uv run shop eval ndcg", f"--set {set_name}", f"--engine {','.join(engines)}", f"--mode {mode}"]
    if limit is not None:
        parts.append(f"--limit {limit}")
    return " ".join(parts)


def _machine(repo_root: Path) -> dict[str, Any]:
    system = RealSystem()
    ram = system.ram_bytes()
    env_path = repo_root / ".env"
    profile = (
        parse_env(env_path.read_text(encoding="utf-8")).get("RAM_PROFILE", "") if env_path.is_file() else ""
    )
    return {
        "os": system.os_description(),
        "cpu_count": os.cpu_count(),
        "ram_gb": round(ram / 1e9, 1) if ram else None,
        "profile": profile,
        "python": platform.python_version(),
    }


def _odoo_image(repo_root: Path) -> str:
    match = _ODOO_IMAGE.search((repo_root / stack.COMPOSE_FILE).read_text(encoding="utf-8"))
    return match.group(1) if match else ""


@dataclass
class Connections:
    """What a run talks to; tests replace it with fakes."""

    fetchers: dict[str, Fetch]
    facts: ShopFacts


def connect(
    repo_root: Path, modes: Sequence[str], esci_of: Mapping[int, str], query_builder: ModuleType
) -> Connections:
    from shoptools.catalog_import import CatalogImportError, json2_caller

    env_path = repo_root / ".env"
    if not env_path.is_file():
        raise NdcgError(".env is missing: run `uv run shop env init`")
    env = parse_env(env_path.read_text(encoding="utf-8"))
    password = env.get("SHOP_TOOLS_ES_PASSWORD", "")
    if not password:
        raise NdcgError(".env has no SHOP_TOOLS_ES_PASSWORD: run `uv run shop env init`")
    es = es_caller(password)
    try:
        facts = read_shop_facts(json2_caller(repo_root), es)
    except CatalogImportError as error:
        raise NdcgError(str(error)) from error
    fetchers: dict[str, Fetch] = {}
    if HTTP in modes:
        key = env.get("LOAD_TEST_KEY", "")
        if not key:
            raise NdcgError(
                ".env has no LOAD_TEST_KEY: run `uv run shop env init`, then `docker compose up -d odoo`"
            )
        fetchers[HTTP] = http_fetcher(key, esci_of)
    if DIRECT in modes:
        config = load_module_file(repo_root / MODULE_CONFIG, "lost_demand_module_config")
        max_hits = int(
            config.OPTIONAL_NUMBERS["SEARCH_MAX_HITS"][0]
        )  # the module's default (not overridden in compose)
        fetchers[DIRECT] = direct_fetcher(
            es, query_builder, facts.website_id, max_hits, facts.page_size, esci_of
        )
    return Connections(fetchers=fetchers, facts=facts)


def _print(text: str) -> None:
    # Flushed at once: a run takes minutes, and its progress must show in a log file, not only at the end.
    # Redirected to a file on Windows, stdout is cp1252: a character it lacks ("Δ") is replaced, never fatal
    # (Task 3.5: eleven runs crashed on their last line, after their results were written).
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding))
    sys.stdout.flush()


def run_ndcg(
    repo_root: Path,
    set_name: str = DEV,
    engines: Sequence[str] = DEFAULT_ENGINES,
    mode: str = HTTP,
    limit: int | None = None,
    write: Callable[[str], None] | None = None,
    connections: Connections | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    write = write or _print
    try:
        return _run(repo_root, set_name, engines, mode, limit, write, connections, sleep)
    except NdcgError as error:
        print(f"shop eval ndcg: {error}", file=sys.stderr)
        return 1


def _run(
    repo_root: Path,
    set_name: str,
    engines: Sequence[str],
    mode: str,
    limit: int | None,
    write: Callable[[str], None],
    connections: Connections | None,
    sleep: Callable[[float], None],
) -> int:
    if set_name in REFUSED_SETS:
        raise NdcgError(
            f"the {set_name} set is run once, after the configuration freeze (Task 8.2, protocol §3 and §8); "
            "use --set dev"
        )
    if set_name != DEV:
        raise NdcgError(f"unknown set {set_name!r}: use --set dev")
    unknown = [engine for engine in engines if engine not in ALL_ENGINES]
    if unknown or not engines:
        raise NdcgError(f"unknown engine(s) {unknown}: choose from {', '.join(ALL_ENGINES)} or all")
    if mode not in MODES:
        raise NdcgError(f"unknown mode {mode!r}: choose from {', '.join(MODES)}")
    if mode == DIRECT and not _engines_for(DIRECT, engines):
        raise NdcgError(
            "engine odoo exists only in http mode: use --mode http or add an Elasticsearch engine"
        )
    if limit is not None and limit < 1:
        raise NdcgError("--limit must be at least 1")

    started_at = datetime.now(UTC)
    started = time.monotonic()
    try:
        slice_config = slice_builder.load_config(repo_root / SLICE_CONFIG)
    except slice_builder.SliceError as error:
        raise NdcgError(str(error)) from error
    if slice_config.gains != dict(metrics.GAINS):
        raise NdcgError(
            f"[gains] of {SLICE_CONFIG.as_posix()} differ from the protocol's {dict(metrics.GAINS)}"
        )
    seed = slice_config.seed
    dev = read_dev_set(repo_root)
    queries = dev.queries[:limit] if limit else dev.queries
    try:
        esci_of = read_id_map(repo_root)
    except BaselineError as error:
        raise NdcgError(str(error)) from error
    query_builder = load_module_file(repo_root / QUERY_BUILDER, "lost_demand_query_builder")
    connections = connections or connect(repo_root, _modes(mode), esci_of, query_builder)

    write(f"NDCG@10, {set_name} set: {len(queries)} queries, engines {', '.join(engines)}, mode {mode}\n")
    results = []
    for current in _modes(mode):
        results.append(collect(current, connections.fetchers[current], engines, queries, write, sleep))

    sections = []
    all_scores: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for result in results:
        scores, summaries, comparisons = summarise(result, dev.judgments, seed)
        sections.append((result.mode, summaries, comparisons))
        all_scores[result.mode] = {
            engine: [asdict(item) for item in items] for engine, items in scores.items()
        }
    agreement = consistency(results[0], results[1], dev.judgments) if mode == BOTH else []

    seconds = time.monotonic() - started
    git = snapshot.git_sha(repo_root)
    run_id = f"ndcg-{set_name}-{mode}-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    meta = {
        "run_id": run_id,
        "kind": "ndcg",
        "git_sha": git.removesuffix("-dirty"),
        "git_dirty": git.endswith("-dirty"),
        "command": _command(set_name, engines, mode, limit),
        "config": {
            "set": set_name,
            "engines": list(engines),
            "mode": mode,
            "cutoff": metrics.CUTOFF,
            "gains": dict(metrics.GAINS),
            "resamples": metrics.RESAMPLES,
            "permutations": metrics.PERMUTATIONS,
            "query_builder_sha256": _sha256(repo_root / QUERY_BUILDER),
            "limit": limit,
        },
        "seed": seed,
        "versions": {
            "odoo_image": _odoo_image(repo_root),
            "module": connections.facts.module_version,
            "elasticsearch": connections.facts.elasticsearch,
            "python": platform.python_version(),
        },
        "data": {
            **{name: digest for name, digest in dev.checksums.items()},
            "odoo_id_map.parquet": _sha256(repo_root / slice_builder.PROCESSED_DIR / "odoo_id_map.parquet"),
        },
        "shop": asdict(connections.facts),
        "machine": _machine(repo_root),
        "queries": len(queries),
        "fallback_retries": sum(len(result.retried) for result in results),
        "fallback_retried": [list(item) for result in results for item in result.retried],
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round(seconds, 1),
    }
    folder = repo_root / "results" / run_id
    rankings = [
        json.dumps(
            {"mode": result.mode, "engine": engine, "query_id": query_id, **asdict(ranking)},
            ensure_ascii=False,
        )
        for result in results
        for engine, by_query in result.rankings.items()
        for query_id, ranking in sorted(by_query.items())
    ]
    _write_text(folder / "rankings.jsonl", "\n".join(rankings) + "\n")
    _write_text(folder / "scores.json", json.dumps(all_scores, indent=1) + "\n")
    _write_text(folder / "run.json", json.dumps(meta, indent=2) + "\n")
    summary = render_summary(meta, sections, agreement)
    for title, summaries, comparisons in sections:
        write(f"{title}: " + "; ".join(f"{item.engine} {_interval(item.ndcg)}" for item in summaries) + "\n")
        for item in comparisons:
            write(f"  {item.first} - {item.second}: {_signed(item.difference)}, p Holm {item.p_holm:.4f}\n")
    if limit is not None:  # a quick look must not replace the committed table
        write(f"Done in {seconds:.0f} s. Run folder: results/{run_id}/ (table unchanged: --limit)\n")
        return 0
    table = SUMMARY_DIR / f"ndcg-{set_name}-{mode}.md"
    _write_text(repo_root / table, summary)
    write(f"Done in {seconds:.0f} s. Table: {table.as_posix()}; run folder: results/{run_id}/\n")
    return 0
