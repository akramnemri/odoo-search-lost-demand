"""Doctor sections `stack`, `elastic` and `kibana`: the running Docker Compose stack.

Read-only: the state reported by Docker Compose, then HTTP GETs on the published ports with the users of
`.env` (the `shop_tools` user for Elasticsearch, the personal login for Kibana; never `elastic`).
"""

from __future__ import annotations

from typing import Any

from shoptools.doctor.checks import TROUBLESHOOTING, DoctorContext
from shoptools.doctor.model import CheckResult, Status
from shoptools.doctor.system import HttpResponse
from shoptools.envfile import parse_env
from shoptools.stack import (
    ELASTICSEARCH_URL,
    KIBANA_URL,
    ONE_SHOT_SERVICES,
    OPTIONAL_SERVICES,
    SERVICES,
    ServiceState,
    describe,
    parse_ps,
    ps_command,
)

UP_HINT = "uv run shop up"
# es-setup sets every password from .env on each run; re-running it repairs a mismatch.
PASSWORD_HINT = "the password in .env differs from the cluster: run `docker compose up -d es-setup`"


def _env(context: DoctorContext) -> dict[str, str]:
    text = context.system.read_text(context.repo_root / ".env")
    return parse_env(text) if text else {}


def _json(response: HttpResponse) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


# --- stack ---


def check_stack(context: DoctorContext) -> list[CheckResult]:
    output = context.system.run(ps_command(context.repo_root))
    if output is None or not output.ok:
        return [
            CheckResult(
                "stack",
                "containers",
                Status.FAIL,
                "Docker Compose not reachable",
                "stack running",
                f"start Docker Desktop, then `{UP_HINT}`",
            )
        ]
    states = {state.service: state for state in parse_ps(output.stdout)}
    if not states:
        return [CheckResult("stack", "containers", Status.FAIL, "not started", "stack running", UP_HINT)]
    return [service_result(service, states.get(service)) for service in SERVICES]


def service_result(service: str, state: ServiceState | None) -> CheckResult:
    name = f"service {service}"
    one_shot, optional = service in ONE_SHOT_SERVICES, service in OPTIONAL_SERVICES
    expected = "exited (0)" if one_shot else "running (healthy)"
    logs_hint = f"uv run shop logs {service}, see {TROUBLESHOOTING}"

    if state is None:
        if optional:
            return CheckResult(
                "stack", name, Status.WARN, "not created", expected, f"started with --no-kibana? `{UP_HINT}`"
            )
        return CheckResult("stack", name, Status.FAIL, "not created", expected, UP_HINT)

    found = describe(state)
    if one_shot:
        if state.state == "exited" and state.exit_code == 0:
            return CheckResult("stack", name, Status.OK, found, expected)
        if state.state in ("running", "created"):
            return CheckResult(
                "stack", name, Status.WARN, found, expected, "still running: wait and check again"
            )
        return CheckResult("stack", name, Status.FAIL, found, expected, logs_hint)

    if state.state == "running" and state.health == "healthy":
        return CheckResult("stack", name, Status.OK, found, expected)
    if state.state == "running" and state.health == "starting":
        return CheckResult(
            "stack", name, Status.WARN, found, expected, "still starting: wait and check again"
        )
    if optional and state.state == "created":
        return CheckResult(
            "stack", name, Status.WARN, found, expected, f"started with --no-kibana? `{UP_HINT}`"
        )
    return CheckResult("stack", name, Status.FAIL, found, expected, logs_hint)


# --- elastic ---


def check_elastic(context: DoctorContext) -> list[CheckResult]:
    password = _env(context).get("SHOP_TOOLS_ES_PASSWORD")
    if not password:
        return [CheckResult("elastic", "login (shop_tools)", Status.SKIP, "no password in .env (see [repo])")]
    auth = ("shop_tools", password)

    def get(path: str) -> HttpResponse | None:
        return context.system.http_get(ELASTICSEARCH_URL + path, auth=auth)

    login = login_result("elastic", "login (shop_tools)", ELASTICSEARCH_URL, get("/_security/_authenticate"))
    if login.status is not Status.OK:
        return [login]
    expected = context.expected
    return [
        login,
        cluster_health_result(get("/_cluster/health")),
        es_version_result(get("/"), expected.elasticsearch_version),
        license_result(get("/_license"), expected.elastic_license),
        CheckResult("elastic", "product index alias", Status.SKIP, "available from Task 3.1"),
        CheckResult("elastic", "event data stream", Status.SKIP, "available from Task 4.1"),
    ]


