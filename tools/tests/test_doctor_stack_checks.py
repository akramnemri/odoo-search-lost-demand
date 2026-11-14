from __future__ import annotations

import json

import pytest
from conftest import FakeSystem

from shoptools.doctor.checks import DoctorContext
from shoptools.doctor.model import CheckResult, Status
from shoptools.doctor.stack_checks import check_elastic, check_kibana, check_stack, service_result
from shoptools.doctor.system import HttpResponse
from shoptools.stack import ELASTICSEARCH_URL, KIBANA_URL, ServiceState, ps_command

ENV_VALUES = {
    # Fake values for the tests, not real credentials.
    "SHOP_TOOLS_ES_PASSWORD": "tools-value",  # pragma: allowlist secret
    "KIBANA_PERSONAL_USER": "supervisor",
    "KIBANA_PERSONAL_PASSWORD": "kibana-value",  # pragma: allowlist secret
}
ENV = "".join(f"{key}={value}\n" for key, value in ENV_VALUES.items())


def by_name(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {result.name: result for result in results}


@pytest.fixture
def with_env(context: DoctorContext, fake_system: FakeSystem) -> FakeSystem:
    fake_system.files[(context.repo_root / ".env").as_posix()] = ENV
    return fake_system


def _ok(body: dict) -> HttpResponse:
    return HttpResponse(200, json.dumps(body))


# --- stack ---


def _ps(fake_system: FakeSystem, context: DoctorContext, rows: list[dict]) -> None:
    stdout = "\n".join(json.dumps(row) for row in rows)
    fake_system.respond(*ps_command(context.repo_root), stdout=stdout)


def _row(service: str, state: str = "running", health: str = "healthy", exit_code: int = 0) -> dict:
    return {"Service": service, "State": state, "Health": health, "ExitCode": exit_code}


def test_healthy_stack(context: DoctorContext, fake_system: FakeSystem) -> None:
    _ps(
        fake_system,
        context,
        [_row("db"), _row("elasticsearch"), _row("es-setup", "exited", ""), _row("kibana"), _row("odoo")],
    )

    assert {result.status for result in check_stack(context)} == {Status.OK}


def test_stack_not_started(context: DoctorContext, fake_system: FakeSystem) -> None:
    _ps(fake_system, context, [])

    [result] = check_stack(context)
    assert result.status is Status.FAIL
    assert result.hint == "uv run shop up"


def test_docker_not_reachable(context: DoctorContext) -> None:
    [result] = check_stack(context)  # no recorded answer: docker not installed or daemon down

    assert result.status is Status.FAIL
    assert "Docker" in result.found


@pytest.mark.parametrize(
    ("service", "state", "expected"),
    [
        ("odoo", ServiceState("odoo", "running", "unhealthy", 0), Status.FAIL),
        ("odoo", ServiceState("odoo", "running", "starting", 0), Status.WARN),
        ("odoo", ServiceState("odoo", "exited", "", 137), Status.FAIL),
        ("odoo", None, Status.FAIL),
        ("es-setup", ServiceState("es-setup", "exited", "", 0), Status.OK),
        ("es-setup", ServiceState("es-setup", "exited", "", 1), Status.FAIL),
        ("es-setup", ServiceState("es-setup", "running", "", 0), Status.WARN),
        ("kibana", None, Status.WARN),  # `shop up --no-kibana`
        ("kibana", ServiceState("kibana", "exited", "", 137), Status.FAIL),  # killed, e.g. out of memory
    ],
)
def test_service_decisions(service: str, state: ServiceState | None, expected: Status) -> None:
    assert service_result(service, state).status is expected


def test_failed_service_points_to_its_logs() -> None:
    result = service_result("es-setup", ServiceState("es-setup", "exited", "", 1))

    assert "uv run shop logs es-setup" in result.hint


# --- elastic ---


def _healthy_cluster(fake_system: FakeSystem, license_type: str = "basic") -> None:
    fake_system.http.update(
        {
            f"{ELASTICSEARCH_URL}/_security/_authenticate": _ok({"username": "shop_tools"}),
            f"{ELASTICSEARCH_URL}/_cluster/health": _ok({"status": "green"}),
            f"{ELASTICSEARCH_URL}/": _ok({"version": {"number": "9.5.5"}}),
            f"{ELASTICSEARCH_URL}/_license": _ok({"license": {"type": license_type, "status": "active"}}),
        }
    )


def test_healthy_elasticsearch_with_the_tools_user(context: DoctorContext, with_env: FakeSystem) -> None:
    _healthy_cluster(with_env)

    results = by_name(check_elastic(context))

    for name in ("login (shop_tools)", "cluster health", "version", "license"):
        assert results[name].status is Status.OK, name
    assert results["product index alias"].status is Status.SKIP
    assert with_env.http_auth[f"{ELASTICSEARCH_URL}/_license"] == ("shop_tools", "tools-value")


def test_trial_license_fails(context: DoctorContext, with_env: FakeSystem) -> None:
    _healthy_cluster(with_env, license_type="trial")

    result = by_name(check_elastic(context))["license"]
    assert result.status is Status.FAIL
    assert "ADR-004" in result.hint


def test_unreachable_elasticsearch_stops_the_section(context: DoctorContext, with_env: FakeSystem) -> None:
    [result] = check_elastic(context)

    assert result.status is Status.FAIL
    assert "no answer" in result.found
    assert "uv run shop up" in result.hint


def test_wrong_password_points_to_es_setup(context: DoctorContext, with_env: FakeSystem) -> None:
    with_env.http[f"{ELASTICSEARCH_URL}/_security/_authenticate"] = HttpResponse(401, "{}")

    [result] = check_elastic(context)
    assert result.status is Status.FAIL
    assert "es-setup" in result.hint


def test_yellow_and_red_cluster(context: DoctorContext, with_env: FakeSystem) -> None:
    _healthy_cluster(with_env)
    with_env.http[f"{ELASTICSEARCH_URL}/_cluster/health"] = _ok({"status": "yellow"})
    assert by_name(check_elastic(context))["cluster health"].status is Status.WARN

    with_env.http[f"{ELASTICSEARCH_URL}/_cluster/health"] = _ok({"status": "red"})
    assert by_name(check_elastic(context))["cluster health"].status is Status.FAIL


def test_unexpected_version_fails(context: DoctorContext, with_env: FakeSystem) -> None:
    _healthy_cluster(with_env)
    with_env.http[f"{ELASTICSEARCH_URL}/"] = _ok({"version": {"number": "9.4.0"}})

    assert by_name(check_elastic(context))["version"].status is Status.FAIL


def test_no_env_skips_elastic(context: DoctorContext) -> None:
    [result] = check_elastic(context)

    assert result.status is Status.SKIP


# --- kibana ---


def _kibana(fake_system: FakeSystem, level: str = "available", login_status: int = 200) -> None:
    fake_system.http[f"{KIBANA_URL}/api/status"] = HttpResponse(
        200 if level == "available" else 503, json.dumps({"status": {"overall": {"level": level}}})
    )
    fake_system.http[f"{KIBANA_URL}/internal/security/me"] = HttpResponse(login_status, "{}")


def test_kibana_available_and_personal_login(context: DoctorContext, with_env: FakeSystem) -> None:
    _kibana(with_env)

    results = by_name(check_kibana(context))

    assert results["status"].status is Status.OK
    assert results["login (supervisor)"].status is Status.OK
    assert with_env.http_auth[f"{KIBANA_URL}/internal/security/me"] == ("supervisor", "kibana-value")


@pytest.mark.parametrize(("level", "expected"), [("degraded", Status.WARN), ("unavailable", Status.FAIL)])
def test_kibana_not_available(
    context: DoctorContext, with_env: FakeSystem, level: str, expected: Status
) -> None:
    _kibana(with_env, level=level)

    assert by_name(check_kibana(context))["status"].status is expected


def test_kibana_rejects_the_personal_login(context: DoctorContext, with_env: FakeSystem) -> None:
    _kibana(with_env, login_status=401)

    assert by_name(check_kibana(context))["login (supervisor)"].status is Status.FAIL


def test_kibana_not_running_is_a_warning(context: DoctorContext, with_env: FakeSystem) -> None:
    [result] = check_kibana(context)

    assert result.status is Status.WARN
    assert "--no-kibana" in result.hint
