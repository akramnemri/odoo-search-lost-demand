from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import REPO_ROOT, FakeSystem

from shoptools.data import esci
from shoptools.data.manifest import (
    ManifestEntry,
    ManifestError,
    read_manifest,
    render_manifest,
    upsert_entries,
)
from shoptools.doctor.checks import DoctorContext
from shoptools.doctor.data_checks import check_data
from shoptools.doctor.expected import VERSIONS_FILE, load_expected
from shoptools.doctor.model import Status

# Synthetic ESCI-format data: 3 queries, 2 locales, both splits; 4 products.
EXAMPLES = {
    "query_id": [1, 1, 1, 2, 2, 3],
    "product_id": ["A", "B", "C", "A", "D", "E"],
    "product_locale": ["us", "us", "us", "us", "us", "es"],
    "esci_label": ["E", "S", "I", "E", "C", "E"],
    "small_version": [1, 1, 1, 1, 0, 1],
    "split": ["train", "train", "train", "test", "test", "train"],
}
PRODUCTS = {"product_id": ["A", "B", "C", "D", "E"], "product_locale": ["us", "us", "us", "us", "es"]}


def parquet_bytes(columns: dict) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.table(columns), buffer)
    return buffer.getvalue()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    """A repository with a pin for synthetic files, and the 'server' contents by URL suffix."""
    contents = {
        esci.EXAMPLES: parquet_bytes(EXAMPLES),
        esci.PRODUCTS: parquet_bytes(PRODUCTS),
        "shopping_queries_dataset_sources.csv": b"query_id,source\n1,other\n",
    }
    pin = {
        "repository": "owner/repo",
        "commit": "test-commit",
        "folder": "ds",
        "license": "Apache-2.0",
    }
    blocks = ["[datasets.esci]\n" + "".join(f'{key} = "{value}"\n' for key, value in pin.items())]
    for name, content in contents.items():
        lfs = "true" if name.endswith(".parquet") else "false"
        checksum = hashlib.sha256(content).hexdigest()
        blocks.append(
            f'[[datasets.esci.files]]\nname = "{name}"\nlfs = {lfs}\n'
            f'size_bytes = {len(content)}\nsha256 = "{checksum}"\n'
        )
    (tmp_path / VERSIONS_FILE).parent.mkdir(parents=True)
    (tmp_path / VERSIONS_FILE).write_text("\n".join(blocks), encoding="utf-8")
    return tmp_path, contents


def opener_for(contents: dict[str, bytes], calls: list[str]):
    def opener(url: str, start: int) -> tuple[int, io.BytesIO]:
        calls.append(url)
        return 200, io.BytesIO(contents[url.rsplit("/", 1)[1]])

    return opener


def quiet(text: str) -> None:
    pass


def test_real_pin_matches_the_lfs_pointers() -> None:
    pin = esci.load_pin(REPO_ROOT)

    assert pin.commit == "7916cdf6ab75a462e77f20ab40428a10923998d5"  # pragma: allowlist secret
    assert pin.total_bytes == 1_161_827_075
    assert pin.url(pin.files[1]) == (
        "https://media.githubusercontent.com/media/amazon-science/esci-data/"
        "7916cdf6ab75a462e77f20ab40428a10923998d5/shopping_queries_dataset/shopping_queries_dataset_products.parquet"
    )
    assert pin.url(pin.files[2]).startswith("https://raw.githubusercontent.com/")


def test_dry_run_and_declined_confirmation_download_nothing(repo: tuple[Path, dict[str, bytes]]) -> None:
    root, contents = repo
    calls: list[str] = []

    assert esci.run_fetch(root, dry_run=True, opener=opener_for(contents, calls), write=quiet) == 0
    assert esci.run_fetch(root, ask=lambda _: "no", opener=opener_for(contents, calls), write=quiet) == 1
    assert calls == []
    assert not (root / esci.RAW_DIR).exists()


def test_fetch_records_provenance_and_a_second_run_downloads_nothing(
    repo: tuple[Path, dict[str, bytes]],
) -> None:
    root, contents = repo
    calls: list[str] = []

    assert esci.run_fetch(root, yes=True, opener=opener_for(contents, calls), write=quiet) == 0
    first = read_manifest(root)
    assert len(calls) == 3
    assert [entry.path for entry in first] == sorted(f"data/raw/esci/{name}" for name in contents)
    assert {entry.version for entry in first} == {"owner/repo@test-commit"}
    assert {entry.license for entry in first} == {"Apache-2.0"}

    calls.clear()
    assert esci.run_fetch(root, yes=True, opener=opener_for(contents, calls), write=quiet) == 0
    assert calls == []
    assert read_manifest(root) == first  # same download dates: nothing was downloaded again


