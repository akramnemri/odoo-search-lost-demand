from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from shoptools import odoodb, stack
from shoptools.cli import main
from shoptools.envfile import parse_env, set_env_value
from shoptools.odoo_scripts.configure_shop import RESULT_PREFIX
from shoptools.odoodb import (
    Settings,
    SetupError,
    check_json2,
    configure_program,
    exists_command,
    init_command,
    install_command,
    parse_result,
    read_settings,
)

ROOT = Path("C:/work/odoo-search-lost-demand")
SECRET = "s3cr3t-value"  # pragma: allowlist secret
SETTINGS = Settings("shop", SECRET, "shop_integration")


def write_env(path: Path, **values: str) -> Path:
    defaults = {
        "ODOO_DB_NAME": "shop",
        "ODOO_ADMIN_LOGIN_PASSWORD": SECRET,
        "ODOO_INTEGRATION_LOGIN": "shop_integration",
    }
    env = path / ".env"
    env.write_text(
        "".join(f"{key}={value}\n" for key, value in {**defaults, **values}.items()), encoding="utf-8"
    )
    return env


# --- settings ---


def test_read_settings(tmp_path: Path) -> None:
    assert read_settings(write_env(tmp_path)) == SETTINGS


def test_read_settings_names_missing_keys(tmp_path: Path) -> None:
    with pytest.raises(SetupError, match="ODOO_ADMIN_LOGIN_PASSWORD.*shop env init"):
        read_settings(write_env(tmp_path, ODOO_ADMIN_LOGIN_PASSWORD=""))


@pytest.mark.parametrize("name", ["Shop", "shop;drop", "1shop", "shop-db", "a" * 64])
def test_read_settings_rejects_unsafe_database_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(SetupError, match="ODOO_DB_NAME"):
        read_settings(write_env(tmp_path, ODOO_DB_NAME=name))


# --- commands ---


def test_odoo_steps_run_in_the_odoo_container_with_its_config() -> None:
    init = init_command(ROOT, "shop")
    install = install_command(ROOT, "shop")

    assert init[init.index("exec") :] == [
        "exec",
        "-T",
        "odoo",
        "odoo",
        "db",
        "-c",
        "/etc/odoo/odoo.conf",
        "init",
        "shop",
        "--language",
        "en_US",
    ]
    assert "--with-demo" not in init  # demo data is opt-in in 19.0
    assert install[install.index("install") :] == [
        "install",
        "-c",
        "/etc/odoo/odoo.conf",
        "-d",
        "shop",
        "website_sale",
        "website_sale_stock",
        "purchase_stock",
        "payment_demo",
    ]


def test_no_secret_ever_reaches_a_command_line() -> None:
    commands = [
        init_command(ROOT, "shop"),
        install_command(ROOT, "shop"),
        odoodb.shell_command(ROOT, "shop"),
        odoodb.drop_command(ROOT, "shop"),
        exists_command(ROOT, "shop"),
    ]
    assert not any(SECRET in part for command in commands for part in command)


def test_configure_program_is_valid_python_with_the_settings_on_its_last_line() -> None:
    program = configure_program(SETTINGS)

    compile(program, "configure_shop.py", "exec")
    last_line = program.strip().splitlines()[-1]
    assert last_line.startswith("configure(env, {") and SECRET in last_line


def test_parse_result_takes_the_marked_line_among_odoo_output() -> None:
    stdout = f"some banner\n{RESULT_PREFIX}{json.dumps({'api_key': 'k', 'company': 'C'})}\n"

    assert parse_result(stdout) == {"api_key": "k", "company": "C"}
    with pytest.raises(SetupError):
        parse_result("Traceback ...\n")


# --- .env update ---


def test_set_env_value_replaces_one_key_and_keeps_the_rest(tmp_path: Path) -> None:
    env = write_env(tmp_path, ODOO_API_KEY="")
    text_before = env.read_text(encoding="utf-8")

    set_env_value(env, "ODOO_API_KEY", "new-key")

    values = parse_env(env.read_text(encoding="utf-8"))
    assert values["ODOO_API_KEY"] == "new-key"  # pragma: allowlist secret
    assert values["ODOO_ADMIN_LOGIN_PASSWORD"] == SECRET
    assert len(env.read_text(encoding="utf-8").splitlines()) == len(text_before.splitlines())
    assert b"\r\n" not in env.read_bytes()
    assert not (tmp_path / ".env.tmp").exists()


def test_set_env_value_appends_a_missing_key(tmp_path: Path) -> None:
    env = write_env(tmp_path)

    set_env_value(env, "ODOO_API_KEY", "k")

    assert parse_env(env.read_text(encoding="utf-8"))["ODOO_API_KEY"] == "k"


# --- JSON-2 check against a local fake Odoo ---


