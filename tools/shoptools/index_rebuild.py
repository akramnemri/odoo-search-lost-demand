"""`uv run shop index rebuild [--check]` (Task 3.1).

Rebuild: runs the module's own rebuild (`lost_demand.product.index._rebuild`) in `odoo shell` inside the Odoo
container, as `shop db create` configures the shop: the same code as the settings button, and no API user
gets administrator rights (supervisor, 2026-11-19). Odoo's output goes to local/logs/index-rebuild.log.

--check: read-only, the doctor's check `product index count` (products Odoo indexes, counted in PostgreSQL,
vs. documents behind the alias, counted as `shop_tools`).
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from shoptools import odoodb
from shoptools.doctor.checks import DoctorContext
from shoptools.doctor.expected import VERSIONS_FILE, load_expected
from shoptools.doctor.model import Status
from shoptools.doctor.odoo_checks import index_count_check
from shoptools.doctor.system import RealSystem

RESULT_PREFIX = "SHOP_INDEX "
LOG_FILE = Path("local") / "logs" / "index-rebuild.log"

# Sent on stdin to `odoo shell`; its last line `SHOP_INDEX <json>` is the result. `odoo shell` rolls back at
# the end, which is right: a rebuild writes nothing in Odoo.
PROGRAM = f"""
import json
from odoo.exceptions import UserError

if "lost_demand.product.index" not in env.registry:
    outcome = {{"error": "the module website_sale_lost_demand 19.0.0.3.0 or later is not installed in this "
                         "database: upgrade it (Apps > Lost-Demand Search > Upgrade), then try again"}}
else:
    try:
        result = env["lost_demand.product.index"]._rebuild()
    except UserError as error:
        outcome = {{"error": str(error)}}
    else:
        outcome = {{"summary": result.summary(), "index": result.index, "documents": result.documents,
                   "seconds": round(result.seconds, 1), "synonyms_created": result.synonyms_created}}
print({RESULT_PREFIX!r} + json.dumps(outcome))
"""


def parse_result(stdout: str) -> dict[str, object]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line.removeprefix(RESULT_PREFIX))
    raise odoodb.SetupError(f"the rebuild printed no result: see {LOG_FILE.as_posix()}")


def run_check(repo_root: Path, write: Callable[[str], object] = sys.stdout.write) -> int:
    settings = odoodb.read_settings(repo_root / ".env")
    context = DoctorContext(RealSystem(), load_expected(repo_root / VERSIONS_FILE), repo_root)
    result = index_count_check(context, settings.db_name)
    write(f"{result.status.value:<5} {result.name}: {result.found}\n")
    if result.status is not Status.OK and result.hint:
        write(f"      fix: {result.hint}\n")
    return 0 if result.status is Status.OK else 1


def run_rebuild(
    repo_root: Path, check_only: bool = False, write: Callable[[str], object] = sys.stdout.write
) -> int:
    try:
        if check_only:
            return run_check(repo_root, write)
        settings = odoodb.read_settings(repo_root / ".env")
        odoodb.require_running_stack(repo_root)
        log_path = repo_root / LOG_FILE
        log_path.parent.mkdir(parents=True, exist_ok=True)
        write(
            f"Rebuilding the product index of database {settings.db_name!r} (a few minutes). "
            f"Odoo output: {LOG_FILE.as_posix()}\n"
        )
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            command = odoodb.shell_command(repo_root, settings.db_name)
            stdout = odoodb._run("index rebuild", command, log, PROGRAM, capture=True)  # noqa: SLF001
        outcome = parse_result(stdout)
    except odoodb.SetupError as error:
        write(f"shop index rebuild: {error}\n")
        return 1
    if "error" in outcome:
        write(f"shop index rebuild: {outcome['error']}\n")
        return 1
    write(f"{outcome['summary']} (whole command: {time.monotonic() - started:.0f} s)\n")
    if outcome.get("synonyms_created"):
        write("Created the empty synonyms set shop-synonyms (rules come in Task 3.6).\n")
    return run_check(repo_root, write)
