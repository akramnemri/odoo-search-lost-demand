"""Amazon Shopping Queries Dataset (ESCI): `shop data fetch esci` and `shop data profile esci` (Task 2.1).

Source: github.com/amazon-science/esci-data at the commit pinned in docs/setup/versions.toml. The two Parquet
files are Git LFS objects: they are downloaded from the repository's LFS storage (media.githubusercontent.com)
at that commit, and checked against the size and SHA-256 of the LFS pointer files (pinned too). No git clone
inside `data/`. `sources.csv` is a plain git file (raw.githubusercontent.com).

The profile reads only the columns it needs, in batches, and writes aggregates only (no rows) to
results/summary/esci-profile.md.
"""

from __future__ import annotations

import shutil
import sys
import time
import tomllib
import urllib.error
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from shoptools.data import download
from shoptools.data.manifest import ManifestEntry, ManifestError, read_manifest, upsert_entries
from shoptools.doctor.expected import VERSIONS_FILE

RAW_DIR = Path("data") / "raw" / "esci"
PROFILE_FILE = Path("results") / "summary" / "esci-profile.md"
EXAMPLES = "shopping_queries_dataset_examples.parquet"
PRODUCTS = "shopping_queries_dataset_products.parquet"
EXAMPLES_COLUMNS = ("query_id", "product_id", "product_locale", "esci_label", "small_version", "split")
PRODUCTS_COLUMNS = ("product_locale",)
LABELS = ("E", "S", "C", "I")
ASSUMED_MBIT_S = 30  # for the time estimate only
DISK_MARGIN_BYTES = 2 * 1024**3  # keep at least this much free after the download


class EsciError(Exception):
    """A pin, a download, the manifest or the dataset itself is not as expected."""


@dataclass(frozen=True)
class PinnedFile:
    name: str
    lfs: bool
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class EsciPin:
    repository: str
    commit: str
    folder: str
    license: str
    files: tuple[PinnedFile, ...]

    def url(self, file: PinnedFile) -> str:
        host = "media.githubusercontent.com/media" if file.lfs else "raw.githubusercontent.com"
        return f"https://{host}/{self.repository}/{self.commit}/{self.folder}/{file.name}"

    def relative_path(self, file: PinnedFile) -> str:
        return (RAW_DIR / file.name).as_posix()

    @property
    def total_bytes(self) -> int:
        return sum(file.size_bytes for file in self.files)


def load_pin(repo_root: Path) -> EsciPin:
    try:
        data = tomllib.loads((repo_root / VERSIONS_FILE).read_text(encoding="utf-8"))["datasets"]["esci"]
        files = tuple(
            PinnedFile(row["name"], bool(row["lfs"]), int(row["size_bytes"]), row["sha256"]) for row in data["files"]
        )
        return EsciPin(data["repository"], data["commit"], data["folder"], data["license"], files)
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as error:
        raise EsciError(f"no valid [datasets.esci] pin in {VERSIONS_FILE}: {error}") from error


# --- fetch -------------------------------------------------------------------------------------------------


def plan_lines(pin: EsciPin, repo_root: Path, to_fetch: list[PinnedFile]) -> list[str]:
    missing = sum(file.size_bytes for file in to_fetch)
    free = shutil.disk_usage(repo_root).free
    minutes = missing * 8 / (ASSUMED_MBIT_S * 1e6) / 60
    lines = [
        f"Amazon ESCI, {pin.repository} at {pin.commit[:7]} ({pin.license}) into {RAW_DIR.as_posix()}/",
    ]
    for file in pin.files:
        state = "download" if file in to_fetch else "already verified, skipped"
        lines.append(f"  {file.name:45} {file.size_bytes / 1e6:9,.1f} MB  {state}")
    lines.append(
        f"To download: {missing / 1e9:.2f} GB, about {minutes:.0f} min at {ASSUMED_MBIT_S} Mbit/s; "
        f"free disk {free / 1e9:.1f} GB. Interrupted downloads resume."
    )
    return lines


