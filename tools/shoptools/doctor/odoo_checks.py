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
from shoptools.doctor.stack_checks import REBUILD_HINT, product_index_documents
from shoptools.doctor.system import CommandResult, HttpResponse
from shoptools.envfile import parse_env
from shoptools.stack import ODOO_URL, compose_command

MODULE = "website_sale_lost_demand"
MANIFEST = f"addons/{MODULE}/__manifest__.py"
UP_HINT = "uv run shop up"
# Products the module indexes: the domain of lost_demand.product.index._indexable_domain (active, sale_ok).
PRODUCTS_TO_INDEX_SQL = "SELECT count(*) FROM product_template WHERE sale_ok AND active"
# Outbox of product changes (Task 3.2, lost_demand.index.queue): rows, age of the oldest in seconds, rows
# refused 10 times or more (services/index_sync.py FAILING_AFTER_ATTEMPTS). Datetimes are naive UTC in Odoo.
QUEUE_SQL = (
    "SELECT count(*), coalesce(floor(extract(epoch FROM (now() AT TIME ZONE 'utc') - min(enqueued_at))), 0), "
    "count(*) FILTER (WHERE attempts >= 10) FROM lost_demand_index_queue"
)
QUEUE_MAX_AGE_SECONDS = 300  # FR1 wants 60 s; 5 min leaves room for a rebuild or a restart
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
    module = module_result(row.stdout if row and row.ok else None, wanted)
    queue = index_queue_check(context, db_name)
    return [health, database, module, queue, index_count_check(context, db_name)]


def index_count_check(context: DoctorContext, db_name: str) -> CheckResult:
    """Products Odoo would index vs. documents behind the alias (also `shop index rebuild --check`)."""
    rows = context.system.run(psql_command(context, db_name, PRODUCTS_TO_INDEX_SQL))
    text = rows.stdout.strip() if rows is not None and rows.ok else ""
    return index_count_result(int(text) if text.isdigit() else None, product_index_documents(context))


def index_queue_check(context: DoctorContext, db_name: str) -> CheckResult:
    """Product changes waiting to reach the index (module 19.0.0.4.0 and later)."""
    rows = context.system.run(psql_command(context, db_name, QUEUE_SQL))
    return index_queue_result(rows.stdout if rows is not None and rows.ok else None)


def index_queue_result(output: str | None) -> CheckResult:
    name, expected = "product changes waiting", f"none older than {QUEUE_MAX_AGE_SECONDS // 60} min"
    parts = (output or "").strip().split("|")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return CheckResult("odoo", name, Status.SKIP, "no outbox (module older than 19.0.0.4.0?)", expected)
    waiting, oldest, refused = (int(part) for part in parts)
    if not waiting:
        return CheckResult("odoo", name, Status.OK, "none", expected)
    found = f"{waiting:,} rows, oldest {oldest} s" + (f", {refused:,} refused 10+ times" if refused else "")
    if refused or oldest > QUEUE_MAX_AGE_SECONDS:
        hint = (
            "Settings > Website > Product changes; `uv run shop logs odoo` (Elasticsearch up? index rebuilt?)"
        )
        return CheckResult("odoo", name, Status.WARN, found, expected, hint)
    return CheckResult("odoo", name, Status.OK, found, expected)


def index_count_result(products: int | None, documents: int | None) -> CheckResult:
    name, expected = "product index count", "one document per product"
    if products is None:
        return CheckResult(
            "odoo", name, Status.WARN, "cannot count the products", expected, "uv run shop logs db"
        )
    if documents is None:
        return CheckResult(
            "odoo", name, Status.WARN, f"{products:,} products, no product index", expected, REBUILD_HINT
        )
    found = f"{documents:,} documents for {products:,} products"
    if documents == products:
        return CheckResult("odoo", name, Status.OK, found, expected)
    # Since Task 3.2 changes reach the index within a minute: a lasting difference means the sync is
    # stuck (see `product changes waiting`) or the index was built before products were added in bulk.
    return CheckResult("odoo", name, Status.WARN, found, expected, REBUILD_HINT)


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
