from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from shoptools import stack
from shoptools.cli import main
from shoptools.stack import (
    ServiceState,
    down_command,
    logs_command,
    parse_ps,
    up_command,
)

ROOT = Path("C:/work/odoo-search-lost-demand")
COMPOSE = ["docker", "compose", "--project-directory", str(ROOT), "-f", str(ROOT / "compose.yaml")]


def test_up_waits_for_health_and_starts_every_service() -> None:
    assert up_command(ROOT) == [*COMPOSE, "up", "-d", "--wait", "--wait-timeout", "300"]


def test_up_without_kibana_names_every_other_service() -> None:
    command = up_command(ROOT, no_kibana=True)

    assert command[-4:] == ["db", "elasticsearch", "es-setup", "odoo"]
    assert "kibana" not in command


def test_down_never_removes_volumes() -> None:
    command = down_command(ROOT)

    assert command == [*COMPOSE, "down"]
    assert not {"-v", "--volumes", "--rmi"} & set(command)


def test_logs_command_options() -> None:
    assert logs_command(ROOT, None, follow=False, tail=200) == [*COMPOSE, "logs", "--tail", "200"]
    assert logs_command(ROOT, "odoo", follow=True, tail=50) == [
        *COMPOSE,
        "logs",
        "--tail",
        "50",
        "--follow",
        "odoo",
    ]


ROWS = [
    {"Service": "db", "State": "running", "Health": "healthy", "ExitCode": 0, "Name": "x-db-1"},
    {"Service": "es-setup", "State": "exited", "Health": "", "ExitCode": 1},
]


def test_parse_ps_reads_one_object_per_line() -> None:
    stdout = "\n".join(json.dumps(row) for row in ROWS) + "\n"

    assert parse_ps(stdout) == [
        ServiceState("db", "running", "healthy", 0),
        ServiceState("es-setup", "exited", "", 1),
    ]


def test_parse_ps_reads_a_json_array_from_older_compose() -> None:
    assert [state.service for state in parse_ps(json.dumps(ROWS))] == ["db", "es-setup"]


def test_parse_ps_with_no_containers() -> None:
    assert parse_ps("") == []
    assert parse_ps("[]") == []


def test_describe_states() -> None:
    assert stack.describe(ServiceState("db", "running", "healthy", 0)) == "running (healthy)"
    assert stack.describe(ServiceState("es-setup", "exited", "", 1)) == "exited (1)"
    assert stack.describe(ServiceState("x", "created", "", 0)) == "created"


# --- shop up preconditions (no Docker call reaches the real daemon) ---


def test_up_refuses_without_env(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert stack.run_up(tmp_path, images=["postgres:16"]) == 1
    assert "uv run shop env init" in capsys.readouterr().err


def test_up_refuses_to_pull_missing_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        missing = command[:3] == ["docker", "image", "inspect"] and "kibana" in command[-1]
        return subprocess.CompletedProcess(command, returncode=1 if missing else 0, stdout="", stderr="")

    monkeypatch.setattr(stack, "_run", fake_run)
    images = ["postgres:16", "docker.elastic.co/kibana/kibana:9.5.5"]

    assert stack.run_up(tmp_path, images) == 1
    assert "docker.elastic.co/kibana/kibana:9.5.5" in capsys.readouterr().err
    assert not any("up" in command for command in calls), "must not start (and pull) anything"

    # Without Kibana, its image is not needed, so the stack starts.
    calls.clear()
    assert stack.run_up(tmp_path, images, no_kibana=True) == 0
    assert calls[-1] == up_command(tmp_path, no_kibana=True)


def test_up_reports_docker_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(
        stack, "_run", lambda command, capture=False: subprocess.CompletedProcess(command, 1, "", "")
    )

    assert stack.run_up(tmp_path, images=[]) == 1
    assert "Docker is not running" in capsys.readouterr().err


def test_logs_rejects_unknown_service() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["logs", "postgres"])

    assert exit_info.value.code == 2


def test_docker_calls_never_read_the_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # `docker compose exec` forwards stdin: it swallowed the confirmation typed for `shop db reset`.
    received: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        received.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    stack._run(["docker", "compose", "exec", "-T", "db", "psql"], capture=True)

    assert received["stdin"] is subprocess.DEVNULL
