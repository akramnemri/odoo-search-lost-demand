from __future__ import annotations

import json

import pytest
from conftest import REPO_ROOT, FakeSystem

from shoptools.doctor.checks import DoctorContext
from shoptools.doctor.model import Status
from shoptools.doctor.odoo_checks import (
    MANIFEST,
    MODULE,
    check_odoo,
    health_result,
    manifest_version,
    module_result,
    psql_command,
)
from shoptools.doctor.system import HttpResponse
from shoptools.stack import ODOO_URL

HEALTH_URL = ODOO_URL + "/web/health"
MODULE_SQL = f"SELECT state, coalesce(latest_version, '') FROM ir_module_module WHERE name = '{MODULE}'"


@pytest.fixture
def ready(context: DoctorContext, fake_system: FakeSystem) -> FakeSystem:
    fake_system.http[HEALTH_URL] = HttpResponse(200, json.dumps({"status": "pass"}))
    fake_system.files[(context.repo_root / ".env").as_posix()] = "ODOO_DB_NAME=shop\n"
    fake_system.files[(context.repo_root / MANIFEST).as_posix()] = '{"name": "x", "version": "19.0.0.1.0"}'
    sql = "SELECT 1 FROM pg_database WHERE datname = 'shop'"
    fake_system.respond(*psql_command(context, "postgres", sql), stdout="1\n")
    return fake_system


def test_everything_ok(context: DoctorContext, ready: FakeSystem) -> None:
    ready.respond(*psql_command(context, "shop", MODULE_SQL), stdout="installed|19.0.0.1.0\n")

    results = check_odoo(context)

    assert [(r.name, r.status) for r in results] == [
        ("health (/web/health)", Status.OK),
        ("database shop", Status.OK),
        (f"module {MODULE}", Status.OK),
    ]


def test_odoo_down_stops_the_section(context: DoctorContext, fake_system: FakeSystem) -> None:
    results = check_odoo(context)

    assert len(results) == 1
    assert results[0].status is Status.FAIL
    assert results[0].hint == "uv run shop up"


def test_missing_database(context: DoctorContext, ready: FakeSystem) -> None:
    sql = "SELECT 1 FROM pg_database WHERE datname = 'shop'"
    ready.respond(*psql_command(context, "postgres", sql), stdout="\n")

    results = check_odoo(context)

    assert results[-1].status is Status.FAIL
    assert results[-1].hint == "uv run shop db create"


def test_unsafe_database_name_is_not_put_in_sql(context: DoctorContext, ready: FakeSystem) -> None:
    ready.files[(context.repo_root / ".env").as_posix()] = "ODOO_DB_NAME=shop'; drop\n"

    results = check_odoo(context)

    assert results[-1].status is Status.SKIP
    assert not ready.calls  # no psql command ran


def test_module_not_installed_is_a_warning(context: DoctorContext, ready: FakeSystem) -> None:
    ready.respond(*psql_command(context, "shop", MODULE_SQL), stdout="uninstalled|\n")

    assert check_odoo(context)[-1].status is Status.WARN


def test_real_manifest_version_is_readable() -> None:
    assert manifest_version((REPO_ROOT / MANIFEST).read_text(encoding="utf-8")).startswith("19.0.")


@pytest.mark.parametrize(
    ("stdout", "status", "found"),
    [
        ("installed|19.0.0.1.0\n", Status.OK, "installed 19.0.0.1.0"),
        ("installed|19.0.0.0.9\n", Status.WARN, "installed 19.0.0.0.9"),
        ("", Status.WARN, "not in the Apps list"),
        ("to install|\n", Status.WARN, "to install"),
        (None, Status.FAIL, "cannot query the database"),
    ],
)
def test_module_result(stdout: str | None, status: Status, found: str) -> None:
    result = module_result(stdout, "19.0.0.1.0")

    assert (result.status, result.found) == (status, found)


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (HttpResponse(200, '{"status": "pass"}'), Status.OK),
        (HttpResponse(500, '{"status": "fail"}'), Status.FAIL),
        (HttpResponse(200, "<html>"), Status.FAIL),
        (None, Status.FAIL),
    ],
)
def test_health_result(response: HttpResponse | None, status: Status) -> None:
    assert health_result(response).status is status


@pytest.mark.parametrize("text", [None, "", "not python", "['a list']"])
def test_unreadable_manifest(text: str | None) -> None:
    assert manifest_version(text) == ""
