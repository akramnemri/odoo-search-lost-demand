"""Catalog slice and query sets from ESCI: `uv run shop data build-slice [--dry-run]` (Task 2.3a).

Binding rules: docs/evaluation/protocol.md §2–3, §6.1 and §6.3 (tag `protocol-v1`); settings in
`tools/shoptools/data/slice.toml`. Named `slice_builder` so it does not shadow the built-in `slice`. Task 2.3b adds the synthetic enrichment, the hidden sets and the out-of-stock set.

Input: the two ESCI Parquet files in data/raw/esci/, checked against their pinned SHA-256 (never modified).
Steps, each with its own random stream derived from the base seed and a label (`derived_rng`):

1. query pool: every query of the configured locale and `small_version`, with its text and ESCI split;
2. dev: `queries.dev.size` queries drawn uniformly from the dev split (stream `dev-queries`);
3. test: `queries.test.size` queries drawn uniformly from the test split, after removing every query whose
   normalized text (`normalize_query`) equals a dev query's (stream `test-queries`); the removed count is recorded;
4. qrels: every judgment of the dev and test queries, with the gain of its label;
5. test-typo: each test query with one typo from `make_typo` (stream `typos`);
6. catalog: every product judged for a dev or test query (any label), with its ESCI text fields.

Outputs in data/processed/ (git-ignored): Parquet files with sorted rows, then `slice-manifest.json` (config,
seed, input and output SHA-256, counts, versions). The manifest is removed first and written last, so a stopped run
leaves no manifest and nothing downstream trusts its half-written files. An aggregates-only report (no query text,
no rows) goes to results/summary/slice-report.md, which is committed.

Same inputs, configuration, Python minor version and pyarrow version give byte-identical files. The files hold no
timestamp for that reason: the build time is only printed.

Memory: the products file (1.1 GB) is read in batches and filtered on the fly; measured peak in the task report.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import sys
import time
import tomllib
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any

from shoptools.data import download, esci
from shoptools.data.normalize import normalize_query
from shoptools.data.typos import OPERATIONS, make_typo

if TYPE_CHECKING:
    import pyarrow as pa

CONFIG_FILE = Path("tools") / "shoptools" / "data" / "slice.toml"
PROCESSED_DIR = Path("data") / "processed"
REPORT_FILE = Path("results") / "summary" / "slice-report.md"
MANIFEST_NAME = "slice-manifest.json"
DEV_FILE = "queries-dev.parquet"
TEST_FILE = "queries-test.parquet"
TYPO_FILE = "queries-test-typo.parquet"
QRELS_FILE = "qrels.parquet"
CATALOG_FILE = "catalog.parquet"
OUTPUT_FILES = (DEV_FILE, TEST_FILE, TYPO_FILE, QRELS_FILE, CATALOG_FILE)
LABELS = ("E", "S", "C", "I")
PRODUCT_TEXT_COLUMNS = (
    "product_title",
    "product_description",
    "product_bullet_point",
    "product_brand",
    "product_color",
)
BATCH_ROWS = 50_000
STREAM_BUFFER_BYTES = 8 * 1024 * 1024
STEPS = 5


class SliceError(Exception):
    """The configuration, an input file or the data does not satisfy a rule of the protocol."""


# --- configuration and seeds -----------------------------------------------------------------------------


@dataclass(frozen=True)
class QuerySetRule:
    size: int
    split: str  # ESCI split the queries are drawn from


@dataclass(frozen=True)
class SliceConfig:
    seed: int
    locale: str
    small_version: int
    dev: QuerySetRule
    test: QuerySetRule
    gains: dict[str, float]
    min_word_letters: int
    parsed: dict[str, Any]  # the whole file as parsed, for the hash and the manifest

    @property
    def sha256(self) -> str:
        """Hash of the parsed values, not of the file text: comments and spacing do not change it."""
        canonical = json.dumps(self.parsed, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(path: Path) -> SliceConfig:
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        queries = parsed["queries"]
        config = SliceConfig(
            seed=int(parsed["slice"]["seed"]),
            locale=str(parsed["slice"]["locale"]),
            small_version=int(parsed["slice"]["small_version"]),
            dev=QuerySetRule(int(queries["dev"]["size"]), str(queries["dev"]["split"])),
            test=QuerySetRule(int(queries["test"]["size"]), str(queries["test"]["split"])),
            gains={label: float(gain) for label, gain in parsed["gains"].items()},
            min_word_letters=int(parsed["typos"]["min_word_letters"]),
            parsed=parsed,
        )
    except (OSError, KeyError, TypeError, ValueError) as error:  # tomllib.TOMLDecodeError is a ValueError
        raise SliceError(f"slice configuration {path} is not valid: {error}") from error
    if set(config.gains) != set(LABELS):
        raise SliceError(f"[gains] must give exactly the labels {LABELS}, found {sorted(config.gains)}")
    if config.dev.split == config.test.split:
        raise SliceError("dev and test must come from different ESCI splits (protocol §3)")
    if config.dev.size < 1 or config.test.size < 1 or config.min_word_letters < 1:
        raise SliceError("query set sizes and typos.min_word_letters must be positive")
    return config


def derived_rng(seed: int, label: str) -> random.Random:
    """The random stream of one step (protocol §3): adding a step never changes the draws of the others.

    `random.Random` seeded with an int and `sample`/`choice` give the same draws on every platform for a given
    Python version; Python is pinned (docs/setup/VERSIONS.md) and recorded in the manifest.
    """
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


# --- reading ESCI --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Query:
    query_id: int
    text: str
    split: str


def _open_streaming(path: Path) -> Any:
    """Open a Parquet file to read it in small buffered pieces.

    ESCI's files hold a single row group each. By default pyarrow pre-buffers a whole row group's column chunks,
    which for the products file means about 1.1 GB in memory (measured: 1.57 GiB peak for the whole build).
    A buffered stream without pre-buffering reads the same batches with far less memory.
    """
    import pyarrow.parquet as pq  # data group; imported here so the rest of the CLI works without it

    return pq.ParquetFile(path, buffer_size=STREAM_BUFFER_BYTES, pre_buffer=False)


def _cell_batches(examples: Path, columns: Sequence[str], config: SliceConfig) -> Iterator[dict[str, list]]:
    """Batches of the examples file, restricted to the configured locale and small_version."""
    import pyarrow.compute as pc

    parquet = _open_streaming(examples)
    needed = [*columns, "product_locale", "small_version"]
    missing = set(needed) - set(parquet.schema_arrow.names)
    if missing:
        raise SliceError(f"{examples.name} has no column(s) {sorted(missing)}")
    for batch in parquet.iter_batches(batch_size=BATCH_ROWS * 4, columns=needed):
        mask = pc.and_(
            pc.equal(batch["product_locale"], config.locale),
            pc.equal(batch["small_version"], config.small_version),
        )
        yield batch.filter(mask).select(list(columns)).to_pydict()


def read_query_pool(examples: Path, config: SliceConfig) -> dict[int, Query]:
    """Every query of the cell. A query id with two texts or two splits would break dev ∩ test = ∅: refused."""
    pool: dict[int, Query] = {}
    for batch in _cell_batches(examples, ("query_id", "query", "split"), config):
        for query_id, text, split in zip(batch["query_id"], batch["query"], batch["split"], strict=True):
            known = pool.get(query_id)
            if known is None:
                pool[query_id] = Query(query_id, text, split)
            elif (known.text, known.split) != (text, split):
                raise SliceError(f"query {query_id} has two texts or two splits in {examples.name}")
    return pool


@dataclass(frozen=True)
class Selection:
    dev: list[Query]  # sorted by query id
    test: list[Query]  # sorted by query id
    pool_dev: int  # candidates in the dev split
    pool_test: int  # candidates in the test split, before duplicate removal
    removed_duplicates: int  # test candidates whose normalized text equals a dev query's

    def query_set(self) -> dict[int, str]:
        return {query.query_id: "dev" for query in self.dev} | {query.query_id: "test" for query in self.test}


def select_queries(pool: dict[int, Query], config: SliceConfig) -> Selection:
    def candidates(split: str) -> list[int]:
        return sorted(query_id for query_id, query in pool.items() if query.split == split)

    dev_pool = candidates(config.dev.split)
    if len(dev_pool) < config.dev.size:
        raise SliceError(f"only {len(dev_pool)} queries in split {config.dev.split!r}, {config.dev.size} wanted")
    dev_ids = derived_rng(config.seed, "dev-queries").sample(dev_pool, config.dev.size)
    dev_texts = {normalize_query(pool[query_id].text) for query_id in dev_ids}

    test_all = candidates(config.test.split)
    test_pool = [query_id for query_id in test_all if normalize_query(pool[query_id].text) not in dev_texts]
    if len(test_pool) < config.test.size:
        raise SliceError(
            f"only {len(test_pool)} queries in split {config.test.split!r} after duplicate removal, "
            f"{config.test.size} wanted"
        )
    test_ids = derived_rng(config.seed, "test-queries").sample(test_pool, config.test.size)
    return Selection(
        dev=[pool[query_id] for query_id in sorted(dev_ids)],
        test=[pool[query_id] for query_id in sorted(test_ids)],
        pool_dev=len(dev_pool),
        pool_test=len(test_all),
        removed_duplicates=len(test_all) - len(test_pool),
    )


@dataclass(frozen=True)
class Judgment:
    query_set: str
    query_id: int
    product_id: str
    label: str
    gain: float


def read_qrels(examples: Path, config: SliceConfig, selection: Selection) -> list[Judgment]:
    """All judgments of the selected queries, sorted by (query id, product id); one judgment per pair."""
    query_set = selection.query_set()
    judgments: dict[tuple[int, str], Judgment] = {}
    for batch in _cell_batches(examples, ("query_id", "product_id", "esci_label"), config):
        for query_id, product_id, label in zip(
            batch["query_id"], batch["product_id"], batch["esci_label"], strict=True
        ):
            if query_id not in query_set:
                continue
            if label not in config.gains:
                raise SliceError(f"unknown label {label!r} for query {query_id} in {examples.name}")
            if (query_id, product_id) in judgments:
                raise SliceError(f"query {query_id} judges product {product_id} twice in {examples.name}")
            judgments[(query_id, product_id)] = Judgment(
                query_set[query_id], query_id, product_id, label, config.gains[label]
            )
    unjudged = set(query_set) - {query_id for query_id, _ in judgments}
    if unjudged:
        raise SliceError(f"{len(unjudged)} selected queries have no judgment, e.g. {min(unjudged)}")
    return [judgment for _, judgment in sorted(judgments.items())]  # keys are unique: only they are compared


@dataclass(frozen=True)
class TypoQuery:
    query_id: int
    query: str  # with the typo; the original text when no word is eligible
    query_original: str
    operation: str | None
    position: int | None


def build_test_typos(test: list[Query], config: SliceConfig) -> list[TypoQuery]:
    rng = derived_rng(config.seed, "typos")
    rows = []
    for query in test:  # sorted by query id, so the stream is consumed in a fixed order
        typo = make_typo(query.text, rng, config.min_word_letters)
        if typo is None:
            rows.append(TypoQuery(query.query_id, query.text, query.text, None, None))
        else:
            rows.append(TypoQuery(query.query_id, typo.text, query.text, typo.operation, typo.position))
    return rows


def read_catalog(products: Path, locale: str, product_ids: set[str]) -> pa.Table:
    """The judged products with their ESCI text fields, sorted by product id. A missing product is refused."""
    import pyarrow as pa
    import pyarrow.compute as pc

    parquet = _open_streaming(products)
    columns = ["product_id", "product_locale", *PRODUCT_TEXT_COLUMNS]
    missing_columns = set(columns) - set(parquet.schema_arrow.names)
    if missing_columns:
        raise SliceError(f"{products.name} has no column(s) {sorted(missing_columns)}")
    wanted = pa.array(sorted(product_ids), pa.string())
    kept = ["product_id", *PRODUCT_TEXT_COLUMNS]
    parts = []
    for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=columns):
        mask = pc.and_(pc.equal(batch["product_locale"], locale), pc.is_in(batch["product_id"], value_set=wanted))
        selected = batch.filter(mask)
        if selected.num_rows:
            parts.append(selected.select(kept))
    source_schema = pa.schema([parquet.schema_arrow.field(name) for name in kept])
    table = pa.Table.from_batches(parts, schema=source_schema)
    # A fixed all-string schema, so the catalog's types (and hash) do not depend on how the source typed a column.
    table = table.cast(pa.schema([(name, pa.string()) for name in kept])).sort_by("product_id").combine_chunks()
    found = table["product_id"].to_pylist()
    if len(found) != len(set(found)):
        raise SliceError(f"{products.name} lists some {locale} products twice")
    absent = product_ids - set(found)
    if absent:
        raise SliceError(
            f"{len(absent)} judged products are not in {products.name} for locale {locale}, "
            f"e.g. {sorted(absent)[:3]}: every judged product must be in the catalog (protocol §3)"
        )
    return table


# --- writing -----------------------------------------------------------------------------------------------


def _tables(selection: Selection, qrels: list[Judgment], typos: list[TypoQuery]) -> dict[str, pa.Table]:
    import pyarrow as pa

    def queries_table(queries: list[Query]) -> pa.Table:
        return pa.table(
            {
                "query_id": [query.query_id for query in queries],
                "query": [query.text for query in queries],
                "query_normalized": [normalize_query(query.text) for query in queries],
            },
            schema=pa.schema([("query_id", pa.int64()), ("query", pa.string()), ("query_normalized", pa.string())]),
        )

    return {
        DEV_FILE: queries_table(selection.dev),
        TEST_FILE: queries_table(selection.test),
        TYPO_FILE: pa.table(
            {
                "query_id": [row.query_id for row in typos],
                "query": [row.query for row in typos],
                "query_original": [row.query_original for row in typos],
                "typo_operation": [row.operation for row in typos],
                "typo_position": [row.position for row in typos],
            },
            schema=pa.schema(
                [
                    ("query_id", pa.int64()),
                    ("query", pa.string()),
                    ("query_original", pa.string()),
                    ("typo_operation", pa.string()),
                    ("typo_position", pa.int64()),
                ]
            ),
        ),
        QRELS_FILE: pa.table(
            {
                "query_set": [row.query_set for row in qrels],
                "query_id": [row.query_id for row in qrels],
                "product_id": [row.product_id for row in qrels],
                "esci_label": [row.label for row in qrels],
                "gain": [row.gain for row in qrels],
            },
            schema=pa.schema(
                [
                    ("query_set", pa.string()),
                    ("query_id", pa.int64()),
                    ("product_id", pa.string()),
                    ("esci_label", pa.string()),
                    ("gain", pa.float64()),
                ]
            ),
        ),
    }


def write_parquet(table: pa.Table, target: Path) -> str:
    """Write atomically and return the SHA-256 of the file."""
    import pyarrow.parquet as pq

    temporary = target.with_name(target.name + ".tmp")
    pq.write_table(table.combine_chunks(), temporary, compression="snappy")
    os.replace(temporary, target)
    return download.sha256_of(target)


def _write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, target)


# --- statistics and report -----------------------------------------------------------------------------------


def set_statistics(queries: list[Query], qrels: list[Judgment]) -> dict[str, Any]:
    ids = {query.query_id for query in queries}
    rows = [row for row in qrels if row.query_id in ids]
    per_query = Counter(row.query_id for row in rows)
    with_gain = {row.query_id for row in rows if row.gain > 0}
    with_exact = {row.query_id for row in rows if row.label == "E"}
    normalized = Counter(normalize_query(query.text) for query in queries)
    counts = sorted(per_query.values())
    return {
        "queries": len(queries),
        "judgments": len(rows),
        "labels": {label: sum(1 for row in rows if row.label == label) for label in LABELS},
        "judgments_per_query": {"min": counts[0], "median": median(counts), "max": counts[-1]},
        "queries_without_positive_gain": len(ids - with_gain),  # IDCG = 0: excluded from NDCG (protocol §6.1)
        "queries_without_exact": len(ids - with_exact),
        "normalized_duplicates_within_set": sum(count - 1 for count in normalized.values() if count > 1),
        "products": len({row.product_id for row in rows}),
    }


def catalog_statistics(catalog: pa.Table, qrels: list[Judgment]) -> dict[str, Any]:
    import pyarrow.compute as pc

    by_set: dict[str, set[str]] = {"dev": set(), "test": set()}
    for row in qrels:
        by_set[row.query_set].add(row.product_id)
    empty = {}
    for name in PRODUCT_TEXT_COLUMNS:
        column = catalog[name]
        blank = pc.equal(pc.utf8_trim_whitespace(pc.fill_null(column, "")), "")
        empty[name] = int(pc.sum(blank).as_py() or 0)
    return {
        "products": catalog.num_rows,
        "judged_by_dev_and_test": len(by_set["dev"] & by_set["test"]),
        "empty_fields": empty,
    }


def typo_statistics(typos: list[TypoQuery]) -> dict[str, Any]:
    operations = Counter(row.operation for row in typos if row.operation)
    return {
        "queries": len(typos),
        "unchanged": sum(1 for row in typos if row.operation is None),
        "operations": {name: operations.get(name, 0) for name in OPERATIONS},
    }


def render_report(manifest: dict[str, Any]) -> str:
    config, counts = manifest["config"], manifest["counts"]
    pool = counts["pool"]
    lines = [
        "# Catalog slice and query sets",
        "",
        "Generated by `uv run shop data build-slice` (Task 2.3a) from the ESCI files below, with the rules of",
        "`docs/evaluation/protocol.md` §2–3 and §6 (tag `protocol-v1`). Aggregates only: no query text, no rows.",
        "Same inputs, configuration, Python and pyarrow versions give the same output SHA-256.",
        "",
        f"- configuration: `{manifest['config_file']}`, SHA-256 of the parsed values `{manifest['config_sha256'][:16]}…`",
        f"- base seed `{config['slice']['seed']}`; streams: {', '.join(f'`{s}`' for s in manifest['seed_streams'])}",
        f"- cell: locale `{config['slice']['locale']}`, `small_version = {config['slice']['small_version']}`",
        f"- versions: Python {manifest['versions']['python']}, pyarrow {manifest['versions']['pyarrow']}",
        "",
        "## Inputs",
        "",
        "| file | SHA-256 |",
        "|---|---|",
    ]
    lines += [f"| `{name}` | `{sha[:16]}…` |" for name, sha in manifest["inputs"].items()]
    lines += [
        "",
        "## Query sets",
        "",
        f"- pool: {pool['dev']:,} queries in the dev split, {pool['test']:,} in the test split",
        f"- test candidates removed because their normalized text equals a dev query's: "
        f"**{pool['removed_duplicates']:,}**",
        "",
        "| set | queries | judgments | E | S | C | I | judgments/query (min / median / max) "
        "| no positive gain | no E | normalized duplicates in set | products |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|",
    ]
    for name in ("dev", "test"):
        stats = counts[name]
        labels = " | ".join(f"{stats['labels'][label]:,}" for label in LABELS)
        spread = stats["judgments_per_query"]
        lines.append(
            f"| {name} | {stats['queries']:,} | {stats['judgments']:,} | {labels} | "
            f"{spread['min']} / {spread['median']} / {spread['max']} | {stats['queries_without_positive_gain']} | "
            f"{stats['queries_without_exact']} | {stats['normalized_duplicates_within_set']} | {stats['products']:,} |"
        )
    lines += [
        "",
        "\"No positive gain\" queries have IDCG@10 = 0 and are excluded from NDCG and counted (protocol §6.1).",
        "",
        "## test-typo",
        "",
    ]
    typos = counts["test_typo"]
    operations = ", ".join(f"{name} {count}" for name, count in typos["operations"].items())
    lines += [
        f"- {typos['queries']:,} queries; one edit each: {operations}",
        f"- unchanged (no word of ≥ {config['typos']['min_word_letters']} letters): {typos['unchanged']}",
        "",
        "## Catalog",
        "",
    ]
    catalog = counts["catalog"]
    lines += [
        f"- **{catalog['products']:,} products** (every product judged for a dev or test query, any label); "
        f"{catalog['judged_by_dev_and_test']:,} are judged by both sets",
        "- empty text fields (null or blank): "
        + ", ".join(f"`{name}` {count:,}" for name, count in catalog["empty_fields"].items()),
        "",
        "## Outputs (`data/processed/`, git-ignored)",
        "",
        "| file | rows | SHA-256 |",
        "|---|---:|---|",
    ]
    lines += [
        f"| `{name}` | {output['rows']:,} | `{output['sha256'][:16]}…` |" for name, output in manifest["outputs"].items()
    ]
    return "\n".join(lines) + "\n"


# --- command -----------------------------------------------------------------------------------------------


def _check_inputs(repo_root: Path, verify_checksums: bool) -> dict[str, str]:
    """The two Parquet files must be the pinned ones; returns their SHA-256 by file name."""
    pin = esci.load_pin(repo_root)
    pinned = {file.name: file for file in pin.files}
    checked = {}
    for name in (esci.EXAMPLES, esci.PRODUCTS):
        path = repo_root / esci.RAW_DIR / name
        file = pinned[name]
        if not path.is_file() or path.stat().st_size != file.size_bytes:
            raise SliceError(f"{path} is missing or has the wrong size: run `uv run shop data fetch esci`")
        if verify_checksums and download.sha256_of(path) != file.sha256:
            raise SliceError(f"{path} does not match its pinned SHA-256: run `uv run shop data fetch esci`")
        checked[name] = file.sha256
    return checked


def run_build_slice(
    repo_root: Path,
    dry_run: bool = False,
    config_path: Path | None = None,
    write: Callable[[str], None] = sys.stdout.write,
) -> int:
    started = time.monotonic()
    step_started = started

    def step(number: int, text: str) -> None:
        nonlocal step_started
        now = time.monotonic()
        write(f"  [{number}/{STEPS}] {text} ({now - step_started:.1f} s)\n")
        step_started = now

    try:
        config_file = config_path or repo_root / CONFIG_FILE
        config = load_config(config_file)
        write(f"Slice configuration {config_file.name}, seed {config.seed}, SHA-256 {config.sha256[:12]}...\n")
        inputs = _check_inputs(repo_root, verify_checksums=not dry_run)
        step(1, "ESCI inputs " + ("present (sizes only in a dry run)" if dry_run else "match their pinned SHA-256"))
        examples = repo_root / esci.RAW_DIR / esci.EXAMPLES
        pool = read_query_pool(examples, config)
        selection = select_queries(pool, config)
        step(
            2,
            f"queries: dev {len(selection.dev)} of {selection.pool_dev:,}, test {len(selection.test)} of "
            f"{selection.pool_test:,} ({selection.removed_duplicates} removed as duplicates of dev)",
        )
        qrels = read_qrels(examples, config, selection)
        product_ids = {row.product_id for row in qrels}
        step(3, f"qrels: {len(qrels):,} judgments of {len(product_ids):,} products")
        if dry_run:
            write(f"Dry run: nothing written. A real run writes {', '.join(OUTPUT_FILES)} and {MANIFEST_NAME}\n")
            write(f"  into {PROCESSED_DIR.as_posix()}/, and {REPORT_FILE.as_posix()}.\n")
            return 0
        typos = build_test_typos(selection.test, config)
        catalog = read_catalog(repo_root / esci.RAW_DIR / esci.PRODUCTS, config.locale, product_ids)
        step(4, f"test-typo and catalog: {catalog.num_rows:,} products read from {esci.PRODUCTS}")
        manifest = _write_outputs(repo_root, config, config_file, inputs, selection, qrels, typos, catalog)
    except (SliceError, esci.EsciError, OSError) as error:
        print(f"\nshop data build-slice: {error}", file=sys.stderr)
        return 1
    step(5, f"outputs written to {PROCESSED_DIR.as_posix()}/")
    write(f"Slice built in {time.monotonic() - started:.0f} s. Output SHA-256:\n")
    for name, output in manifest["outputs"].items():
        write(f"  {output['sha256']}  {name} ({output['rows']:,} rows)\n")
    write(f"Report: {REPORT_FILE.as_posix()}; manifest: {(PROCESSED_DIR / MANIFEST_NAME).as_posix()}\n")
    return 0


def _write_outputs(
    repo_root: Path,
    config: SliceConfig,
    config_file: Path,
    inputs: dict[str, str],
    selection: Selection,
    qrels: list[Judgment],
    typos: list[TypoQuery],
    catalog: pa.Table,
) -> dict[str, Any]:
    import pyarrow as pa

    processed = repo_root / PROCESSED_DIR
    processed.mkdir(parents=True, exist_ok=True)
    (processed / MANIFEST_NAME).unlink(missing_ok=True)  # see the module docstring: manifest last
    tables = _tables(selection, qrels, typos) | {CATALOG_FILE: catalog}
    outputs = {
        name: {"rows": tables[name].num_rows, "sha256": write_parquet(tables[name], processed / name)}
        for name in OUTPUT_FILES
    }
    try:
        config_name = config_file.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        config_name = config_file.name
    manifest = {
        "builder": "uv run shop data build-slice (Task 2.3a)",
        "protocol": "docs/evaluation/protocol.md (tag protocol-v1)",
        "config_file": config_name,
        "config_sha256": config.sha256,
        "config": config.parsed,
        "seed_streams": ["dev-queries", "test-queries", "typos"],
        "inputs": inputs,
        "versions": {"python": platform.python_version(), "pyarrow": pa.__version__},
        "counts": {
            "pool": {
                "dev": selection.pool_dev,
                "test": selection.pool_test,
                "removed_duplicates": selection.removed_duplicates,
            },
            "dev": set_statistics(selection.dev, qrels),
            "test": set_statistics(selection.test, qrels),
            "test_typo": typo_statistics(typos),
            "catalog": catalog_statistics(catalog, qrels),
        },
        "outputs": outputs,
    }
    _write_text(repo_root / REPORT_FILE, render_report(manifest))
    _write_text(processed / MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
