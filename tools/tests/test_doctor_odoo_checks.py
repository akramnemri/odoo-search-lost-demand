from __future__ import annotations

import json

import pytest
from conftest import REPO_ROOT, FakeSystem

from shoptools.doctor.checks import DoctorContext
from shoptools.doctor.model import Status
from shoptools.doctor.odoo_checks import (
    MANIFEST,
    MODULE,
    PRODUCTS_TO_INDEX_SQL,
    QUEUE_SQL,
    check_odoo,
    health_result,
    index_queue_result,
    manifest_version,
    module_result,
    psql_command,
)
from shoptools.doctor.system import HttpResponse
from shoptools.stack import ELASTICSEARCH_URL, ODOO_URL

HEALTH_URL = ODOO_URL + "/web/health"
NL = chr(10)
MODULE_SQL = f"SELECT state, coalesce(latest_version, '') FROM ir_module_module WHERE name = '{MODULE}'"


@pytest.fixture
def ready(context: DoctorContext, fake_system: FakeSystem) -> FakeSystem:
    fake_system.http[HEALTH_URL] = HttpResponse(200, json.dumps({"status": "pass"}))
    fake_system.files[(context.repo_root / ".env").as_posix()] = (
        "ODOO_DB_NAME=shop\nSHOP_TOOLS_ES_PASSWORD=tools-value\n"  # pragma: allowlist secret
    )
    fake_system.files[(context.repo_root / MANIFEST).as_posix()] = '{"name": "x", "version": "19.0.0.1.0"}'
    sql = "SELECT 1 FROM pg_database WHERE datname = 'shop'"
    fake_system.respond(*psql_command(context, "postgres", sql), stdout="1\n")
    return fake_system


def test_everything_ok(context: DoctorContext, ready: FakeSystem) -> None:
    ready.respond(*psql_command(context, "shop", MODULE_SQL), stdout="installed|19.0.0.1.0\n")
    ready.respond(*psql_command(context, "shop", QUEUE_SQL), stdout="0|0|0" + NL)
    _index(context, ready, products=19869, documents=19869)

    results = check_odoo(context)

    assert [(r.name, r.status) for r in results] == [
        ("health (/web/health)", Status.OK),
        ("database shop", Status.OK),
        (f"module {MODULE}", Status.OK),
        ("product changes waiting", Status.OK),
        ("product index count", Status.OK),
    ]
    assert results[-1].found == "19,869 documents for 19,869 products"
    assert ready.http_auth[COUNT_URL] == ("shop_tools", "tools-value")


COUNT_URL = f"{ELASTICSEARCH_URL}/shop-products/_count"


def _index(context: DoctorContext, system: FakeSystem, products: int, documents: int | None) -> None:
    system.respond(*psql_command(context, "shop", PRODUCTS_TO_INDEX_SQL), stdout=f"{products}\n")
    status, body = (404, {"status": 404}) if documents is None else (200, {"count": documents})
    system.http[COUNT_URL] = HttpResponse(status, json.dumps(body))


@pytest.mark.parametrize(
    ("documents", "found"),
    [(19868, "19,868 documents for 19,869 products"), (None, "19,869 products, no product index")],
)
def test_product_index_count_differs(
    context: DoctorContext, ready: FakeSystem, documents: int | None, found: str
) -> None:
    ready.respond(*psql_command(context, "shop", MODULE_SQL), stdout="installed|19.0.0.1.0\n")
    _index(context, ready, products=19869, documents=documents)

    result = check_odoo(context)[-1]

    assert (result.name, result.status, result.found) == ("product index count", Status.WARN, found)
    assert result.hint == "uv run shop index rebuild"


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


@pytest.mark.parametrize(
    ("output", "status", "found"),
    [
        ("0|0|0" + NL, Status.OK, "none"),
        ("3|12|0" + NL, Status.OK, "3 rows, oldest 12 s"),
        ("1200|900|0" + NL, Status.WARN, "1,200 rows, oldest 900 s"),
        ("2|40|1" + NL, Status.WARN, "2 rows, oldest 40 s, 1 refused 10+ times"),
        (None, Status.SKIP, "no outbox (module older than 19.0.0.4.0?)"),
    ],
)
def test_product_changes_waiting(output: str | None, status: Status, found: str) -> None:
    result = index_queue_result(output)
    assert (result.name, result.status, result.found) == ("product changes waiting", status, found)
