"""`uv run shop db create|reset`: create the shop database in the running stack (Task 1.2a).

Every step runs inside the `odoo` container with Odoo's own 19.0 commands (read in .odoo-src/odoo/cli/):
`odoo db init` (empty database, English, no demo data: `--with-demo` is opt-in in 19.0),
`odoo module install` (the shop apps), then `odoo shell` with odoo_scripts/configure_shop.py (names,
admin password, integration user, API key). The host then writes the API key to `.env` and proves it
works with one JSON-2 call: XML-RPC and JSON-RPC are deprecated in 19.0 and removed in 22
(.odoo-src/odoo/addons/rpc/controllers/__init__.py).

Secrets travel on stdin only, never on a command line, and are never printed. Odoo's install output goes to
local/logs/db-create.log, because it is thousands of lines long.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from shoptools import stack
from shoptools.envfile import parse_env, set_env_value
from shoptools.odoo_scripts.configure_shop import RESULT_PREFIX

ODOO_CONFIG = "/etc/odoo/odoo.conf"  # written from the environment by docker/odoo/entrypoint.sh
LANGUAGE = "en_US"
# eCommerce, stock availability on the shop, purchase with stock (restock proposals), test payment provider.
APPS = ("website_sale", "website_sale_stock", "purchase_stock", "payment_demo")
COMPANY_NAME = "Lost Demand Demo Shop"
WEBSITE_NAME = "Lost Demand Demo Shop"
CONFIGURE_SCRIPT = Path(__file__).parent / "odoo_scripts" / "configure_shop.py"
LOG_FILE = Path("local") / "logs" / "db-create.log"
JSON2_TIMEOUT_SECONDS = 15

API_KEY_ENV = "ODOO_API_KEY"  # pragma: allowlist secret
REQUIRED_ENV = ("ODOO_DB_NAME", "ODOO_ADMIN_LOGIN_PASSWORD", "ODOO_INTEGRATION_LOGIN")
# PostgreSQL identifier that needs no quoting; also keeps the name safe inside the SQL of `exists_command`.
_DB_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class SetupError(Exception):
    """A step failed; the message says what to do next."""


@dataclass(frozen=True)
class Settings:
    db_name: str
    admin_password: str
    integration_login: str


def read_settings(env_path: Path) -> Settings:
    if not env_path.is_file():
        raise SetupError(".env is missing. Create it with `uv run shop env init`.")
    values = parse_env(env_path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_ENV if not values.get(key)]
    if missing:
        raise SetupError(f".env lacks {', '.join(missing)}. Add them with `uv run shop env init`.")
    db_name = values["ODOO_DB_NAME"]
    if not _DB_NAME.match(db_name):
        raise SetupError(
            f"ODOO_DB_NAME {db_name!r} must be lowercase letters, digits and _, starting with a letter."
        )
    return Settings(db_name, values["ODOO_ADMIN_LOGIN_PASSWORD"], values["ODOO_INTEGRATION_LOGIN"])


# --- commands run in the containers ---


def _odoo(repo_root: Path, *args: str) -> list[str]:
    return stack.compose_command(repo_root, "exec", "-T", "odoo", "odoo", *args)


def exists_command(repo_root: Path, db_name: str) -> list[str]:
    sql = f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"
    return stack.compose_command(
        repo_root, "exec", "-T", "db", "psql", "-U", "odoo", "-d", "postgres", "-tAc", sql
    )


def init_command(repo_root: Path, db_name: str) -> list[str]:
    return _odoo(repo_root, "db", "-c", ODOO_CONFIG, "init", db_name, "--language", LANGUAGE)


def install_command(repo_root: Path, db_name: str) -> list[str]:
    return _odoo(repo_root, "module", "install", "-c", ODOO_CONFIG, "-d", db_name, *APPS)


def shell_command(repo_root: Path, db_name: str) -> list[str]:
    return _odoo(repo_root, "shell", "-c", ODOO_CONFIG, "-d", db_name, "--no-http")


def drop_command(repo_root: Path, db_name: str) -> list[str]:
    return _odoo(repo_root, "db", "-c", ODOO_CONFIG, "drop", db_name)


def configure_program(settings: Settings) -> str:
    """configure_shop.py followed by its call; repr() of a dict of strings is a valid Python literal."""
    values = {
        "admin_password": settings.admin_password,
        "integration_login": settings.integration_login,
        "company_name": COMPANY_NAME,
        "website_name": WEBSITE_NAME,
    }
    return CONFIGURE_SCRIPT.read_text(encoding="utf-8") + f"\nconfigure(env, {values!r})\n"


def parse_result(stdout: str) -> dict[str, object]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line.removeprefix(RESULT_PREFIX))
    raise SetupError("the configuration script printed no result: see the log")


def check_json2(db_name: str, api_key: str, base_url: str = stack.ODOO_URL) -> dict[str, object]:
    """One authenticated JSON-2 call; returns the integration user's context."""
    request = urllib.request.Request(
        f"{base_url}/json/2/res.users/context_get",
        data=b"{}",
        headers={
            "Authorization": f"bearer {api_key}",
            "Content-Type": "application/json",
            "X-Odoo-Database": db_name,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=JSON2_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SetupError(f"JSON-2 call refused: HTTP {error.code} {error.reason}") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise SetupError(f"JSON-2 call failed at {base_url}: {error}") from error


# --- running the steps ---


def _run(
    step: str, command: list[str], log: IO[str], stdin_text: str | None = None, capture: bool = False
) -> str:
    """Run one step; stderr (and stdout unless captured) goes to the log. Returns the captured stdout."""
    log.write(f"\n### {step}: {' '.join(command)}\n")
    log.flush()
    try:
        # Without input, stdin is closed: `docker compose exec` would otherwise read the terminal.
        stdin = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
        result = subprocess.run(
            command,
            **stdin,
            stdout=subprocess.PIPE if capture else log,
            stderr=log,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as error:
        raise SetupError("docker is not installed") from error
    if result.returncode != 0:
        raise SetupError(f"step '{step}' exited with code {result.returncode}")
    return result.stdout if capture else ""


def _require_running_stack(repo_root: Path) -> None:
    result = stack._run(stack.ps_command(repo_root), capture=True)
    if result is None or result.returncode != 0:
        raise SetupError("Docker is not reachable. Start Docker Desktop, then `uv run shop up`.")
    states = {state.service: state for state in stack.parse_ps(result.stdout)}
    for service in ("db", "odoo"):
        state = states.get(service)
        if state is None or state.state != "running" or state.health not in ("healthy", ""):
            raise SetupError(
                f"service {service} is not running and healthy. Start the stack with `uv run shop up`."
            )


def database_exists(repo_root: Path, db_name: str) -> bool:
    result = stack._run(exists_command(repo_root, db_name), capture=True)
    if result is None or result.returncode != 0:
        raise SetupError("cannot query PostgreSQL in the `db` service. See `uv run shop logs db`.")
    return result.stdout.strip() == "1"


def create_database(repo_root: Path, settings: Settings, log: IO[str], started: float) -> dict[str, object]:
    def step(number: int, title: str) -> None:
        print(f"[{number}/4] {title} ... ({time.monotonic() - started:.0f} s)", flush=True)

    db = settings.db_name
    step(1, f"Creating database {db!r} ({LANGUAGE}, no demo data)")
    _run("db init", init_command(repo_root, db), log)
    step(2, f"Installing {', '.join(APPS)} (a few minutes)")
    _run("module install", install_command(repo_root, db), log)
    step(3, "Configuring company, website, admin password, integration user and API key")
    stdout = _run("configure", shell_command(repo_root, db), log, configure_program(settings), capture=True)
    result = parse_result(stdout)
    api_key = str(result.pop("api_key"))
    set_env_value(repo_root / ".env", API_KEY_ENV, api_key)
    step(4, "Checking the API key with one JSON-2 call")
    result["json2_lang"] = check_json2(db, api_key).get("lang")
    return result


def _report(settings: Settings, result: dict[str, object], seconds: float) -> None:
    modules = result.get("modules")
    print(f"Database {settings.db_name!r} ready in {seconds:.0f} s.")
    company = f"{result.get('company')} ({result.get('currency')}, chart {result.get('chart_template')})"
    print(f"  company   {company}")
    print(f"  website   {result.get('website')} (guest checkout on)")
    print(f"  payment   {result.get('payment_provider')}")
    print(f"  language  {result.get('lang')}")
    print(f"  modules   {len(modules) if isinstance(modules, list) else '?'} installed")
    print(f"  API key   written to .env ({API_KEY_ENV}); JSON-2 check OK (lang {result.get('json2_lang')})")
    print(f"Shop {stack.ODOO_URL}/shop  Backend {stack.ODOO_URL}/odoo")
    print("Login: admin, password ODOO_ADMIN_LOGIN_PASSWORD in .env (values are not shown).")


def _prepare(repo_root: Path, command: str) -> tuple[Settings, bool] | None:
    try:
        settings = read_settings(repo_root / ".env")
        _require_running_stack(repo_root)
        return settings, database_exists(repo_root, settings.db_name)
    except SetupError as error:
        print(f"shop db {command}: {error}", file=sys.stderr)
        return None


def _open_log(repo_root: Path) -> IO[str]:
    log_path = repo_root / LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Odoo output: {log_path}")
    return log_path.open("w", encoding="utf-8")


def _create_and_report(
    repo_root: Path, settings: Settings, log: IO[str], started: float, command: str
) -> int:
    try:
        result = create_database(repo_root, settings, log, started)
    except SetupError as error:
        print(f"shop db {command}: {error}", file=sys.stderr)
        print(
            f"The database may be incomplete. Read {repo_root / LOG_FILE}, then recreate it with "
            "`uv run shop db reset`.",
            file=sys.stderr,
        )
        return 1
    _report(settings, result, time.monotonic() - started)
    return 0


def run_create(repo_root: Path) -> int:
    started = time.monotonic()
    prepared = _prepare(repo_root, "create")
    if prepared is None:
        return 1
    settings, exists = prepared
    if exists:
        print(
            f"shop db create: database {settings.db_name!r} already exists. "
            "Recreate it with `uv run shop db reset`.",
            file=sys.stderr,
        )
        return 1
    with _open_log(repo_root) as log:
        return _create_and_report(repo_root, settings, log, started, "create")


def run_reset(repo_root: Path, ask: Callable[[str], str] = input) -> int:
    """Destructive: drop the database and its filestore, then create it again. Asks first."""
    started = time.monotonic()
    prepared = _prepare(repo_root, "reset")
    if prepared is None:
        return 1
    settings, exists = prepared
    if exists:
        print(f"This deletes the database {settings.db_name!r} and its filestore. It cannot be undone.")
        try:
            answer = ask(f"Type the database name ({settings.db_name}) to confirm: ")
        except EOFError:  # no terminal to answer from: never treat silence as a yes
            answer = ""
        if answer.strip() != settings.db_name:
            print("Cancelled: nothing changed.")
            return 1
    with _open_log(repo_root) as log:
        if exists:
            try:
                _run("db drop", drop_command(repo_root, settings.db_name), log)
            except SetupError as error:
                print(f"shop db reset: {error}. Read {repo_root / LOG_FILE}.", file=sys.stderr)
                return 1
            set_env_value(repo_root / ".env", API_KEY_ENV, "")  # the old key died with the database
            print(f"Dropped {settings.db_name!r}.")
        return _create_and_report(repo_root, settings, log, started, "reset")
