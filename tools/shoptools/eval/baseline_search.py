"""`uv run shop eval baseline-search`: what Odoo's own shop search finds, before any of our work (Task 2.5).

Every query goes to the real shop page `/shop?search=...` as an anonymous shopper (protocol §6.2, `http`
mode), on the catalog of `baseline-catalog`. From each page the script reads what a shopper sees:
- the number of results Odoo reports, or none;
- whether Odoo replaced the query by a similar word ("No results found for X. Showing results for Y"), the
  fallback of `website.py::_search_with_fuzzy` when the exact search finds nothing;
- the products on page 1 (20 per page), turned back into ESCI ids through
  `data/processed/odoo_id_map.parquet`, and the rank of the first expected product among them.

Two sets of queries, **dev data only** (the test queries and their products stay unseen, protocol §3):
1. the hand-picked queries of `docs/report/notes/baseline-queries.toml` (typos, vocabulary mismatch,
   singular and plural, brand names, long or negation queries), each with the products a shopper wants and a
   "control" query that differs only by the problem under study;
2. all dev queries, with their Exact (E) products from the qrels: how often a search finds nothing, is
   replaced by another word, or shows an exact match on page 1, by query length. These rates show how often
   the failures of the hand-picked examples happen, so the examples are not a cherry-picked story.

Outputs: `results/<run-id>/observations.json` and `run.json` (git-ignored), and the generated table
`results/summary/baseline-search.md` (committed; a `--no-dev` run leaves it unchanged). Requests are
read-only.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import platform
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shoptools import snapshot, stack
from shoptools.data import slice_builder
from shoptools.data.normalize import normalize_query

QUERY_FILE = Path("docs") / "report" / "notes" / "baseline-queries.toml"
SUMMARY_FILE = Path("results") / "summary" / "baseline-search.md"
ID_MAP = slice_builder.PROCESSED_DIR / "odoo_id_map.parquet"
GROUPS = ("typo", "vocabulary", "plural", "brand", "long")
NEGATIONS = frozenset({"without", "not", "no", "non"})
TIMEOUT_SECONDS = 30
SNAPSHOT = "baseline-catalog"

Fetch = Callable[[str], str]  # query -> HTML of /shop?search=query

# Outcomes of a search, also the column names of the dev-query table.
NO_RESULTS = "no results"
REPLACED = "replaced by another word"


class BaselineError(Exception):
    """The query file, the inputs or the shop are not as expected; the message says what to do."""


# --- reading a shop page -----------------------------------------------------------------------------------

_COUNT = re.compile(
    r"Search results for </span>'<strong>(.*?)</strong>'\s*(?:<small[^>]*>\s*\((\d+)\)</small>)?"
)
# `[^<]*` instead of `.*?`: Odoo escapes the term, so it holds no "<"; no backtracking (SonarCloud S8786).
_FUZZY = re.compile(
    r"No results found for '<span>([^<]*)</span>'\.\s*Showing results for '<span>([^<]*)</span>'"
)
# A product link: /shop/<slug>-<id>, or /shop/<category>/<slug>-<id> on a category page
# (website_sale/models/product_template.py:1117). Odoo keeps non-ASCII letters in slugs (12 of the 19,869
# catalog products have Chinese, Hindi or Cyrillic ones, found in Task 3.4): a slug is anything but / ? # ".
_PRODUCT = re.compile(r'href="/shop/(?!category/|cart|checkout|wishlist|page/)(?:[^"/?#]+/)?[^"/?#]*?-(\d+)"')
_GRID = 'id="o_wsale_products_grid"'


@dataclass(frozen=True)
class SearchPage:
    term: str  # the term Odoo searched for (the replacement word when it fell back)
    total: int  # results Odoo reports (0 when it shows no count)
    fuzzy_term: str | None  # the word Odoo used instead of the query, if it fell back
    template_ids: list[int]  # products on the page, in display order


def parse_shop_page(page: str) -> SearchPage:
    count = _COUNT.search(page)
    if count is None:
        raise BaselineError("not a shop search page: no 'Search results for' header (is the shop running?)")
    fuzzy = _FUZZY.search(page)
    grid_start = page.find(_GRID)
    ids: list[int] = []
    if grid_start >= 0:
        for match in _PRODUCT.finditer(page, grid_start):
            template_id = int(match.group(1))
            if template_id not in ids:  # image and title link to the same product
                ids.append(template_id)
    return SearchPage(
        term=html.unescape(count.group(1)),
        total=int(count.group(2)) if count.group(2) else 0,
        fuzzy_term=html.unescape(fuzzy.group(2)) if fuzzy else None,
        template_ids=ids,
    )


def http_fetcher(base_url: str = stack.ODOO_URL) -> Fetch:
    def fetch(query: str) -> str:
        url = f"{base_url}/shop?{urllib.parse.urlencode({'search': query})}"
        request = urllib.request.Request(url, headers={"User-Agent": "shoptools-baseline-search"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as error:
            raise BaselineError(
                f"the shop at {base_url} did not answer: {error} (run `uv run shop up`)"
            ) from error

    return fetch


# --- observing queries -------------------------------------------------------------------------------------


@dataclass
class Observation:
    query: str
    expected: list[str]  # ESCI ids a shopper looks for
    total: int
    fuzzy_term: str | None
    page_products: list[str | None]  # ESCI ids on page 1 (None: a product not in the id map)
    first_expected_rank: int | None  # 1-based rank on page 1 of the first expected product

    @property
    def outcome(self) -> str:
        if self.total == 0:
            return NO_RESULTS
        if self.fuzzy_term:
            return REPLACED
        if self.first_expected_rank is None:
            return "results, expected product not on page 1"
        return "expected product on page 1"


def observe(query: str, expected: Iterable[str], fetch: Fetch, esci_of: dict[int, str]) -> Observation:
    wanted = list(expected)
    page = parse_shop_page(fetch(query))
    products = [esci_of.get(template_id) for template_id in page.template_ids]
    ranks = [rank for rank, product in enumerate(products, start=1) if product in set(wanted)]
    return Observation(query, wanted, page.total, page.fuzzy_term, products, ranks[0] if ranks else None)


# --- inputs ------------------------------------------------------------------------------------------------


@dataclass
class HandPicked:
    group: str
    query: str
    expected: list[str]
    source: str
    why: str
    control: str | None = None


@dataclass
class DevData:
    queries: list[dict[str, Any]]  # dev queries (query_id, query)
    exact: dict[int, list[str]]  # dev query id -> its E products
    dev_products: set[str] = field(default_factory=set)
    test_products: set[str] = field(default_factory=set)
    test_texts: set[str] = field(default_factory=set)


def read_dev_data(repo_root: Path) -> DevData:
    import pyarrow.parquet as pq

    processed = repo_root / slice_builder.PROCESSED_DIR
    try:
        dev = pq.read_table(processed / slice_builder.DEV_FILE).to_pylist()
        test = pq.read_table(processed / slice_builder.TEST_FILE).to_pylist()
        qrels = pq.read_table(processed / slice_builder.QRELS_FILE).to_pylist()
    except OSError as error:
        raise BaselineError(f"slice outputs missing ({error}): run `uv run shop data build-slice`") from error
    data = DevData(queries=dev, exact={}, test_texts={row["query_normalized"] for row in test})
    for row in qrels:
        if row["query_set"] == "dev":
            data.dev_products.add(row["product_id"])
            if row["esci_label"] == "E":
                data.exact.setdefault(row["query_id"], []).append(row["product_id"])
        else:
            data.test_products.add(row["product_id"])
    return data


def read_id_map(repo_root: Path) -> dict[int, str]:
    import pyarrow.parquet as pq

    path = repo_root / ID_MAP
    if not path.is_file():
        raise BaselineError(f"{path} is missing: run `uv run shop import catalog`")
    return {row["template_id"]: row["product_id"] for row in pq.read_table(path).to_pylist()}


def load_hand_picked(path: Path, dev: DevData) -> list[HandPicked]:
    """The query file, checked: known groups, dev-only products, no test query text (protocol §3)."""
    picked = _read_hand_picked(path)
    problems = [problem for entry in picked for problem in _entry_problems(entry, dev)]
    if problems:
        raise BaselineError("query file refused:\n  " + "\n  ".join(problems))
    return picked


def _read_hand_picked(path: Path) -> list[HandPicked]:
    try:
        rows = tomllib.loads(path.read_text(encoding="utf-8"))["query"]
        return [
            HandPicked(
                group=row["group"],
                query=row["query"],
                expected=list(row["expected"]),
                source=row["source"],
                why=row["why"],
                control=row.get("control"),
            )
            for row in rows
        ]
    except (OSError, KeyError, TypeError, ValueError) as error:  # TOMLDecodeError is a ValueError
        raise BaselineError(f"{path} is not valid: {error}") from error


def _entry_problems(entry: HandPicked, dev: DevData) -> list[str]:
    problems = []
    if entry.group not in GROUPS:
        problems.append(f"{entry.query!r}: unknown group {entry.group!r} (one of {', '.join(GROUPS)})")
    if not entry.expected:
        problems.append(f"{entry.query!r}: no expected product")
    problems += [
        f"{entry.query!r}: {product} is not a dev-only judged product"
        for product in entry.expected
        if product not in dev.dev_products or product in dev.test_products
    ]
    problems += [
        f"{text!r} is a test query: the test set stays unseen"
        for text in filter(None, (entry.query, entry.control))
        if normalize_query(text) in dev.test_texts
    ]
    return problems


# --- aggregate over the dev queries ------------------------------------------------------------------------


def length_bucket(query: str) -> str:
    words = len(query.split())
    if words <= 2:
        return "1–2 words"
    if words <= 4:
        return "3–4 words"
    return "5+ words"


def dev_rates(observations: list[Observation]) -> dict[str, dict[str, Any]]:
    """Outcome shares per length bucket, for all queries, and for queries with a negation word."""
    buckets: dict[str, list[Observation]] = {"all": observations}
    for item in observations:
        buckets.setdefault(length_bucket(item.query), []).append(item)
        if NEGATIONS & set(normalize_query(item.query).split()):
            buckets.setdefault("with a negation word", []).append(item)
    order = ["all", "1–2 words", "3–4 words", "5+ words", "with a negation word"]
    rates = {}
    for name in order:
        items = buckets.get(name, [])
        n = len(items)
        rates[name] = {
            "queries": n,
            NO_RESULTS: sum(o.outcome == NO_RESULTS for o in items),
            REPLACED: sum(o.outcome == REPLACED for o in items),
            "exact match on page 1": sum(o.outcome == "expected product on page 1" for o in items),
            "median results": sorted(o.total for o in items)[n // 2] if n else 0,
        }
    return rates


# --- command -----------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_baseline_search(
    repo_root: Path,
    with_dev: bool = True,
    fetch: Fetch | None = None,
    write: Callable[[str], None] = sys.stdout.write,
) -> int:
    started_at = datetime.now(UTC)
    started = time.monotonic()
    try:
        dev = read_dev_data(repo_root)
        esci_of = read_id_map(repo_root)
        picked = load_hand_picked(repo_root / QUERY_FILE, dev)
        fetch = fetch or http_fetcher()
        write(f"Hand-picked queries: {len(picked)} (+ controls), through /shop?search=\n")
        hand = []
        for entry in picked:
            main = observe(entry.query, entry.expected, fetch, esci_of)
            control = observe(entry.control, entry.expected, fetch, esci_of) if entry.control else None
            hand.append((entry, main, control))
            write(f"  {entry.group:<10} {entry.query[:44]:<44} {main.outcome}\n")
        dev_observations: list[Observation] = []
        if with_dev:
            write(f"All dev queries: {len(dev.queries)} ...\n")
            for row in sorted(dev.queries, key=lambda item: item["query_id"]):
                dev_observations.append(
                    observe(row["query"], dev.exact.get(row["query_id"], []), fetch, esci_of)
                )
    except BaselineError as error:
        print(f"shop eval baseline-search: {error}", file=sys.stderr)
        return 1
    seconds = time.monotonic() - started
    run_id = f"baseline-search-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    meta = {
        "kind": "baseline-search",
        "run_id": run_id,
        "command": "uv run shop eval baseline-search" + ("" if with_dev else " --no-dev"),
        "git": snapshot.git_sha(repo_root),
        "engine": "odoo (native website_sale search, http mode)",
        "shop": stack.ODOO_URL,
        "database_state": f"snapshot {SNAPSHOT} (catalog of Task 2.4b)",
        "inputs": {
            QUERY_FILE.as_posix(): _sha256(repo_root / QUERY_FILE),
            ID_MAP.as_posix(): _sha256(repo_root / ID_MAP),
        },
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "start": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": round(seconds, 1),
        "requests": len(picked) + sum(1 for entry in picked if entry.control) + len(dev_observations),
    }
    rates = dev_rates(dev_observations) if dev_observations else {}
    _write_run(repo_root, run_id, meta, hand, dev_observations, rates)
    if not with_dev:  # a quick look must not replace the committed table, which holds the dev-query rates
        write(
            f"Done in {seconds:.0f} s. Run folder: results/{run_id}/ ({SUMMARY_FILE.as_posix()} unchanged)\n"
        )
        return 0
    _write_text(repo_root / SUMMARY_FILE, render_summary(meta, hand, rates))
    write(f"Done in {seconds:.0f} s. Table: {SUMMARY_FILE.as_posix()}; run folder: results/{run_id}/\n")
    return 0


def _write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, target)


def _write_run(
    repo_root: Path,
    run_id: str,
    meta: dict[str, Any],
    hand: list[tuple[HandPicked, Observation, Observation | None]],
    dev_observations: list[Observation],
    rates: dict[str, Any],
) -> None:
    folder = repo_root / "results" / run_id
    observations = {
        "hand_picked": [
            {"entry": asdict(entry), "query": asdict(main), "control": asdict(control) if control else None}
            for entry, main, control in hand
        ],
        "dev": [asdict(item) for item in dev_observations],
        "dev_rates": rates,
    }
    _write_text(folder / "observations.json", json.dumps(observations, indent=2, ensure_ascii=False) + "\n")
    _write_text(folder / "run.json", json.dumps(meta, indent=2) + "\n")


def _cell(observation: Observation) -> str:
    if observation.total == 0:
        return "**0**"
    rank = f"#{observation.first_expected_rank}" if observation.first_expected_rank else "not on page 1"
    swap = f" → Odoo searched “{observation.fuzzy_term}”" if observation.fuzzy_term else ""
    noun = "result" if observation.total == 1 else "results"
    return f"{observation.total:,} {noun}{swap}; expected: {rank}"


def _short_git(sha: str) -> str:
    """12 characters of the commit, keeping the "-dirty" mark: uncommitted code must show in the table."""
    return sha[:12] + ("-dirty" if sha.endswith("-dirty") else "")


def render_summary(
    meta: dict[str, Any],
    hand: list[tuple[HandPicked, Observation, Observation | None]],
    rates: dict[str, Any],
) -> str:
    lines = [
        "# Baseline: Odoo's own shop search",
        "",
        "Generated by `uv run shop eval baseline-search` (Task 2.5); do not edit by hand. Engine: Odoo 19's",
        "native `website_sale` search through the real `/shop?search=` page (protocol §6.2, `http` mode),",
        f"on the catalog of snapshot `{SNAPSHOT}`. Dev data only.",
        f"Run `{meta['run_id']}`, git `{_short_git(meta['git'])}`, {meta['start']}.",
        "",
        "## Hand-picked queries",
        "",
        '"Expected" = rank of the first expected product among the 20 products of page 1. The control query',
        "differs from the query only by the problem under study.",
        "",
        "| group | query | Odoo shows | control query | Odoo shows |",
        "|---|---|---|---|---|",
    ]
    for entry, main, control in hand:
        control_text = f"`{entry.control}`" if entry.control else "—"
        control_cell = _cell(control) if control else "—"
        lines.append(f"| {entry.group} | `{entry.query}` | {_cell(main)} | {control_text} | {control_cell} |")
    if rates:
        lines += [
            "",
            f"## All {rates['all']['queries']} dev queries (Exact products from the ESCI judgments)",
            "",
            "| queries | n | no results | replaced by another word | an exact match on page 1 "
            "| median results |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name, row in rates.items():
            n = row["queries"]

            def share(count: int, n: int = n) -> str:
                return f"{count} ({count / n:.0%})" if n else "0"

            lines.append(
                f"| {name} | {n} | {share(row[NO_RESULTS])} | {share(row[REPLACED])} | "
                f"{share(row['exact match on page 1'])} | {row['median results']:,} |"
            )
        lines += [
            "",
            "Negation words: "
            + ", ".join(sorted(NEGATIONS))
            + ". A query can be in a length row and in the negation row.",
        ]
    lines += [
        "",
        f"Requests: {meta['requests']} in {meta['seconds']} s. Raw results: `results/{meta['run_id']}/`.",
    ]
    return "\n".join(lines) + "\n"