@pytest.fixture
def fake_odoo() -> Iterator[tuple[str, list[dict[str, str]]]]:
    seen: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append({"path": self.path, **{key.lower(): value for key, value in self.headers.items()}})
            authorized = self.headers.get("Authorization") == "bearer good-key"
            body = json.dumps({"lang": "en_US"} if authorized else {"error": "Invalid apikey"}).encode()
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_json2_check_sends_the_bearer_key_and_database(fake_odoo: tuple[str, list[dict[str, str]]]) -> None:
    url, seen = fake_odoo

    assert check_json2("shop", "good-key", base_url=url) == {"lang": "en_US"}
    assert seen[0]["path"] == "/json/2/res.users/context_get"
    assert seen[0]["x-odoo-database"] == "shop"


def test_json2_refusal_does_not_leak_the_key(fake_odoo: tuple[str, list[dict[str, str]]]) -> None:
    url, _ = fake_odoo

    with pytest.raises(SetupError, match="HTTP 401") as error:
        check_json2("shop", "bad-key", base_url=url)
    assert "bad-key" not in str(error.value)


# --- shop db create / reset (no call reaches Docker) ---


def ps_stdout(odoo_health: str = "healthy") -> str:
    rows = [
        {"Service": "db", "State": "running", "Health": "healthy", "ExitCode": 0},
        {"Service": "odoo", "State": "running", "Health": odoo_health, "ExitCode": 0},
    ]
    return "\n".join(json.dumps(row) for row in rows)


@pytest.fixture
def fake_stack(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stack healthy; `exists` decides whether the database exists. Records every step that would run."""
    state: dict[str, object] = {"exists": False, "steps": [], "odoo_health": "healthy"}

    def fake_stack_run(command: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
        stdout = (
            ps_stdout(str(state["odoo_health"])) if "ps" in command else ("1\n" if state["exists"] else "")
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def fake_create(repo_root: Path, settings: Settings, log: object, started: float) -> dict[str, object]:
        state["steps"].append("create")  # type: ignore[union-attr]
        return {"company": odoodb.COMPANY_NAME, "modules": ["website_sale"]}

    def fake_step(step: str, command: list[str], log: object, *args: object, **kwargs: object) -> str:
        state["steps"].append(step)  # type: ignore[union-attr]
        return ""

    monkeypatch.setattr(stack, "_run", fake_stack_run)
    monkeypatch.setattr(odoodb, "create_database", fake_create)
    monkeypatch.setattr(odoodb, "_run", fake_step)
    return state


def test_create_refuses_an_existing_database(
    tmp_path: Path, fake_stack: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    write_env(tmp_path)
    fake_stack["exists"] = True

    assert odoodb.run_create(tmp_path) == 1
    assert "shop db reset" in capsys.readouterr().err
    assert fake_stack["steps"] == []


def test_create_needs_a_healthy_stack(
    tmp_path: Path, fake_stack: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    write_env(tmp_path)
    fake_stack["odoo_health"] = "starting"

    assert odoodb.run_create(tmp_path) == 1
    assert "uv run shop up" in capsys.readouterr().err


def test_create_on_a_fresh_stack_never_prints_secrets(
    tmp_path: Path, fake_stack: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    write_env(tmp_path)

    assert odoodb.run_create(tmp_path) == 0
    assert fake_stack["steps"] == ["create"]
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err


def test_reset_drops_only_after_the_name_is_typed(tmp_path: Path, fake_stack: dict[str, object]) -> None:
    write_env(tmp_path, ODOO_API_KEY="old-key")  # pragma: allowlist secret
    fake_stack["exists"] = True

    assert odoodb.run_reset(tmp_path, ask=lambda prompt: "yes") == 1
    assert fake_stack["steps"] == []

    assert odoodb.run_reset(tmp_path, ask=lambda prompt: "shop") == 0
    assert fake_stack["steps"] == ["db drop", "create"]
    assert parse_env((tmp_path / ".env").read_text(encoding="utf-8"))["ODOO_API_KEY"] == ""


def test_reset_without_a_database_creates_it_without_asking(
    tmp_path: Path, fake_stack: dict[str, object]
) -> None:
    write_env(tmp_path)

    def never_asked(prompt: str) -> str:
        raise AssertionError("must not ask when there is nothing to delete")

    assert odoodb.run_reset(tmp_path, ask=never_asked) == 0
    assert fake_stack["steps"] == ["create"]


def test_db_requires_an_action() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["db"])

    assert exit_info.value.code == 2


def test_reset_without_an_answer_cancels(tmp_path: Path, fake_stack: dict[str, object]) -> None:
    write_env(tmp_path)
    fake_stack["exists"] = True

    def end_of_input(prompt: str) -> str:
        raise EOFError

    assert odoodb.run_reset(tmp_path, ask=end_of_input) == 1
    assert fake_stack["steps"] == []