def run_fetch(
    repo_root: Path,
    dry_run: bool = False,
    yes: bool = False,
    ask: Callable[[str], str] = input,
    opener: download.Opener = download.open_url,
    write: Callable[[str], None] = sys.stdout.write,
) -> int:
    try:
        pin = load_pin(repo_root)
        targets = {file: repo_root / RAW_DIR / file.name for file in pin.files}
        to_fetch = [
            file for file in pin.files if not download.is_verified(targets[file], _expected(pin, file))
        ]
        for line in plan_lines(pin, repo_root, to_fetch):
            write(line + "\n")
        if dry_run:
            return 0
        needed = sum(file.size_bytes for file in to_fetch) + DISK_MARGIN_BYTES
        if to_fetch and shutil.disk_usage(repo_root).free < needed:
            raise EsciError(f"not enough free disk: need {needed / 1e9:.1f} GB including a 2 GB margin")
        if to_fetch and not yes and ask("Download now? Type 'yes' to continue: ").strip().lower() != "yes":
            write("Nothing downloaded.\n")
            return 1
        started = time.monotonic()
        for file in to_fetch:
            progress = download.ProgressLine(file.name, write)
            download.fetch(_expected(pin, file), targets[file], opener=opener, progress=progress)
            write(f"\n  {file.name}: size and SHA-256 verified\n")
        _record(repo_root, pin)
    except (EsciError, ManifestError, download.DownloadError, urllib.error.URLError, OSError) as error:
        print(f"\nshop data fetch esci: {error}", file=sys.stderr)
        return 1
    write(
        f"ESCI ready in {RAW_DIR.as_posix()}/ ({len(to_fetch)} downloaded, "
        f"{len(pin.files) - len(to_fetch)} already verified) in {time.monotonic() - started:.0f} s; "
        f"provenance in data/manifest.toml.\n"
    )
    return 0


def _expected(pin: EsciPin, file: PinnedFile) -> download.Expected:
    return download.Expected(pin.url(file), file.size_bytes, file.sha256)


def _record(repo_root: Path, pin: EsciPin) -> None:
    previous = {entry.path: entry for entry in read_manifest(repo_root)}
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = []
    for file in pin.files:
        path = pin.relative_path(file)
        old = previous.get(path)
        # Keep the first download date when the same verified file is recorded again.
        downloaded_at = old.downloaded_at if old and old.sha256 == file.sha256 else now
        entries.append(
            ManifestEntry(
                path=path,
                source_url=pin.url(file),
                version=f"{pin.repository}@{pin.commit}",
                sha256=file.sha256,
                size_bytes=file.size_bytes,
                license=pin.license,
                downloaded_at=downloaded_at,
            )
        )
    upsert_entries(repo_root, entries)


# --- profile -----------------------------------------------------------------------------------------------


@dataclass
class Cell:
    judgments: int = 0
    queries: set[int] = field(default_factory=set)
    labels: Counter[str] = field(default_factory=Counter)


def _batches(path: Path, columns: tuple[str, ...]) -> Iterator[dict[str, list]]:
    import pyarrow.parquet as pq  # data group; imported here so the rest of the CLI works without it

    parquet = pq.ParquetFile(path)
    missing = set(columns) - set(parquet.schema_arrow.names)
    if missing:
        raise EsciError(f"{path.name} has no column(s) {sorted(missing)}; columns: {parquet.schema_arrow.names}")
    for batch in parquet.iter_batches(batch_size=200_000, columns=list(columns)):
        yield batch.to_pydict()