def test_profile_counts_on_known_data(repo: tuple[Path, dict[str, bytes]]) -> None:
    root, contents = repo
    esci.run_fetch(root, yes=True, opener=opener_for(contents, []), write=quiet)

    assert esci.run_profile(root, write=quiet) == 0
    result = esci.profile(root / esci.RAW_DIR / esci.EXAMPLES, root / esci.RAW_DIR / esci.PRODUCTS)

    assert result["cells"][("us", "train", 1)] == (3, 1, {"E": 1, "S": 1, "I": 1})
    assert result["cells"][("us", "test", 0)] == (1, 1, {"C": 1})
    assert result["us_small"] == {
        "queries": 2,
        "judgments": 4,
        "products": 3,
        "per_query_min": 1,
        "per_query_median": 2.0,
        "per_query_max": 3,
    }
    assert result["products_per_locale"] == {"es": 1, "us": 4}
    text = (root / esci.PROFILE_FILE).read_text(encoding="utf-8")
    assert "| us | train | 1 | 3 | 1 | 33.3% | 33.3% | 0.0% | 33.3% |" in text
    assert "query_id" not in text.split("## ")[1]  # aggregates only: no rows, no queries


def test_profile_refuses_before_the_fetch(repo: tuple[Path, dict[str, bytes]]) -> None:
    root, _ = repo

    assert esci.run_profile(root, write=quiet) == 1


def test_manifest_upsert_keeps_other_entries_sorted(tmp_path: Path) -> None:
    def entry(path: str, sha: str = "1") -> ManifestEntry:
        return ManifestEntry(path, "https://x", "v1", sha, 10, "MIT", "2026-11-14T00:00:00Z")

    upsert_entries(tmp_path, [entry("data/raw/b"), entry("data/raw/a")])
    upsert_entries(tmp_path, [entry("data/raw/b", sha="2")])

    assert read_manifest(tmp_path) == [entry("data/raw/a"), entry("data/raw/b", sha="2")]
    assert render_manifest(read_manifest(tmp_path)).splitlines().count("[[file]]") == 2
    assert not list(tmp_path.glob("data/*.tmp"))


def test_invalid_manifest_is_reported(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manifest.toml").write_text("[[file]]\npath = 'x'\n", encoding="utf-8")

    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


def data_context(root: Path) -> DoctorContext:
    return DoctorContext(FakeSystem(), load_expected(REPO_ROOT / VERSIONS_FILE), root)


def test_doctor_warns_before_the_fetch_and_is_ok_after(repo: tuple[Path, dict[str, bytes]]) -> None:
    root, contents = repo

    assert {result.status for result in check_data(data_context(root))} == {Status.WARN}
    esci.run_fetch(root, yes=True, opener=opener_for(contents, []), write=quiet)
    assert {result.status for result in check_data(data_context(root))} == {Status.OK}


def test_doctor_fails_on_a_git_lfs_pointer_and_a_truncated_parquet(
    repo: tuple[Path, dict[str, bytes]],
) -> None:
    root, contents = repo
    esci.run_fetch(root, yes=True, opener=opener_for(contents, []), write=quiet)
    raw = root / esci.RAW_DIR
    (raw / esci.EXAMPLES).write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 51286808\n"
    )
    truncated = contents[esci.PRODUCTS][:-1] + b"X"
    (raw / esci.PRODUCTS).write_bytes(truncated)

    results = {result.name: result for result in check_data(data_context(root))}

    assert results["ESCI examples.parquet"].status is Status.FAIL
    assert "pointer" in results["ESCI examples.parquet"].found
    assert results["ESCI products.parquet"].status is Status.FAIL
    assert results["ESCI products.parquet"].found == "not a complete Parquet file"


def test_doctor_fails_when_the_file_is_not_recorded(repo: tuple[Path, dict[str, bytes]]) -> None:
    root, contents = repo
    esci.run_fetch(root, yes=True, opener=opener_for(contents, []), write=quiet)
    (root / "data" / "manifest.toml").unlink()

    assert {result.found for result in check_data(data_context(root))} == {"not in data/manifest.toml"}
