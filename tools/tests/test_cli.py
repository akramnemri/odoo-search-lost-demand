import subprocess
import sys

import pytest

from shoptools import __version__
from shoptools.cli import PLANNED_COMMANDS, main


def test_help_lists_every_planned_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    for name in PLANNED_COMMANDS:
        assert name in output


def test_no_command_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: shop" in capsys.readouterr().out


def test_version_matches_package_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out.strip() == f"shop {__version__}"


def test_placeholder_command_fails_and_names_its_task(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["replay", "--from", "2019-10-01"]) == 1
    assert "planned in Task 7.3" in capsys.readouterr().err


def test_doctor_rejects_unknown_options() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["doctor", "--sectoin", "machine"])

    assert exit_info.value.code == 2


def test_doctor_rejects_unknown_sections() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["doctor", "--section", "network"])

    assert exit_info.value.code == 2


def test_unknown_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["no-such-command"])

    assert exit_info.value.code == 2


def test_unknown_option_without_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--no-such-option"])

    assert exit_info.value.code == 2


def test_lint_runs_pre_commit_on_all_files_and_returns_its_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert main(["lint"]) == 1
    assert calls == [[sys.executable, "-m", "pre_commit", "run", "--all-files"]]
