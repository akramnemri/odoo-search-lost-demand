from __future__ import annotations

import io
import json
from pathlib import Path

from conftest import REPO_ROOT, FakeSystem

from shoptools.doctor.model import CheckResult, Fix, Status
from shoptools.doctor.report import SECTIONS, apply_fixes, exit_code, render_json, render_text, run_doctor

OK = CheckResult("machine", "RAM", Status.OK, "16.9 GB", ">= 16 GB")
WARN = CheckResult(
    "repo",
    "core.autocrlf",
    Status.WARN,
    "true",
    "false",
    "git config --local core.autocrlf false",
    fix=Fix("set core.autocrlf=false", ("git", "config", "--local", "core.autocrlf", "false")),
)
FAIL = CheckResult("ports", "port 8069", Status.FAIL, "in use by another program", "free", "stop it")


def test_exit_code_is_one_only_when_something_fails() -> None:
    assert exit_code([OK, WARN]) == 0
    assert exit_code([OK, FAIL]) == 1


def test_text_report_is_ascii_and_shows_hints_for_problems_only() -> None:
    text = render_text([OK, WARN, FAIL])

    text.encode("ascii")  # Windows consoles redirected to a file may not accept other characters
    assert "-> git config --local core.autocrlf false" in text
    assert "-> fixable with `uv run shop doctor --fix`" in text
    assert "(expected >= 16 GB)" not in text  # expected values only for problems, unless --verbose
    assert "Summary: 1 OK, 1 WARN, 1 FAIL, 0 SKIP" in text


def test_verbose_report_shows_expected_values_for_every_line() -> None:
    assert "(expected >= 16 GB)" in render_text([OK], verbose=True)


def test_json_report() -> None:
    report = json.loads(render_json([OK, FAIL]))

    assert report["exit_code"] == 1
    assert report["summary"] == {"OK": 1, "WARN": 0, "FAIL": 1, "SKIP": 0}
    assert report["results"][1]["name"] == "port 8069"


def test_fix_runs_only_after_a_yes() -> None:
    system = FakeSystem()
    system.respond("git", "config", "--local", "core.autocrlf", "false")
    out = io.StringIO()

    assert apply_fixes([WARN], system, ask=lambda question: False, out=out) == 0
    assert system.calls == []
    assert apply_fixes([WARN], system, ask=lambda question: True, out=out) == 1
    assert system.calls == [("git", "config", "--local", "core.autocrlf", "false")]


def test_failed_fix_is_reported() -> None:
    system = FakeSystem()
    system.respond(
        "git", "config", "--local", "core.autocrlf", "false", returncode=1, stderr="permission denied"
    )
    out = io.StringIO()

    assert apply_fixes([WARN], system, ask=lambda question: True, out=out) == 0
    assert "failed: core.autocrlf: permission denied" in out.getvalue()


def test_later_sections_are_skipped_with_their_task() -> None:
    out = io.StringIO()
    code = run_doctor(["odoo", "data"], as_json=True, system=FakeSystem(), start=REPO_ROOT, out=out)
    report = json.loads(out.getvalue())

    assert code == 0
    assert [(result["section"], result["status"], result["found"]) for result in report["results"]] == [
        ("odoo", "SKIP", "available from Task 1.3"),
        ("data", "SKIP", "available from Task 2.1"),
    ]


def test_all_sections_run_by_default_and_a_failure_sets_exit_code_one() -> None:
    out = io.StringIO()
    system = FakeSystem(busy_ports={8069})  # nothing installed and a busy port: several FAIL lines
    code = run_doctor(system=system, start=REPO_ROOT, out=out, err=io.StringIO())

    assert code == 1
    for section in SECTIONS:
        assert f"[{section}]" in out.getvalue()


def test_outside_the_repository_exits_one(tmp_path: Path) -> None:
    err = io.StringIO()

    assert run_doctor(system=FakeSystem(), start=tmp_path, out=io.StringIO(), err=err) == 1
    assert "run it inside the repository" in err.getvalue()


def test_a_crash_exits_two() -> None:
    class BrokenSystem(FakeSystem):
        def ram_bytes(self) -> int | None:
            raise RuntimeError("probe exploded")

    err = io.StringIO()
    code = run_doctor(["machine"], system=BrokenSystem(), start=REPO_ROOT, out=io.StringIO(), err=err)

    assert code == 2
    assert "probe exploded" in err.getvalue()
