"""Value objects of the doctor: one CheckResult per line of the report."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class Fix:
    """A safe, repository- or user-level action that `--fix` may run after asking."""

    description: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    section: str
    name: str
    status: Status
    found: str = ""
    expected: str = ""
    hint: str = ""
    fix: Fix | None = None

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "section": self.section,
            "name": self.name,
            "status": self.status.value,
            "found": self.found,
            "expected": self.expected,
            "hint": self.hint,
            "fixable": self.fix is not None,
        }
