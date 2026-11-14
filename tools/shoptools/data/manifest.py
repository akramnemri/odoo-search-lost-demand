"""`data/manifest.toml`: provenance of every downloaded data file (docs/ai/04_DATA_SEARCH_EVALUATION.md §2).

One `[[file]]` table per file. The file is committed; the data is not. Written atomically (temporary file, then
rename), entries sorted by path so the same downloads always give the same text.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

MANIFEST_FILE = Path("data") / "manifest.toml"
HEADER = (
    "# Provenance of every downloaded data file (filled by `uv run shop data fetch`, checked by the doctor).\n"
    "# One [[file]] table per file: path, source_url, version, sha256, size_bytes, license, downloaded_at.\n"
)


class ManifestError(Exception):
    """data/manifest.toml is missing a field or is not valid TOML."""


@dataclass(frozen=True)
class ManifestEntry:
    path: str  # relative to the repository root, forward slashes
    source_url: str
    version: str  # source commit or dataset version
    sha256: str
    size_bytes: int
    license: str
    downloaded_at: str  # ISO 8601, UTC


def read_manifest(repo_root: Path) -> list[ManifestEntry]:
    path = repo_root / MANIFEST_FILE
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return [ManifestEntry(**{f.name: row[f.name] for f in fields(ManifestEntry)}) for row in data.get("file", [])]
    except (tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise ManifestError(f"{MANIFEST_FILE} is not valid: {error}") from error


def render_manifest(entries: list[ManifestEntry]) -> str:
    blocks = [HEADER]
    for entry in sorted(entries, key=lambda item: item.path):
        lines = ["[[file]]"]
        for field in fields(ManifestEntry):
            value = getattr(entry, field.name)
            line = f"{field.name} = {value}" if isinstance(value, int) else f'{field.name} = "{_escape(value)}"'
            # Checksums are public, not secrets; the marker keeps detect-secrets quiet on this committed file.
            lines.append(line + "  # pragma: allowlist secret" if field.name == "sha256" else line)
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


def upsert_entries(repo_root: Path, new_entries: list[ManifestEntry]) -> None:
    """Replace the entries with the same paths, keep the others, write atomically."""
    by_path = {entry.path: entry for entry in read_manifest(repo_root)}
    by_path.update({entry.path: entry for entry in new_entries})
    target = repo_root / MANIFEST_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".toml.tmp")
    temporary.write_text(render_manifest(list(by_path.values())), encoding="utf-8", newline="\n")
    os.replace(temporary, target)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
