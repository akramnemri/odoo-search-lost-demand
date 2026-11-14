"""`uv run shop test tools|module`: the two test suites of the project (Task 1.3).

`test tools` runs pytest on the host: tools/tests, including the module's pure services/.

`test module [--es]` runs the module's Odoo tests inside the running `odoo` container, in a second Odoo
process next to the development server, on a throwaway database `shop_test` (never the shop database):
`odoo -d shop_test -i website_sale_lost_demand --test-tags ... --stop-after-init`. The 19.0 server creates
a missing database itself (odoo/cli/server.py::main) and starts its HTTP thread for HttpCase when tests are
enabled, even with --stop-after-init (odoo/service/server.py, ThreadedServer.start). That thread listens on
port 8079 inside the container only, and `--db-filter` lets it serve `shop_test` (odoo.conf allows only
the shop database). `shop_test` is dropped before and after each run (supervisor decision, 2026-11-06).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import IO

from shoptools import odoodb, stack

MODULE = "website_sale_lost_demand"
TEST_DB = "shop_test"
TEST_HTTP_PORT = 8079  # inside the container only; 8069 is the development server
LOG_FILE = Path("local") / "logs" / "test-module.log"
_SUMMARY = re.compile(r"(\d+) failed, (\d+) error\(s\) of (\d+) tests")


def test_tags(with_es: bool) -> str:
    # Odoo tag selector (odoo/tests/tag_selector.py): "/module" = the module's standard tests,
    # "-es" = minus the tests tagged `es`, which need the running Elasticsearch.
    return f"/{MODULE}" if with_es else f"/{MODULE},-es"


def run_command(repo_root: Path, with_es: bool) -> list[str]:
    return stack.compose_command(
        repo_root,
        "exec",
        "-T",
        "odoo",
        "odoo",
        "-c",
        odoodb.ODOO_CONFIG,
        "-d",
        TEST_DB,
        f"--db-filter=^{TEST_DB}$",
        f"--http-port={TEST_HTTP_PORT}",
        "-i",
        MODULE,
        f"--test-tags={test_tags(with_es)}",
        "--stop-after-init",
    )


def parse_summary(log_text: str) -> tuple[int, int, int] | None:
    """(failed, errors, tests) of the last summary line Odoo printed, or None."""
    matches = _SUMMARY.findall(log_text)
    if not matches:
        return None
    failed, errors, tests = matches[-1]
    return int(failed), int(errors), int(tests)


def failure_lines(log_text: str, limit: int = 20) -> list[str]:
    lines = [line for line in log_text.splitlines() if " ERROR " in line or " FAIL:" in line]
    return lines[:limit]


def _drop_test_db(repo_root: Path, log: IO[str]) -> None:
    # Only ever the throwaway test database: TEST_DB is a constant, never the shop database of .env.
    if odoodb.database_exists(repo_root, TEST_DB):
        odoodb._run("db drop", odoodb.drop_command(repo_root, TEST_DB), log)


def run_module_tests(repo_root: Path, with_es: bool, keep_db: bool = False) -> int:
    started = time.monotonic()
    log_path = repo_root / LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Odoo output: {log_path}")
    try:
        if odoodb.read_settings(repo_root / ".env").db_name == TEST_DB:
            raise odoodb.SetupError(f"ODOO_DB_NAME in .env is {TEST_DB!r}, the throwaway test database")
        odoodb.require_running_stack(repo_root)
        with log_path.open("w", encoding="utf-8") as log:
            _drop_test_db(repo_root, log)
            label = "unit + es" if with_es else "unit (without `es`)"
            print(f"Installing {MODULE} on a fresh {TEST_DB!r} and running its {label} tests (2-3 min) ...")
            log.write(f"\n### tests: {' '.join(run_command(repo_root, with_es))}\n")
            log.flush()
            result = subprocess.run(
                run_command(repo_root, with_es),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if not keep_db:
                _drop_test_db(repo_root, log)
    except (odoodb.SetupError, FileNotFoundError) as error:
        print(f"shop test module: {error}", file=sys.stderr)
        return 1

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    summary = parse_summary(log_text)
    seconds = time.monotonic() - started
    if result.returncode == 0 and summary is not None and summary[2] > 0 and summary[:2] == (0, 0):
        print(f"PASSED: {summary[2]} tests in {seconds:.0f} s.")
        return 0
    if summary is None:
        print("FAILED: Odoo printed no test summary (install error?).", file=sys.stderr)
    elif summary[2] == 0:
        print("FAILED: no test ran; check the test tags and tests/__init__.py.", file=sys.stderr)
    else:
        failed, errors, tests = summary
        print(f"FAILED: {failed} failed, {errors} error(s) of {tests} tests.", file=sys.stderr)
    for line in failure_lines(log_text):
        print(f"  {line}", file=sys.stderr)
    print(f"Full output: {log_path}", file=sys.stderr)
    return 1


def run_tool_tests(repo_root: Path, pytest_args: list[str]) -> int:
    # Same interpreter as `shop`, so the pinned pytest of uv.lock runs; pyproject.toml sets the paths.
    command = [sys.executable, "-m", "pytest", *pytest_args]
    return subprocess.run(command, cwd=repo_root, check=False).returncode
