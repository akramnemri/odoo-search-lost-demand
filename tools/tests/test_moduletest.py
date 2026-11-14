from __future__ import annotations

from pathlib import Path

import pytest

from shoptools import moduletest
from shoptools.cli import main


def test_unit_run_excludes_es_tests() -> None:
    assert moduletest.test_tags(with_es=False) == "/website_sale_lost_demand,-es"
    assert moduletest.test_tags(with_es=True) == "/website_sale_lost_demand"


def test_command_targets_only_the_test_database() -> None:
    command = moduletest.run_command(Path("/repo"), with_es=False)

    assert command[command.index("-d") + 1] == "shop_test"
    assert "--db-filter=^shop_test$" in command
    assert "--http-port=8079" in command
    assert "--stop-after-init" in command
    assert command[command.index("-i") + 1] == "website_sale_lost_demand"
    assert command[:2] == ["docker", "compose"]
    assert "-T" in command  # no terminal: stdin is closed as well


def test_summary_uses_the_last_line() -> None:
    log = (
        "INFO shop_test odoo.tests.result: 0 failed, 0 error(s) of 0 tests when loading database\n"
        "INFO shop_test odoo.tests.result: 1 failed, 2 error(s) of 14 tests when loading database\n"
    )

    assert moduletest.parse_summary(log) == (1, 2, 14)


def test_no_summary() -> None:
    assert moduletest.parse_summary("CRITICAL Failed to initialize database") is None


def test_failure_lines_are_limited() -> None:
    log = "\n".join(["2026 ERROR shop_test x: boom"] * 30 + ["INFO fine"])

    assert len(moduletest.failure_lines(log)) == 20


def test_refuses_when_the_shop_database_is_the_test_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values = {
        "ODOO_DB_NAME": "shop_test",
        "ODOO_ADMIN_LOGIN_PASSWORD": "fake",  # pragma: allowlist secret
        "ODOO_INTEGRATION_LOGIN": "integration",
    }
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")

    assert moduletest.run_module_tests(tmp_path, with_es=False) == 1
    assert "throwaway test database" in capsys.readouterr().err


def test_cli_passes_arguments_to_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(moduletest, "run_tool_tests", lambda root, args: seen.append(args) or 0)

    assert main(["test", "tools", "-k", "breaker"]) == 0
    assert seen == [["-k", "breaker"]]


def test_cli_module_options(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[bool, bool]] = []
    monkeypatch.setattr(
        moduletest, "run_module_tests", lambda root, with_es, keep_db: seen.append((with_es, keep_db)) or 0
    )

    assert main(["test", "module", "--es"]) == 0
    assert seen == [(True, False)]
