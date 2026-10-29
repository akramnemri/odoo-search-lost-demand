"""Expected versions and thresholds, read from docs/setup/versions.toml (kept in sync with VERSIONS.md)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from shoptools.doctor.model import Status

VERSIONS_FILE = Path("docs") / "setup" / "versions.toml"

_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")

Version = tuple[int, int, int]


def parse_version(text: str) -> Version | None:
    """First `major.minor[.patch]` in a tool's output, e.g. 'git version 2.51.0.windows.2' -> (2, 51, 0)."""
    match = _VERSION_PATTERN.search(text)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def version_at_least(found: Version, minimum: str) -> bool:
    required = parse_version(minimum)
    if required is None:
        raise ValueError(f"invalid minimum version in versions.toml: {minimum!r}")
    return found >= required


def find_repo_root(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        if (directory / VERSIONS_FILE).is_file() and (directory / "pyproject.toml").is_file():
            return directory
    return None


@dataclass(frozen=True)
class ToolRequirement:
    min_version: str
    severity: Status  # status when missing or too old: FAIL, or WARN for optional tools


@dataclass(frozen=True)
class Expected:
    tools: dict[str, ToolRequirement]
    host_python: str
    stack_images: tuple[str, ...]
    elasticsearch_version: str
    elastic_license: str
    ram_gb_recommended: float
    ram_gb_min: float
    disk_free_gb_warn: float
    disk_free_gb_fail: float
    vm_max_map_count_min: int
    docker_memory_gb: dict[str, float]
    ports: tuple[int, ...]


def load_expected(path: Path) -> Expected:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tools = {
        name: ToolRequirement(
            min_version=spec["min"],
            severity=Status.WARN if spec.get("severity") == "warn" else Status.FAIL,
        )
        for name, spec in data["tools"].items()
    }
    machine = data["machine"]
    return Expected(
        tools=tools,
        host_python=data["python"]["host"],
        stack_images=tuple(value for key, value in data["stack"].items() if key.endswith("_image")),
        elasticsearch_version=data["stack"]["elasticsearch_version"],
        elastic_license=data["stack"]["elastic_license"],
        ram_gb_recommended=float(machine["ram_gb_recommended"]),
        ram_gb_min=float(machine["ram_gb_min"]),
        disk_free_gb_warn=float(machine["disk_free_gb_warn"]),
        disk_free_gb_fail=float(machine["disk_free_gb_fail"]),
        vm_max_map_count_min=int(machine["vm_max_map_count_min"]),
        docker_memory_gb={name: float(value) for name, value in machine["docker_memory_gb"].items()},
        ports=tuple(int(port) for port in data["ports"]["required_free"]),
    )