def profile(examples: Path, products: Path) -> dict:
    """Aggregates only. Memory: the distinct query ids and product ids of the us/small_version cell."""
    cells: dict[tuple[str, str, int], Cell] = defaultdict(Cell)
    per_query: Counter[int] = Counter()
    us_small_products: set[str] = set()
    for batch in _batches(examples, EXAMPLES_COLUMNS):
        rows = zip(*(batch[name] for name in EXAMPLES_COLUMNS), strict=True)
        for query_id, product_id, locale, label, small, split in rows:
            cell = cells[(locale, split, int(small))]
            cell.judgments += 1
            cell.queries.add(query_id)
            cell.labels[label] += 1
            if locale == "us" and small:
                per_query[query_id] += 1
                us_small_products.add(product_id)
    products_per_locale: Counter[str] = Counter()
    for batch in _batches(products, PRODUCTS_COLUMNS):
        products_per_locale.update(batch["product_locale"])
    counts = sorted(per_query.values())
    return {
        "cells": {key: (cell.judgments, len(cell.queries), dict(cell.labels)) for key, cell in sorted(cells.items())},
        "us_small": {
            "queries": len(counts),
            "judgments": sum(counts),
            "products": len(us_small_products),
            "per_query_min": counts[0] if counts else 0,
            "per_query_median": median(counts) if counts else 0,
            "per_query_max": counts[-1] if counts else 0,
        },
        "products_per_locale": dict(sorted(products_per_locale.items())),
    }


def render_profile(result: dict, entries: list[ManifestEntry]) -> str:
    lines = [
        "# ESCI profile",
        "",
        "Generated by `uv run shop data profile esci` (Task 2.1). Aggregates only, no rows. Source files and their",
        "SHA-256 in `data/manifest.toml`:",
        "",
    ]
    lines += [f"- `{entry.path}` — {entry.version}, `{entry.sha256[:12]}…`" for entry in entries]
    lines += [
        "",
        "## Judgments and queries per locale, split and `small_version`",
        "",
        "| locale | split | small_version | judgments | queries | E | S | C | I |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for (locale, split, small), (judgments, queries, labels) in result["cells"].items():
        shares = [f"{labels.get(label, 0) / judgments:.1%}" if judgments else "–" for label in LABELS]
        lines.append(f"| {locale} | {split} | {small} | {judgments:,} | {queries:,} | " + " | ".join(shares) + " |")
    us = result["us_small"]
    lines += [
        "",
        "## `us`, `small_version = 1` (the pool for the dev and test query sets, `04` §3)",
        "",
        f"- queries: {us['queries']:,}; judgments: {us['judgments']:,}; distinct judged products: {us['products']:,}",
        f"- judgments per query: min {us['per_query_min']}, median {us['per_query_median']}, max {us['per_query_max']}",
        "",
        "## Products per locale (products file)",
        "",
        "| locale | products |",
        "|---|---:|",
    ]
    lines += [f"| {locale} | {count:,} |" for locale, count in result["products_per_locale"].items()]
    return "\n".join(lines) + "\n"


def run_profile(repo_root: Path, write: Callable[[str], None] = sys.stdout.write) -> int:
    started = time.monotonic()
    try:
        pin = load_pin(repo_root)
        entries = {entry.path: entry for entry in read_manifest(repo_root)}
        recorded = [entries.get(pin.relative_path(file)) for file in pin.files]
        if any(entry is None or entry.sha256 != file.sha256 for entry, file in zip(recorded, pin.files, strict=True)):
            raise EsciError("ESCI is not fetched and recorded yet: run `uv run shop data fetch esci` first")
        for file in pin.files:
            path = repo_root / RAW_DIR / file.name
            if not path.is_file() or path.stat().st_size != file.size_bytes:
                raise EsciError(f"{path} is missing or has the wrong size: run `uv run shop data fetch esci`")
        result = profile(repo_root / RAW_DIR / EXAMPLES, repo_root / RAW_DIR / PRODUCTS)
        target = repo_root / PROFILE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".md.tmp")
        temporary.write_text(render_profile(result, [e for e in recorded if e]), encoding="utf-8", newline="\n")
        temporary.replace(target)
    except (EsciError, ManifestError, OSError) as error:
        print(f"shop data profile esci: {error}", file=sys.stderr)
        return 1
    us = result["us_small"]
    write(
        f"Profile written to {PROFILE_FILE.as_posix()} in {time.monotonic() - started:.0f} s "
        f"(us/small_version: {us['queries']:,} queries, {us['products']:,} judged products).\n"
    )
    return 0
