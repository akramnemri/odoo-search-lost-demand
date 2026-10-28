"""Runs the doctor sections, renders the report (text or JSON), applies `--fix` and sets the exit code.

Exit codes: 0 = no FAIL, 1 = at least one FAIL, 2 = the doctor itself crashed.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from shoptools.doctor.checks import (
    DoctorContext,
    check_docker,
    check_machine,
    check_ports,
    check_repo,
    check_tools,
)
from shoptools.doctor.expected import VERSIONS_FILE, find_repo_root, load_expected
from shoptools.doctor.model import CheckResult, Status
from shoptools.doctor.system import RealSystem, System

SECTION_CHECKS: dict[str, Callable[[DoctorContext], list[CheckResult]]] = {
    "machine": check_machine,
    "tools": check_tools,
    "docker": check_docker,
    "ports": check_ports,
    "repo": check_repo,
}
# Sections built in later milestones: section -> task that adds it.
LATER_SECTIONS = {"stack": "1.1", "elastic": "1.1", "kibana": "1.1", "odoo": "1.3", "data": "2.1"}
SECTIONS = (*SECTION_CHECKS, *LATER_SECTIONS)

Ask = Callable[[str], bool]


def run_checks(sections: Sequence[str], context: DoctorContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    for section in sections:
        if section in SECTION_CHECKS:
            results.extend(SECTION_CHECKS[section](context))
        else:
            results.append(
                CheckResult(section, section, Status.SKIP, f"available from Task {LATER_SECTIONS[section]}")
            )
    return results


def exit_code(results: Sequence[CheckResult]) -> int:
    return 1 if any(result.status is Status.FAIL for result in results) else 0


def summarize(results: Sequence[CheckResult]) -> dict[str, int]:
    return {status.value: sum(result.status is status for result in results) for status in Status}


def render_text(results: Sequence[CheckResult], verbose: bool = False) -> str:
    width = max((len(result.name) for result in results), default=0)
    indent = " " * (2 + 4 + 2 + width + 2)
    lines: list[str] = []
    section = None
    for result in results:
        if result.section != section:
            section = result.section
            lines.append(f"[{section}]")
        detail = result.found
        if result.expected and (verbose or result.status in (Status.WARN, Status.FAIL)):
            detail += f"  (expected {result.expected})"
        lines.append(f"  {result.status.value:<4}  {result.name:<{width}}  {detail}".rstrip())
        if result.hint and (verbose or result.status in (Status.WARN, Status.FAIL)):
            lines.append(f"{indent}-> {result.hint}")
        if result.fix is not None and result.status is not Status.OK:
            lines.append(f"{indent}-> fixable with `uv run shop doctor --fix`")
    counts = summarize(results)
    lines.append("")
    lines.append("Summary: " + ", ".join(f"{count} {status}" for status, count in counts.items()))
    return "\n".join(lines)


def render_json(results: Sequence[CheckResult]) -> str:
    return json.dumps(
        {
            "results": [result.to_dict() for result in results],
            "summary": summarize(results),
            "exit_code": exit_code(results),
        },
        indent=2,
    )


def apply_fixes(results: Sequence[CheckResult], system: System, ask: Ask, out: TextIO) -> int:
    applied = 0
    for result in results:
        if result.fix is None or result.status is Status.OK:
            continue
        command = " ".join(result.fix.command)
        if not ask(f"{result.name}: {result.fix.description}\n  command: {command}\n  Apply? [y/N] "):
            out.write(f"  skipped: {result.name}\n")
            continue
        output = system.run(result.fix.command)
        if output is None or not output.ok:
            reason = "command not found" if output is None else (output.stderr or output.stdout)
            out.write(f"  failed: {result.name}: {reason}\n")
        else:
            out.write(f"  fixed: {result.name}\n")
            applied += 1
    return applied


def ask_in_terminal(question: str) -> bool:
    if not sys.stdin.isatty():
        sys.stderr.write("--fix needs an interactive terminal; nothing changed.\n")
        return False
    sys.stderr.write(question)
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


def run_doctor(
    sections: Sequence[str] | None = None,
    *,
    as_json: bool = False,
    verbose: bool = False,
    fix: bool = False,
    system: System | None = None,
    start: Path | None = None,
    ask: Ask = ask_in_terminal,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        repo_root = find_repo_root(start or Path.cwd())
        if repo_root is None:
            err.write(f"shop doctor: run it inside the repository ({VERSIONS_FILE.as_posix()} not found).\n")
            return 1
        context = DoctorContext(system or RealSystem(), load_expected(repo_root / VERSIONS_FILE), repo_root)
        selected = list(dict.fromkeys(sections)) if sections else list(SECTIONS)
        results = run_checks(selected, context)
        if fix and apply_fixes(results, context.system, ask, err):
            results = run_checks(selected, context)
        out.write((render_json(results) if as_json else render_text(results, verbose=verbose)) + "\n")
        return exit_code(results)
    except Exception as error:  # documented contract: exit code 2 when the doctor itself crashes
        err.write(f"shop doctor crashed: {error!r}\n")
        if verbose:
            err.write(traceback.format_exc())
        else:
            err.write("Run `uv run shop doctor --verbose` for the traceback.\n")
        return 2
