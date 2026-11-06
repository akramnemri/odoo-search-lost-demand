"""Doctor section `odoo`: the Odoo server, the shop database and the module (Task 1.3).

Read-only. The health route is public (`/web/health`, odoo/addons/web/controllers/home.py::health).
The database and the module state are read with psql in the `db` container: the integration user has no
Settings rights, and only `base.group_system` may read `ir.module.module`
(odoo/addons/base/security/ir.model.access.csv), so JSON-2 cannot answer this.
"""

from __future__ import annotations

import ast
import re

from shoptools.doctor.checks import DoctorContext
from shoptools.doctor.model import CheckResult, Status
from shoptools.doctor.system import CommandResult, HttpResponse
from shoptools.envfile import parse_env
from shoptools.stack import ODOO_URL, compose_command

MODULE = "website_sale_lost_demand"
MANIFEST = f"addons/{MODULE}/__manifest__.py"
UP_HINT = "uv run shop up"
# Same rule as `shop db create`: a PostgreSQL identifier that is safe inside the SQL below.
_DB_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def psql_command(context: DoctorContext, database: str, sql: str) -> list[str]:
    return compose_command(
        context.repo_root, "exec", "-T", "db", "psql", "-U", "odoo", "-d", database, "-tAc", sql
    )


def check_odoo(context: DoctorContext) -> list[CheckResult]:
    health = health_result(context.system.http_get(ODOO_URL + "/web/health"))
    if health.status is not Status.OK:
        return [health]
    text = context.system.read_text(context.repo_root / ".env")
    db_name = (parse_env(text) if text else {}).get("ODOO_DB_NAME", "")
    if not _DB_NAME.match(db_name):
        return [
            health,
            CheckResult("odoo", "database", Status.SKIP, "no valid ODOO_DB_NAME in .env (see [repo])"),
        ]

    exists = context.system.run(
        psql_command(context, "postgres", f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
    )
    database = database_result(db_name, exists)
    if database.status is not Status.OK:
        return [health, database]

    wanted = manifest_version(context.system.read_text(context.repo_root / MANIFEST))
    row = context.system.run(
        psql_command(
            context,
            db_name,
            f"SELECT state, coalesce(latest_version, '') FROM ir_module_module WHERE name = '{MODULE}'",
        )
    )
    return [health, database, module_result(row.stdout if row and row.ok else None, wanted)]


def health_result(response: HttpResponse | None) -> CheckResult:
    name, expected = "health (/web/health)", "pass"
    if response is None:
        return CheckResult("odoo", name, Status.FAIL, f"no answer at {ODOO_URL}", expected, UP_HINT)
    try:
        body = response.json()
    except ValueError:
        body = None
    status = body.get("status") if isinstance(body, dict) else None
    if response.status == 200 and status == "pass":
        return CheckResult("odoo", name, Status.OK, "pass", expected)
    return CheckResult(
        "odoo",
        name,
        Status.FAIL,
        f"HTTP {response.status} {status or ''}".strip(),
        expected,
        "uv run shop logs odoo",
    )


def database_result(db_name: str, output: CommandResult | None) -> CheckResult:
    name = f"database {db_name}"
    if output is None or not output.ok:
        return CheckResult(
            "odoo", name, Status.FAIL, "cannot query PostgreSQL", "exists", "uv run shop logs db"
        )
    if output.stdout.strip() != "1":
        return CheckResult("odoo", name, Status.FAIL, "missing", "exists", "uv run shop db create")
    return CheckResult("odoo", name, Status.OK, "exists", "exists")


def manifest_version(text: str | None) -> str:
    """The `version` of the module's manifest (a Python dict literal), or "" when unreadable."""
    if not text:
        return ""
    try:
        manifest = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return ""
    return str(manifest.get("version", "")) if isinstance(manifest, dict) else ""


def module_result(stdout: str | None, wanted: str) -> CheckResult:
    name = f"module {MODULE}"
    expected = f"installed {wanted}".strip()
    if stdout is None:
        return CheckResult(
            "odoo", name, Status.FAIL, "cannot query the database", expected, "uv run shop logs db"
        )
    state, _, version = stdout.strip().partition("|")
    if state != "installed":
        found = state or "not in the Apps list"
        return CheckResult(
            "odoo",
            name,
            Status.WARN,
            found,
            expected,
            "Apps > Update Apps List, then install 'Lost-Demand Search' (restart Odoo after code changes)",
        )
    if wanted and version != wanted:
        return CheckResult(
            "odoo",
            name,
            Status.WARN,
            f"installed {version}",
            expected,
            "upgrade the module: Apps > Lost-Demand Search > Upgrade",
        )
    return CheckResult("odoo", name, Status.OK, f"installed {version}", expected)
