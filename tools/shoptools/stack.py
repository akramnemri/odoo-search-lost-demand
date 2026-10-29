"""`uv run shop up|down|status|logs`: drive the Docker Compose stack defined in compose.yaml.

Every command names compose.yaml and the repository explicitly, so it works from any folder of the checkout.
`shop down` never removes volumes: they hold the database and the indices (CLAUDE.md, hard rules).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

COMPOSE_FILE = "compose.yaml"
SERVICES = ("db", "elasticsearch", "es-setup", "kibana", "odoo")
ONE_SHOT_SERVICES = ("es-setup",)
OPTIONAL_SERVICES = ("kibana",)  # `shop up --no-kibana` on 8 GB machines (docs/ai/01_ARCHITECTURE.md §5.3)
WAIT_TIMEOUT_SECONDS = 300  # acceptance: a clean start is healthy in < 5 min once the images are pulled

ODOO_URL = "http://127.0.0.1:8069"
ELASTICSEARCH_URL = "http://127.0.0.1:9200"
KIBANA_URL = "http://127.0.0.1:5601"

_PROJECT_NAME = re.compile(r"^name:\s*([a-z0-9][a-z0-9_-]*)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ServiceState:
    service: str
    state: str  # running, exited, created, restarting, ...
    health: str  # healthy, unhealthy, starting, or "" without a healthcheck
    exit_code: int


def project_name(repo_root: Path) -> str:
    """The `name:` of compose.yaml; Compose's default (folder name) when the file does not set one."""
    compose = repo_root / COMPOSE_FILE
    if compose.is_file():
        match = _PROJECT_NAME.search(compose.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    return re.sub(r"[^a-z0-9_-]", "", repo_root.name.lower())


def compose_command(repo_root: Path, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(repo_root),
        "-f",
        str(repo_root / COMPOSE_FILE),
        *args,
    ]


def up_command(repo_root: Path, no_kibana: bool = False) -> list[str]:
    command = compose_command(repo_root, "up", "-d", "--wait", "--wait-timeout", str(WAIT_TIMEOUT_SECONDS))
    if no_kibana:
        command += [service for service in SERVICES if service not in OPTIONAL_SERVICES]
    return command


def down_command(repo_root: Path) -> list[str]:
    # Never `-v`: removing the volumes deletes the database and every index.
    return compose_command(repo_root, "down")


def ps_command(repo_root: Path) -> list[str]:
    return compose_command(repo_root, "ps", "--all", "--format", "json")


def logs_command(repo_root: Path, service: str | None, follow: bool, tail: int) -> list[str]:
    command = compose_command(repo_root, "logs", "--tail", str(tail))
    if follow:
        command.append("--follow")
    if service:
        command.append(service)
    return command


def parse_ps(stdout: str) -> list[ServiceState]:
    """Output of `docker compose ps --format json`: one object per line (Compose ≥ 2.21) or one JSON array."""
    text = stdout.strip()
    if not text:
        return []
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [
        ServiceState(
            service=row["Service"],
            state=row.get("State", ""),
            health=row.get("Health", ""),
            exit_code=int(row.get("ExitCode", 0)),
        )
        for row in rows
    ]


def describe(state: ServiceState) -> str:
    if state.state == "exited":
        return f"exited ({state.exit_code})"
    return f"{state.state} ({state.health})" if state.health else state.state


# --- commands (print for the person at the terminal) ---


def _run(command: list[str], capture: bool = False) -> subprocess.CompletedProcess[str] | None:
    """None when the docker executable is not installed."""
    try:
        # stdin closed: `docker compose exec` forwards stdin and would swallow what the person types next.
        return subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=capture,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None


def docker_reachable() -> bool:
    result = _run(["docker", "info", "--format", "{{.ServerVersion}}"], capture=True)
    return result is not None and result.returncode == 0


def missing_images(images: Sequence[str]) -> list[str]:
    missing = []
    for image in images:
        result = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture=True)
        if result is None or result.returncode != 0:
            missing.append(image)
    return missing


def run_up(repo_root: Path, images: Sequence[str], no_kibana: bool = False) -> int:
    if not (repo_root / ".env").is_file():
        print("shop up: .env is missing. Create it with `uv run shop env init`.", file=sys.stderr)
        return 1
    if not docker_reachable():
        print("shop up: Docker is not running. Start Docker Desktop, then retry.", file=sys.stderr)
        return 1
    wanted = [image for image in images if not (no_kibana and "/kibana:" in image)]
    missing = missing_images(wanted)
    if missing:
        # No surprise downloads (CLAUDE.md): pulling is a separate, explicit step.
        print("shop up: these images are not pulled yet:", file=sys.stderr)
        for image in missing:
            print(f"  {image}", file=sys.stderr)
        print(
            "Pull them with `docker compose pull`: about 2.3 GB for all four (docs/setup/VERSIONS.md).",
            file=sys.stderr,
        )
        return 1

    result = _run(up_command(repo_root, no_kibana))
    if result is None or result.returncode != 0:
        print(
            "shop up: the stack did not become healthy. See `uv run shop status` and "
            "`uv run shop logs <service>` (often es-setup), and docs/setup/TROUBLESHOOTING.md.",
            file=sys.stderr,
        )
        return 1
    print()
    print(f"Odoo           {ODOO_URL}")
    print(f"Elasticsearch  {ELASTICSEARCH_URL}")
    print(f"Kibana         {KIBANA_URL}" + ("  (not started: --no-kibana)" if no_kibana else ""))
    print("Logins and passwords: .env (KIBANA_PERSONAL_USER / KIBANA_PERSONAL_PASSWORD for Kibana).")
    return 0


def run_down(repo_root: Path) -> int:
    result = _run(down_command(repo_root))
    if result is None:
        print("shop down: docker is not installed.", file=sys.stderr)
        return 1
    if result.returncode == 0:
        print("Stack stopped. Volumes (database, indices) are kept.")
    return result.returncode


def run_status(repo_root: Path) -> int:
    result = _run(ps_command(repo_root), capture=True)
    if result is None or result.returncode != 0:
        print("shop status: Docker is not reachable. Start Docker Desktop, then retry.", file=sys.stderr)
        return 1
    states = {state.service: state for state in parse_ps(result.stdout)}
    if not states:
        print("Stack not started. Start it with `uv run shop up`.")
        return 0
    for service in SERVICES:
        state = states.get(service)
        print(f"{service:<14} {describe(state) if state else 'not created'}")
    print()
    print(f"Odoo {ODOO_URL}  Elasticsearch {ELASTICSEARCH_URL}  Kibana {KIBANA_URL}")
    return 0


def run_logs(repo_root: Path, service: str | None, follow: bool, tail: int) -> int:
    result = _run(logs_command(repo_root, service, follow, tail))
    if result is None:
        print("shop logs: docker is not installed.", file=sys.stderr)
        return 1
    return result.returncode
