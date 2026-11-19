from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shoptools.doctor.checks import GB, DoctorContext
from shoptools.doctor.expected import VERSIONS_FILE, Expected, load_expected
from shoptools.doctor.system import CommandResult, HttpResponse

REPO_ROOT = Path(__file__).resolve().parents[2]


def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein distance, optimal string alignment variant (an adjacent swap is one edit)."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[len(a)][len(b)]


@dataclass
class FakeSystem:
    """Replays recorded command outputs; commands without a recorded answer behave as 'not installed'."""

    platform: str = "Windows"
    commands: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    ram: int | None = 16_869_000_000
    cpus: int | None = 16
    disk_free: int = 68 * GB
    files: dict[str, str] = field(default_factory=dict)
    busy_ports: set[int] = field(default_factory=set)
    # url -> response; a URL without an entry behaves as "nothing listens there"
    http: dict[str, HttpResponse] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    http_auth: dict[str, tuple[str, str] | None] = field(default_factory=dict)

    def respond(self, *args: str, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.commands[args] = CommandResult(returncode, stdout, stderr)

    def run(
        self, args: Sequence[str], timeout: float = 15.0, encoding: str = "utf-8"
    ) -> CommandResult | None:
        self.calls.append(tuple(args))
        return self.commands.get(tuple(args))

    def os_description(self) -> str:
        return f"{self.platform} (fake)"

    def ram_bytes(self) -> int | None:
        return self.ram

    def cpu_count(self) -> int | None:
        return self.cpus

    def disk_free_bytes(self, path: Path) -> int:
        return self.disk_free

    def read_text(self, path: Path) -> str | None:
        return self.files.get(path.as_posix())

    def port_in_use(self, port: int) -> bool:
        return port in self.busy_ports

    def http_get(
        self,
        url: str,
        auth: tuple[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
    ) -> HttpResponse | None:
        self.http_auth[url] = auth
        return self.http.get(url)


@pytest.fixture
def expected() -> Expected:
    # The real file, so a broken versions.toml fails the tests too.
    return load_expected(REPO_ROOT / VERSIONS_FILE)


@pytest.fixture
def fake_system() -> FakeSystem:
    return FakeSystem()


@pytest.fixture
def context(fake_system: FakeSystem, expected: Expected, tmp_path: Path) -> DoctorContext:
    return DoctorContext(fake_system, expected, tmp_path)
