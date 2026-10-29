from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from shoptools.cli import main
from shoptools.envfile import GENERATED, PROFILES, generate_secret, init_env, parse_env

REPO_ROOT = Path(__file__).resolve().parents[2]

EXAMPLE = """# comment kept
RAM_PROFILE=standard
ES_HEAP=2g

DB_NAME=shop
FIRST_GENERATED=<generated>
SECOND_GENERATED=<generated>
"""


def _counter_secrets() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"random-{next(counter)}"


def _write_env(path: Path, **values: str) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


@pytest.fixture
def example(tmp_path: Path) -> Path:
    path = tmp_path / ".env.example"
    path.write_text(EXAMPLE, encoding="utf-8")
    return path


def test_new_env_copies_the_example_and_generates_every_secret(example: Path, tmp_path: Path) -> None:
    env = tmp_path / ".env"

    result = init_env(example, env, make_secret=_counter_secrets())

    assert result.created
    assert result.generated == ["FIRST_GENERATED", "SECOND_GENERATED"]
    assert parse_env(env.read_text(encoding="utf-8")) == {
        "RAM_PROFILE": "standard",
        "ES_HEAP": "2g",
        "DB_NAME": "shop",
        "FIRST_GENERATED": "random-1",
        "SECOND_GENERATED": "random-2",
    }
    assert env.read_text(encoding="utf-8").startswith("# comment kept\n")


def test_env_is_written_with_lf_line_endings(example: Path, tmp_path: Path) -> None:
    env = tmp_path / ".env"

    init_env(example, env)

    assert b"\r\n" not in env.read_bytes()


def test_rerun_keeps_existing_values_and_only_adds_missing_keys(example: Path, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    _write_env(env, DB_NAME="custom", FIRST_GENERATED="kept-value", ES_HEAP="4g")

    result = init_env(example, env, make_secret=_counter_secrets())

    values = parse_env(env.read_text(encoding="utf-8"))
    assert values["DB_NAME"] == "custom"
    assert values["FIRST_GENERATED"] == "kept-value"
    assert values["ES_HEAP"] == "4g"
    assert values["SECOND_GENERATED"] == "random-1"
    assert not result.created
    assert result.added == ["RAM_PROFILE", "SECOND_GENERATED"]
    assert result.generated == ["SECOND_GENERATED"]


def test_placeholder_left_in_env_is_replaced_by_a_secret(example: Path, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    _write_env(env, FIRST_GENERATED=GENERATED)

    result = init_env(example, env, make_secret=_counter_secrets())

    assert parse_env(env.read_text(encoding="utf-8"))["FIRST_GENERATED"] == "random-1"
    assert "FIRST_GENERATED" in result.generated
    assert "FIRST_GENERATED" not in result.added


def test_profile_overrides_memory_settings_even_when_env_exists(example: Path, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    _write_env(env, RAM_PROFILE="standard", ES_HEAP="2g", FIRST_GENERATED="kept-value")

    init_env(example, env, profile="lowmem")

    values = parse_env(env.read_text(encoding="utf-8"))
    assert values["RAM_PROFILE"] == "lowmem"
    assert values["ES_HEAP"] == PROFILES["lowmem"]["ES_HEAP"]
    assert values["FIRST_GENERATED"] == "kept-value"


def test_keys_added_by_hand_are_preserved(example: Path, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    _write_env(env, MY_DEBUG="1")

    init_env(example, env)

    assert parse_env(env.read_text(encoding="utf-8"))["MY_DEBUG"] == "1"


def test_generated_secrets_are_long_unique_and_safe_without_quoting() -> None:
    secrets = {generate_secret() for _ in range(50)}

    assert len(secrets) == 50
    for secret in secrets:
        assert len(secret) >= 32
        assert secret.replace("-", "").replace("_", "").isalnum()


def test_real_example_matches_the_standard_profile_and_has_only_safe_values() -> None:
    values = parse_env((REPO_ROOT / ".env.example").read_text(encoding="utf-8"))

    for key, value in PROFILES["standard"].items():
        assert values[key] == value
    assert set(PROFILES["lowmem"]) == set(PROFILES["standard"])
    for key, value in values.items():
        if any(word in key for word in ("PASSWORD", "PASSWD", "_KEY")):
            # Empty = filled later by a tool (ODOO_API_KEY by `shop db create`).
            assert value in (GENERATED, ""), (
                f"{key} must be generated or empty, never written in .env.example"
            )


def test_cli_env_init_never_prints_secret_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("pyproject.toml", ".env.example", "docs/setup/versions.toml"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["env", "init"]) == 0

    output = capsys.readouterr().out
    values = parse_env((tmp_path / ".env").read_text(encoding="utf-8"))
    assert "ELASTIC_PASSWORD" in output
    assert values["ELASTIC_PASSWORD"] not in output
    for key, value in values.items():
        if value and ("PASSWORD" in key or key.endswith("_KEY")):
            assert value not in output


def test_cli_env_requires_an_action() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["env"])

    assert exit_info.value.code == 2