def login_result(section: str, name: str, url: str, response: HttpResponse | None) -> CheckResult:
    if response is None:
        return CheckResult(
            section, name, Status.FAIL, f"no answer at {url}", "HTTP 200", f"is the stack up? `{UP_HINT}`"
        )
    if response.status == 401:
        return CheckResult(section, name, Status.FAIL, "rejected (HTTP 401)", "HTTP 200", PASSWORD_HINT)
    if response.status != 200:
        return CheckResult(section, name, Status.FAIL, f"HTTP {response.status}", "HTTP 200", TROUBLESHOOTING)
    return CheckResult(section, name, Status.OK, "HTTP 200", "HTTP 200")


def _answer(response: HttpResponse | None) -> tuple[Any, str]:
    """Parsed JSON body, or None and the reason to report."""
    if response is None:
        return None, "no answer"
    if response.status != 200:
        return None, f"HTTP {response.status}"
    body = _json(response)
    return (body, "") if isinstance(body, dict) else (None, "unexpected answer")


def cluster_health_result(response: HttpResponse | None) -> CheckResult:
    body, problem = _answer(response)
    if body is None:
        return CheckResult("elastic", "cluster health", Status.FAIL, problem, "green")
    health = str(body.get("status", "unknown"))
    if health == "green":
        return CheckResult("elastic", "cluster health", Status.OK, health, "green")
    if health == "yellow":
        # One node: a replica can never be assigned, so every index needs number_of_replicas 0.
        return CheckResult(
            "elastic",
            "cluster health",
            Status.WARN,
            health,
            "green",
            "an index has replicas > 0 on a single node",
        )
    return CheckResult(
        "elastic", "cluster health", Status.FAIL, health, "green", "uv run shop logs elasticsearch"
    )


def es_version_result(response: HttpResponse | None, wanted: str) -> CheckResult:
    body, problem = _answer(response)
    if body is None:
        return CheckResult("elastic", "version", Status.FAIL, problem, wanted)
    found = str(body.get("version", {}).get("number", "unknown"))
    if found == wanted:
        return CheckResult("elastic", "version", Status.OK, found, wanted)
    return CheckResult(
        "elastic", "version", Status.FAIL, found, wanted, "compose.yaml and docs/setup/versions.toml disagree"
    )


def license_result(response: HttpResponse | None, wanted: str) -> CheckResult:
    body, problem = _answer(response)
    if body is None:
        return CheckResult("elastic", "license", Status.FAIL, problem, wanted)
    license_info = body.get("license", {})
    kind, state = str(license_info.get("type", "unknown")), str(license_info.get("status", "unknown"))
    found = f"{kind} ({state})"
    if kind == wanted and state == "active":
        return CheckResult("elastic", "license", Status.OK, found, f"{wanted} (active)")
    # Only the free Basic license is allowed, never a trial (ADR-004).
    return CheckResult(
        "elastic", "license", Status.FAIL, found, f"{wanted} (active)", "see ADR-004; never start a trial"
    )


# --- kibana ---


def check_kibana(context: DoctorContext) -> list[CheckResult]:
    status = context.system.http_get(KIBANA_URL + "/api/status")
    if status is None:
        return [
            CheckResult(
                "kibana",
                "status",
                Status.WARN,
                f"no answer at {KIBANA_URL}",
                "available",
                f"started with --no-kibana? `{UP_HINT}`",
            )
        ]
    results = [kibana_status_result(status)]

    env = _env(context)
    user, password = env.get("KIBANA_PERSONAL_USER"), env.get("KIBANA_PERSONAL_PASSWORD")
    if user and password:
        # Kibana answers /api/status without a login, so the personal login is checked separately.
        me = context.system.http_get(
            KIBANA_URL + "/internal/security/me",
            auth=(user, password),
            headers={"x-elastic-internal-origin": "kibana"},
        )
        results.append(login_result("kibana", f"login ({user})", KIBANA_URL, me))
    else:
        results.append(CheckResult("kibana", "personal login", Status.SKIP, "no login in .env (see [repo])"))
    results.append(CheckResult("kibana", "data views and dashboards", Status.SKIP, "available from Task 4.5"))
    return results


def kibana_status_result(response: HttpResponse) -> CheckResult:
    # A degraded or unavailable Kibana answers 503 with the same JSON body.
    body = _json(response)
    level = "unknown"
    if isinstance(body, dict):
        level = str(body.get("status", {}).get("overall", {}).get("level", "unknown"))
    if level == "available":
        return CheckResult("kibana", "status", Status.OK, level, "available")
    if level == "degraded":
        return CheckResult("kibana", "status", Status.WARN, level, "available", "uv run shop logs kibana")
    return CheckResult(
        "kibana",
        "status",
        Status.FAIL,
        f"{level} (HTTP {response.status})",
        "available",
        "uv run shop logs kibana",
    )
