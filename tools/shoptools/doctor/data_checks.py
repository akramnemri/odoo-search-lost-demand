"""Doctor section `data`: the downloaded datasets match their pins and data/manifest.toml (Task 2.1: ESCI).

Fast and read-only: size, the Parquet marker at both ends (a Git LFS pointer file is ~130 bytes of
text), and the manifest entry. It does not re-hash 1.1 GB on every run; `shop data fetch` hashes before
recording. Before the first fetch the files are simply absent: WARN, not FAIL.
"""

from __future__ import annotations

from pathlib import Path

from shoptools.data.esci import RAW_DIR, EsciError, load_pin
from shoptools.data.manifest import ManifestError, read_manifest
from shoptools.doctor.checks import DoctorContext
from shoptools.doctor.model import CheckResult, Status

PARQUET_MAGIC = b"PAR1"
POINTER_PREFIX = b"version https://git-lfs"
FETCH_HINT = "uv run shop data fetch esci"


def check_data(context: DoctorContext) -> list[CheckResult]:
    try:
        pin = load_pin(context.repo_root)
        entries = {entry.path: entry for entry in read_manifest(context.repo_root)}
    except (EsciError, ManifestError) as error:
        return [CheckResult("data", "ESCI pin and manifest", Status.FAIL, str(error))]
    results = []
    for file in pin.files:
        path = context.repo_root / RAW_DIR / file.name
        entry = entries.get(pin.relative_path(file))
        results.append(_file_result(path, file.size_bytes, file.sha256, entry.sha256 if entry else None))
    return results


def _file_result(path: Path, size: int, sha256: str, recorded_sha256: str | None) -> CheckResult:
    name = f"ESCI {path.name.removeprefix('shopping_queries_dataset_')}"
    expected = f"{size:,} bytes, recorded in data/manifest.toml"
    if not path.is_file():
        return CheckResult("data", name, Status.WARN, "not fetched", expected, FETCH_HINT)
    actual = path.stat().st_size
    with path.open("rb") as handle:
        head = handle.read(len(POINTER_PREFIX))
        if path.suffix == ".parquet" and actual >= len(PARQUET_MAGIC):
            handle.seek(actual - len(PARQUET_MAGIC))
            tail = handle.read()
        else:
            tail = PARQUET_MAGIC
    if head.startswith(POINTER_PREFIX):
        return CheckResult(
            "data", name, Status.FAIL, "Git LFS pointer file, not the data", expected, FETCH_HINT
        )
    if actual != size:
        return CheckResult("data", name, Status.FAIL, f"{actual:,} bytes", expected, FETCH_HINT)
    if path.suffix == ".parquet" and (not head.startswith(PARQUET_MAGIC) or tail != PARQUET_MAGIC):
        return CheckResult("data", name, Status.FAIL, "not a complete Parquet file", expected, FETCH_HINT)
    if recorded_sha256 != sha256:
        found = (
            "not in data/manifest.toml"
            if recorded_sha256 is None
            else "manifest SHA-256 differs from the pin"
        )
        return CheckResult("data", name, Status.FAIL, found, expected, FETCH_HINT)
    return CheckResult("data", name, Status.OK, f"{actual / 1e6:,.1f} MB, recorded")
