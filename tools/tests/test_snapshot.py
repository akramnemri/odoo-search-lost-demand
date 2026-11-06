from __future__ import annotations

from pathlib import Path

import pytest

from shoptools import odoodb, snapshot
from shoptools.cli import main
from shoptools.snapshot import (
    DB_FILE,
    FILESTORE_FILE,
    Metadata,
    SnapshotError,
    compare_counts,
    create_restore_db_command,
    dump_command,
    filestore_stage_command,
    filestore_swap_command,
    metadata_text,
    parse_counts,
    pg_restore_command,
    read_metadata,
    swap_db_command,
    validate_name,
    verify_files,
)

ROOT = Path("C:/work/odoo-search-lost-demand")
COUNTS = {"modules": 86, "products": 1, "partners": 5, "sale_orders": 2}


def _after(command: list[str], marker: str) -> list[str]:
    return command[command.index(marker) :]


# --- names ---


@pytest.mark.parametrize("name", ["baseline", "baseline-catalog", "m2.import_1", "0"])
def test_valid_names(name: str) -> None:
    assert validate_name(name) == name


@pytest.mark.parametrize("name", ["", "../escape", "a/b", "Baseline", ".hidden", "-x", "a" * 65, "x y"])
def test_names_that_could_escape_or_hide_are_refused(name: str) -> None:
    with pytest.raises(SnapshotError):
        validate_name(name)


# --- commands ---


def test_dump_uses_the_postgres_16_client_of_the_db_container() -> None:
    assert _after(dump_command(ROOT, "shop"), "exec") == [
        "exec",
        "-T",
        "db",
        "pg_dump",
        "-U",
        "odoo",
        "--format=custom",
        "--no-owner",
        "shop",
    ]


def test_restore_goes_to_a_temporary_database_and_stops_at_the_first_error() -> None:
    command = pg_restore_command(ROOT, "shop")

    assert "--exit-on-error" in command
    assert command[-3:] == ["-d", "shop_restore", "/root/snapshot-restore.dump"]


def test_restore_database_is_created_like_odoo_creates_databases() -> None:
    command = create_restore_db_command(ROOT, "shop")
    statements = [command[index + 1] for index, part in enumerate(command) if part == "-c"]

    # Separate -c: CREATE DATABASE cannot run inside one transaction with the DROP.
    assert statements == [
        'DROP DATABASE IF EXISTS "shop_restore"',
        "CREATE DATABASE \"shop_restore\" ENCODING 'unicode' LC_COLLATE 'C' TEMPLATE template0",
    ]
    assert "ON_ERROR_STOP=1" in command


def test_swap_replaces_the_database_only_with_the_restored_one() -> None:
    command = swap_db_command(ROOT, "shop")
    statements = [command[index + 1] for index, part in enumerate(command) if part == "-c"]

    assert statements == [
        'DROP DATABASE IF EXISTS "shop" WITH (FORCE)',
        'ALTER DATABASE "shop_restore" RENAME TO "shop"',
    ]


def test_filestore_is_staged_then_swapped_in_a_one_off_container() -> None:
    stage = filestore_stage_command(ROOT, "shop")
    swap = filestore_swap_command(ROOT, "shop")

    for command in (stage, swap):
        assert _after(command, "run")[:7] == ["run", "--rm", "--no-deps", "-T", "--entrypoint", "sh", "odoo"]
        assert command[-1].startswith("set -e;")
    assert "/var/lib/odoo/filestore/.restore-shop" in stage[-1]
    assert "mv /var/lib/odoo/filestore/.restore-shop/shop /var/lib/odoo/filestore/shop" in swap[-1]


# --- counts and metadata ---


def test_parse_and_compare_counts() -> None:
    assert parse_counts("86,1,5,2\n") == COUNTS
    with pytest.raises(SnapshotError):
        parse_counts("86,1\n")
    assert compare_counts(COUNTS, COUNTS) == []
    assert compare_counts(COUNTS, {**COUNTS, "products": 3}) == ["products: 3 (snapshot: 1)"]


def write_snapshot(folder: Path, name: str = "baseline") -> Metadata:
    folder.mkdir(parents=True)
    (folder / DB_FILE).write_bytes(b"dump")
    (folder / FILESTORE_FILE).write_bytes(b"tar")
    metadata = Metadata(
        name=name,
        created_at="2026-11-06T18:00:00Z",
        git_sha="abc123",
        odoo_image="odoo-search-lost-demand/odoo:19.0-20261015",
        db_name="shop",
        files={
            file_name: {
                "bytes": (folder / file_name).stat().st_size,
                "sha256": snapshot.sha256_file(folder / file_name),
            }
            for file_name in (DB_FILE, FILESTORE_FILE)
        },
        counts=COUNTS,
    )
    (folder / snapshot.METADATA_FILE).write_text(metadata_text(metadata), encoding="utf-8")
    return metadata


def test_metadata_round_trip(tmp_path: Path) -> None:
    metadata = write_snapshot(tmp_path / "baseline")

    assert read_metadata(tmp_path / "baseline") == metadata


def test_a_damaged_file_is_detected(tmp_path: Path) -> None:
    metadata = write_snapshot(tmp_path / "baseline")
    verify_files(tmp_path / "baseline", metadata)

    (tmp_path / "baseline" / DB_FILE).write_bytes(b"dumq")
    with pytest.raises(SnapshotError, match="checksum"):
        verify_files(tmp_path / "baseline", metadata)


# --- save / restore / list (no call reaches Docker) ---


