"""`shop index rebuild [--check]` (Task 3.1): the odoo shell program, its result and the messages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import REPO_ROOT

from shoptools import index_rebuild, odoodb
from shoptools.cli import build_parser
from shoptools.doctor.expected import VERSIONS_FILE
from shoptools.doctor.model import CheckResult, Status

ENV = (
    # Fake values for the tests, not real credentials.
    "ODOO_DB_NAME=shop\nODOO_ADMIN_LOGIN_PASSWORD=fake-admin\n"  # pragma: allowlist secret
    "ODOO_INTEGRATION_LOGIN=shop-integration\n"
)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".env").write_text(ENV, encoding="utf-8")
    versions = tmp_path / VERSIONS_FILE
    versions.parent.mkdir(parents=True)
    versions.write_text((REPO_ROOT / VERSIONS_FILE).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(odoodb, "require_running_stack", lambda root: None)
    return tmp_path


def _shell_answers(monkeypatch: pytest.MonkeyPatch, outcome: dict[str, object]) -> list[str]:
    programs: list[str] = []

    def fake_run(step: str, command: list[str], log: object, stdin_text: str, capture: bool) -> str:
        assert command[-6:] == ["shell", "-c", "/etc/odoo/odoo.conf", "-d", "shop", "--no-http"]
        programs.append(stdin_text)
        return "odoo noise\n" + index_rebuild.RESULT_PREFIX + json.dumps(outcome) + "\n"

    monkeypatch.setattr(odoodb, "_run", fake_run)
    return programs


def _check(monkeypatch: pytest.MonkeyPatch, status: Status) -> None:
    result = CheckResult(
        "odoo",
        "product index count",
        status,
        "19,869 documents for 19,869 products",
        "one document per product",
        "uv run shop index rebuild",
    )
    monkeypatch.setattr(index_rebuild, "index_count_check", lambda context, db_name: result)


def test_the_program_is_valid_python() -> None:
    compile(index_rebuild.PROGRAM, "rebuild_program", "exec")
    assert "_rebuild()" in index_rebuild.PROGRAM


def test_parse_result_takes_the_last_result_line() -> None:
    stdout = 'INFO start\nSHOP_INDEX {"index": "a"}\nINFO more\nSHOP_INDEX {"index": "b"}\n'
    assert index_rebuild.parse_result(stdout) == {"index": "b"}
    with pytest.raises(odoodb.SetupError, match="printed no result"):
        index_rebuild.parse_result("Traceback ...\n")


def test_rebuild_then_check(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    programs = _shell_answers(
        monkeypatch,
        {
            "summary": "19,869 products indexed into shop-products-v1 in 95 s; "
            "alias shop-products moved from nothing.",
            "synonyms_created": True,
        },
    )
    _check(monkeypatch, Status.OK)
    out: list[str] = []

    assert index_rebuild.run_rebuild(repo, write=out.append) == 0

    text = "".join(out)
    assert "19,869 products indexed into shop-products-v1" in text
    assert "Created the empty synonyms set shop-synonyms" in text
    assert "OK    product index count: 19,869 documents for 19,869 products" in text
    assert programs == [index_rebuild.PROGRAM]
    assert (repo / index_rebuild.LOG_FILE).is_file()


def test_rebuild_error_is_reported(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _shell_answers(
        monkeypatch, {"error": "Elasticsearch refused 1 products. The alias shop-products was not moved."}
    )
    out: list[str] = []

    assert index_rebuild.run_rebuild(repo, write=out.append) == 1
    assert (
        out[-1]
        == "shop index rebuild: Elasticsearch refused 1 products. The alias shop-products was not moved.\n"
    )


def test_check_only_changes_nothing(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odoodb, "_run", lambda *args, **kwargs: pytest.fail("no odoo shell for --check"))
    _check(monkeypatch, Status.WARN)
    out: list[str] = []

    assert index_rebuild.run_rebuild(repo, check_only=True, write=out.append) == 1
    assert out[-1] == "      fix: uv run shop index rebuild\n"


def test_cli_arguments() -> None:
    namespace = build_parser().parse_args(["index", "rebuild", "--check"])
    assert (namespace.command, namespace.index_action, namespace.check) == ("index", "rebuild", True)
