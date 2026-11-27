"""Tests of tools/shoptools/eval/ndcg.py (Task 3.4) on a small temporary repository, with fake connections:
no stack, no network."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from shoptools.eval import ndcg

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTS = ndcg.ShopFacts(
    website_id=1,
    page_size=21,
    module_version="19.0.0.5.0",
    published_products=6,
    elasticsearch="9.5.5",
    index="shop-products-v5",
    definition_version=2,
    documents=6,
    sold_out_documents=1,
)
# Two dev queries (1 and 2) and one test query (9, must never be read); template id = 100 + product number.
QUERIES = [(1, "blue lamp"), (2, "garden chair")]
QRELS = [
    ("dev", 1, "P1", "E", 1.0),
    ("dev", 1, "P2", "S", 0.1),
    ("dev", 1, "P3", "I", 0.0),
    ("dev", 2, "P4", "E", 1.0),
    ("dev", 2, "P5", "C", 0.01),
    ("test", 9, "P6", "E", 1.0),
]


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    processed = tmp_path / "data" / "processed"
    _write_parquet(
        processed / "queries-dev.parquet",
        [{"query_id": qid, "query": text, "query_normalized": text} for qid, text in QUERIES],
    )
    _write_parquet(
        processed / "qrels.parquet",
        [
            {"query_set": s, "query_id": q, "product_id": p, "esci_label": label, "gain": gain}
            for s, q, p, label, gain in QRELS
        ],
    )
    _write_parquet(
        processed / "odoo_id_map.parquet",
        [{"product_id": f"P{n}", "template_id": 100 + n, "variant_id": 200 + n} for n in range(1, 7)],
    )
    outputs = {
        name: {"sha256": hashlib.sha256((processed / name).read_bytes()).hexdigest()}
        for name in ("queries-dev.parquet", "qrels.parquet")
    }
    (processed / "slice-manifest.json").write_text(json.dumps({"outputs": outputs}), encoding="utf-8")
    for relative in (ndcg.SLICE_CONFIG, ndcg.QUERY_BUILDER, ndcg.MODULE_CONFIG, Path("compose.yaml")):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, tmp_path / relative)
    return tmp_path


class FakeEngines:
    """A fixed ranking of ESCI ids per engine and query; `fallbacks` makes Odoo answer instead."""

    def __init__(self, rankings: dict[str, dict[str, list[str]]]) -> None:
        self.rankings = rankings
        self.fallbacks: dict[str, int] = {}  # query -> how many more times the fallback answers
        self.calls: list[tuple[str, str]] = []

    def __call__(self, engine: str, query: str) -> ndcg.Ranking:
        self.calls.append((engine, query))
        if self.fallbacks.get(query, 0) > 0:
            self.fallbacks[query] -= 1
            return ndcg.Ranking(products=["P3"], engine_used="odoo_fallback")
        return ndcg.Ranking(products=self.rankings[engine][query], engine_used=engine)


RANKINGS = {
    "odoo": {"blue lamp": [], "garden chair": ["P5", "P4"]},
    "es_plain": {"blue lamp": ["P2", "P1"], "garden chair": ["P4"]},
    "es_tuned": {"blue lamp": ["P1", "P2", "P3"], "garden chair": ["P4", "P5"]},
    "es_tuned_stock": {"blue lamp": ["P1", "P2"], "garden chair": ["P4", "P5"]},
}


@pytest.fixture
def engines() -> FakeEngines:
    return FakeEngines(RANKINGS)


def _connections(engines: FakeEngines) -> ndcg.Connections:
    return ndcg.Connections(fetchers={ndcg.HTTP: engines, ndcg.DIRECT: engines}, facts=FACTS)


def _run(repo: Path, fake: FakeEngines, **kwargs: Any) -> tuple[int, str]:
    lines: list[str] = []
    code = ndcg.run_ndcg(
        repo, connections=_connections(fake), write=lines.append, sleep=lambda _: None, **kwargs
    )
    return code, "".join(lines)


def _run_folders(repo: Path) -> list[Path]:
    return sorted((repo / "results").glob("ndcg-*"))


# --- refusals ---


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"set_name": "test"}, "after the configuration freeze"),
        ({"set_name": "test-typo"}, "after the configuration freeze"),
        ({"set_name": "train"}, "unknown set"),
        ({"engines": ("es_magic",)}, "unknown engine"),
        ({"engines": ("odoo",), "mode": "direct"}, "only in http mode"),
        ({"mode": "fast"}, "unknown mode"),
        ({"limit": 0}, "at least 1"),
    ],
)
def test_refusals(repo: Path, engines: FakeEngines, kwargs: dict, message: str, capsys) -> None:
    code, _ = _run(repo, engines, **kwargs)

    assert code == 1
    assert message in capsys.readouterr().err
    assert engines.calls == []
    assert not (repo / "results").exists()


def test_data_that_does_not_match_the_manifest_is_refused(repo: Path, engines: FakeEngines, capsys) -> None:
    _write_parquet(
        repo / "data" / "processed" / "queries-dev.parquet",
        [{"query_id": 1, "query": "changed", "query_normalized": "changed"}],
    )

    assert _run(repo, engines)[0] == 1
    assert "does not match" in capsys.readouterr().err


def test_dev_set_reads_dev_judgments_only(repo: Path) -> None:
    dev = ndcg.read_dev_set(repo)

    assert dev.queries == QUERIES
    assert set(dev.judgments) == {1, 2}
    assert dev.judgments[1] == {"P1": 1.0, "P2": 0.1, "P3": 0.0}


def test_a_gain_that_is_not_the_protocols_is_refused(repo: Path) -> None:
    processed = repo / "data" / "processed"
    _write_parquet(
        processed / "qrels.parquet",
        [{"query_set": "dev", "query_id": 1, "product_id": "P1", "esci_label": "E", "gain": 3.0}],
    )
    manifest = json.loads((processed / "slice-manifest.json").read_text(encoding="utf-8"))
    manifest["outputs"]["qrels.parquet"]["sha256"] = hashlib.sha256(
        (processed / "qrels.parquet").read_bytes()
    ).hexdigest()
    (processed / "slice-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ndcg.NdcgError, match="not the protocol's"):
        ndcg.read_dev_set(repo)


# --- fallback handling (http mode) ---


def test_one_fallback_is_retried(repo: Path, engines: FakeEngines) -> None:
    engines.fallbacks["garden chair"] = 1

    code, _ = _run(repo, engines)

    assert code == 0
    meta = json.loads((_run_folders(repo)[0] / "run.json").read_text(encoding="utf-8"))
    assert meta["fallback_retries"] == 1
    assert meta["fallback_retried"] == [["odoo", 2]]  # the first engine of the run, query "garden chair"
    table = (repo / "results" / "summary" / "ndcg-dev-http.md").read_text(encoding="utf-8")
    assert "Fallback retries in http mode: 1 (odoo query 2)" in table


def test_a_second_fallback_stops_the_run_and_writes_nothing(repo: Path, engines: FakeEngines, capsys) -> None:
    engines.fallbacks["garden chair"] = 2

    assert _run(repo, engines)[0] == 1
    assert "was not used" in capsys.readouterr().err
    assert _run_folders(repo) == []
    assert not (repo / "results" / "summary").exists()


def test_warm_up_queries_are_not_counted(repo: Path, engines: FakeEngines) -> None:
    _run(repo, engines, engines=("es_plain",))

    assert engines.calls == [
        ("es_plain", "blue lamp"),
        ("es_plain", "blue lamp"),
        ("es_plain", "garden chair"),
    ]


# --- a full run ---


def test_full_run_writes_the_run_folder_and_the_table(repo: Path, engines: FakeEngines) -> None:
    code, output = _run(repo, engines)

    assert code == 0
    (folder,) = _run_folders(repo)
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert meta["kind"] == "ndcg"
    assert meta["command"] == "uv run shop eval ndcg --set dev --engine odoo,es_plain,es_tuned --mode http"
    assert meta["seed"] == 20261025
    assert meta["queries"] == 2
    assert set(meta["data"]) == {"queries-dev.parquet", "qrels.parquet", "odoo_id_map.parquet"}
    assert meta["shop"]["index"] == "shop-products-v5"
    assert len((folder / "rankings.jsonl").read_text(encoding="utf-8").splitlines()) == 6
    table = (repo / "results" / "summary" / "ndcg-dev-http.md").read_text(encoding="utf-8")
    assert "Dev queries only" in table
    assert "| `es_tuned` | 2 (+0 excluded) | 1.0000 [1.0000, 1.0000]" in table
    assert "`es_tuned` − `es_plain`" in table
    assert "Table: results/summary/ndcg-dev-http.md" in output


def test_scores_by_hand(repo: Path, engines: FakeEngines) -> None:
    _run(repo, engines)
    (folder,) = _run_folders(repo)
    scores = json.loads((folder / "scores.json").read_text(encoding="utf-8"))["http"]

    by_query = {item["query_id"]: item for item in scores["es_plain"]}
    # blue lamp: P2 (0.1) then P1 (1.0); ideal P1, P2, P3. DCG 0.1 + 1/log2(3); IDCG 1 + 0.1/log2(3).
    assert by_query[1]["ndcg"] == pytest.approx((0.1 + 0.6309298) / (1 + 0.0630930), abs=1e-6)
    odoo = {item["query_id"]: item for item in scores["odoo"]}
    assert odoo[1] == {"query_id": 1, "ndcg": 0.0, "judged": None, "condensed": 0.0, "results": 0}


def test_limit_writes_the_run_folder_but_not_the_table(repo: Path, engines: FakeEngines) -> None:
    code, output = _run(repo, engines, limit=1)

    assert code == 0
    assert len(_run_folders(repo)) == 1
    assert not (repo / "results" / "summary").exists()
    assert "table unchanged" in output


def test_both_modes_and_their_consistency(repo: Path, engines: FakeEngines) -> None:
    code, _ = _run(repo, engines, engines=ndcg.ALL_ENGINES, mode="both")

    assert code == 0
    table = (repo / "results" / "summary" / "ndcg-dev-both.md").read_text(encoding="utf-8")
    assert "## Mode `direct`" in table and "## Mode `http`" in table
    assert "| `es_tuned_stock` | 2 | 2 (100.0%) |" in table
    direct_section = table.split("## Mode `direct`")[1].split("## Mode `http`")[0]
    assert "`odoo`" not in direct_section  # Odoo's search exists only in http mode


def test_two_runs_give_identical_numbers(repo: Path, engines: FakeEngines) -> None:
    _run(repo, engines, engines=ndcg.ALL_ENGINES)
    first = (repo / "results" / "summary" / "ndcg-dev-http.md").read_text(encoding="utf-8")
    for folder in _run_folders(repo):
        shutil.rmtree(folder)
    _run(repo, engines, engines=ndcg.ALL_ENGINES)
    second = (repo / "results" / "summary" / "ndcg-dev-http.md").read_text(encoding="utf-8")

    def numbers(text: str) -> list[str]:
        return [line for line in text.splitlines() if line.startswith("| `")]

    assert numbers(first) == numbers(second)


# --- fetchers ---


@pytest.fixture
def query_builder(repo: Path) -> Iterator[Any]:
    yield ndcg.load_module_file(repo / ndcg.QUERY_BUILDER, "test_query_builder")


def test_direct_mode_sends_the_modules_query_and_applies_its_stock_rule(query_builder: Any) -> None:
    sent: list[tuple[str, Any]] = []

    def es(path: str, body: Any) -> dict[str, Any]:
        sent.append((path, body))
        hits = [
            {"_id": "103", "fields": {"in_stock": [False]}},
            {"_id": "101", "fields": {"in_stock": [True]}},
            {"_id": "102", "fields": {"in_stock": [True]}},
        ]
        return {"took": 5, "hits": {"hits": hits}}

    fetch = ndcg.direct_fetcher(es, query_builder, 1, 1000, 2, {101: "P1", 102: "P2", 103: "P3"})
    ranking = fetch("es_tuned_stock", "  blue\tlamp ")

    assert ranking == ndcg.Ranking(products=["P1", "P2"], engine_used="es_tuned_stock", took_ms=5)
    path, body = sent[0]
    assert path == "/shop-products/_search"
    filters = query_builder.SearchFilters(website_id=1)
    assert body == query_builder.build_search("es_tuned_stock", "blue lamp", filters, 1000)


def test_direct_mode_refuses_odoo_and_skips_empty_queries(query_builder: Any) -> None:
    fetch = ndcg.direct_fetcher(lambda path, body: {}, query_builder, 1, 1000, 21, {})

    with pytest.raises(ndcg.NdcgError, match="only in http mode"):
        fetch("odoo", "lamp")
    assert fetch("es_plain", " \x00 ").products == []


class _Response:
    def __init__(self, body: str, headers: dict[str, str]) -> None:
        self._body, self.headers = body.encode(), headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_http_fetch_reads_the_page_and_the_engine_header(monkeypatch: pytest.MonkeyPatch) -> None:
    page = (
        "<h1><span class=\"text-muted\">Search results for </span>'<strong>lamp</strong>' "
        '<small class="text-muted">(2)</small></h1><div id="o_wsale_products_grid">'
        '<a href="/shop/blue-lamp-102">x</a><a href="/shop/blue-lamp-102">x</a>'
        '<a href="/shop/other-555">y</a></div>'
    )
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        seen["url"], seen["headers"] = request.full_url, dict(request.header_items())
        return _Response(page, {"X-Lost-Demand-Engine-Used": "es_plain"})

    monkeypatch.setattr(ndcg.urllib.request, "urlopen", fake_urlopen)
    ranking = ndcg.http_fetcher("secret-key-for-tests-only", {102: "P2"})("es_plain", "blue lamp")

    assert ranking == ndcg.Ranking(products=["P2", "odoo-template-555"], engine_used="es_plain")
    assert seen["url"].endswith("/shop?search=blue+lamp")
    assert seen["headers"]["X-lost-demand-engine"] == "es_plain"
    assert seen["headers"]["X-lost-demand-key"] == "secret-key-for-tests-only"


def test_shop_facts(repo: Path) -> None:
    def call(model: str, method: str, body: dict[str, Any]) -> Any:
        return {
            "website": [{"id": 1, "shop_ppg": 0}],
            "ir.module.module": [{"installed_version": "19.0.0.5.0"}],
            "product.template": 19869,
        }[model]

    def es(path: str, body: Any) -> dict[str, Any]:
        if path == "/_alias/shop-products":
            return {"shop-products-v5": {"aliases": {"shop-products": {}}}}
        if path == "/shop-products-v5/_mapping":
            return {"shop-products-v5": {"mappings": {"_meta": {"definition_version": 2}}}}
        if path == "/":
            return {"version": {"number": "9.5.5"}}
        return {"count": 1828 if "term" in body["query"] else 19869}

    facts = ndcg.read_shop_facts(call, es)

    assert facts.page_size == 21  # shop_ppg 0 means Odoo's default
    assert (facts.index, facts.definition_version, facts.documents, facts.sold_out_documents) == (
        "shop-products-v5",
        2,
        19869,
        1828,
    )


def test_progress_is_flushed_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run takes minutes; redirected to a log file, its progress must not wait for the end."""
    events: list[str] = []

    class Stream:
        def write(self, text: str) -> None:
            events.append("write")

        def flush(self) -> None:
            events.append("flush")

    monkeypatch.setattr(ndcg.sys, "stdout", Stream())
    ndcg._print("  http: 50/1200 rankings\n")

    assert events == ["write", "flush"]


def test_progress_never_fails_on_a_narrow_console_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows writes a redirected stdout as cp1252, which has no "Δ" (Task 3.5 runs crashed on it)."""
    written: list[str] = []

    class Stream:
        encoding = "cp1252"

        def write(self, text: str) -> None:
            text.encode("cp1252")  # what the real stream does: fails on a character cp1252 lacks
            written.append(text)

        def flush(self) -> None:
            return None

    monkeypatch.setattr(ndcg.sys, "stdout", Stream())
    ndcg._print("Δ dev +0.0090\n")

    assert written == ["? dev +0.0090\n"]