@pytest.fixture
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Healthy stack with a `shop` database; `fail_at` makes one step fail. Records the steps in order."""
    # Built from a dict, so detect-secrets does not read the fake values as secrets.
    env = {
        "ODOO_DB_NAME": "shop",
        "ODOO_ADMIN_LOGIN_PASSWORD": "x",
        "ODOO_INTEGRATION_LOGIN": "i",
        "ODOO_API_KEY": "k",
    }
    (tmp_path / ".env").write_text(
        "".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8"
    )
    (tmp_path / "compose.yaml").write_text(
        "services:\n  odoo:\n    image: odoo-search-lost-demand/odoo:19.0-20261015\n", encoding="utf-8"
    )
    state: dict[str, object] = {"steps": [], "fail_at": None, "counts": "86,1,5,2"}

    def fake_run(
        step: str, command: list[str], stdin_path: Path | None = None, stdout_path: Path | None = None
    ) -> str:
        state["steps"].append(step)  # type: ignore[union-attr]
        if step == state["fail_at"]:
            raise SnapshotError(f"step '{step}' exited with code 1")
        if stdout_path is not None:
            stdout_path.write_bytes(f"{step} output".encode())
        return {"row counts": str(state["counts"]), "database size": "1000"}.get(step, "")

    monkeypatch.setattr(snapshot, "_run", fake_run)
    monkeypatch.setattr(odoodb, "require_running_stack", lambda repo_root: None)
    monkeypatch.setattr(odoodb, "database_exists", lambda repo_root, db_name: True)
    monkeypatch.setattr(odoodb, "check_json2", lambda db_name, api_key: {"lang": "en_US"})
    return state


def test_save_writes_a_complete_snapshot(tmp_path: Path, fake_docker: dict[str, object]) -> None:
    assert snapshot.run_save(tmp_path, "baseline") == 0

    folder = tmp_path / "local" / "snapshots" / "baseline"
    metadata = read_metadata(folder)
    verify_files(folder, metadata)
    assert metadata.counts == COUNTS
    assert metadata.odoo_image == "odoo-search-lost-demand/odoo:19.0-20261015"
    assert fake_docker["steps"][-2:] == ["pg_dump", "filestore"]  # database first, then files
    assert not list((tmp_path / "local" / "snapshots").glob(".*"))


def test_save_refuses_to_overwrite_without_force(
    tmp_path: Path, fake_docker: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    assert snapshot.run_save(tmp_path, "baseline") == 0
    assert snapshot.run_save(tmp_path, "baseline") == 1
    assert "--force" in capsys.readouterr().err
    assert snapshot.run_save(tmp_path, "baseline", force=True) == 0


def test_a_failed_save_leaves_no_snapshot(tmp_path: Path, fake_docker: dict[str, object]) -> None:
    fake_docker["fail_at"] = "filestore"

    assert snapshot.run_save(tmp_path, "baseline") == 1
    assert list((tmp_path / "local" / "snapshots").iterdir()) == []


def saved(tmp_path: Path) -> None:
    write_snapshot(tmp_path / "local" / "snapshots" / "baseline")


@pytest.mark.parametrize("answer", ["yes", "", EOFError])
def test_restore_does_nothing_without_the_typed_name(
    tmp_path: Path, fake_docker: dict[str, object], answer: object
) -> None:
    saved(tmp_path)

    def ask(prompt: str) -> str:
        if answer is EOFError:
            raise EOFError
        return str(answer)

    assert snapshot.run_restore(tmp_path, "baseline", ask=ask) == 1
    assert fake_docker["steps"] == []


def test_restore_refuses_a_damaged_snapshot_before_asking(
    tmp_path: Path, fake_docker: dict[str, object]
) -> None:
    saved(tmp_path)
    (tmp_path / "local" / "snapshots" / "baseline" / FILESTORE_FILE).write_bytes(b"tampered")

    def never_asked(prompt: str) -> str:
        raise AssertionError("must not ask")

    assert snapshot.run_restore(tmp_path, "baseline", ask=never_asked) == 1
    assert fake_docker["steps"] == []


def test_restore_replaces_only_after_both_parts_are_ready(
    tmp_path: Path, fake_docker: dict[str, object]
) -> None:
    saved(tmp_path)

    assert snapshot.run_restore(tmp_path, "baseline", ask=lambda prompt: "shop") == 0
    assert fake_docker["steps"] == [
        "stop odoo",
        "create restore database",
        "upload dump",
        "pg_restore",
        "remove uploaded dump",
        "stage filestore",
        "swap database",
        "swap filestore",
        "start odoo",
        "row counts",
    ]


def test_a_failed_restore_keeps_the_shop_and_restarts_odoo(
    tmp_path: Path, fake_docker: dict[str, object]
) -> None:
    saved(tmp_path)
    fake_docker["fail_at"] = "pg_restore"

    assert snapshot.run_restore(tmp_path, "baseline", ask=lambda prompt: "shop") == 1
    steps = fake_docker["steps"]
    assert "swap database" not in steps  # type: ignore[operator]
    assert steps[-4:] == [  # type: ignore[index]
        "drop restore database",
        "remove uploaded dump",
        "clean filestore staging",
        "start odoo",
    ]


def test_restore_reports_count_differences(
    tmp_path: Path, fake_docker: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    saved(tmp_path)
    fake_docker["counts"] = "86,2,5,2"

    assert snapshot.run_restore(tmp_path, "baseline", ask=lambda prompt: "shop") == 1
    assert "products: 2 (snapshot: 1)" in capsys.readouterr().err


def test_list_shows_saved_snapshots(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot.run_list(tmp_path)
    assert "No snapshots" in capsys.readouterr().out

    saved(tmp_path)
    snapshot.run_list(tmp_path)
    assert "baseline" in capsys.readouterr().out


def test_snapshot_requires_an_action() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["snapshot"])

    assert exit_info.value.code == 2
