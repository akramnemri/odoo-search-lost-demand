"""`uv run shop snapshot save|restore|list`: snapshots of the shop database and its filestore (Task 1.2b).

A snapshot is a folder `local/snapshots/<name>/` (git-ignored) with:
- `db.dump`: `pg_dump --format=custom` run in the `db` container, so the client matches the
  PostgreSQL 16 server. Odoo's own `odoo db dump|load` is not used: the Odoo image ships pg_dump/psql 18,
  whose dumps contain `SET transaction_timeout`, and Odoo's restore runs psql without stopping on errors
  (.odoo-src/odoo/service/db.py::restore_db), so a broken restore would look successful;
- `filestore.tar`: the database's filestore (/var/lib/odoo/filestore/<db>, tools/config.py::filestore);
- `metadata.toml`: time, git SHA, Odoo image, checksums and row counts, checked again after a restore.

Save runs while Odoo is up: the database is dumped first, then the filestore is copied. Odoo writes a file
before it commits the attachment row (base/models/ir_attachment.py::_file_write), so every file the dump
refers to is in the copy. Restore stops Odoo for the whole operation: without `db_name` in odoo.conf,
scheduled jobs run on every database and would pick up the temporary one. It restores into `<db>_restore`
with `--exit-on-error` and replaces the current database and filestore only once both are ready, so a bad
snapshot leaves the shop unchanged.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shoptools import odoodb, stack
from shoptools.envfile import parse_env

SNAPSHOTS_DIR = Path("local") / "snapshots"
DB_FILE = "db.dump"
FILESTORE_FILE = "filestore.tar"
METADATA_FILE = "metadata.toml"
FILESTORE_PARENT = "/var/lib/odoo/filestore"
# Inside the db container, removed after use. /root is private to root (`docker compose exec` runs as root);
# /tmp and /var/lib/postgresql are writable by every user of the image.
RESTORE_DUMP_PATH = "/root/snapshot-restore.dump"
RESTORE_JOBS = 4
FREE_SPACE_FACTOR = 2  # the custom-format dump is compressed; this leaves a margin for the filestore
MB = 1024 * 1024

_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# Row counts recorded at save and compared after a restore.
COUNT_QUERIES = {
    "modules": "SELECT count(*) FROM ir_module_module WHERE state = 'installed'",
    "products": "SELECT count(*) FROM product_template",
    "partners": "SELECT count(*) FROM res_partner",
    "sale_orders": "SELECT count(*) FROM sale_order",
}


class SnapshotError(Exception):
    """A step failed; the message says what to do next."""


@dataclass(frozen=True)
class Metadata:
    name: str
    created_at: str
    git_sha: str
    odoo_image: str
    db_name: str
    files: dict[str, dict[str, str | int]]  # file name -> {"bytes": ..., "sha256": ...}
    counts: dict[str, int]


def validate_name(name: str) -> str:
    if not _NAME.match(name):
        raise SnapshotError(
            f"invalid snapshot name {name!r}: lowercase letters, digits, '.', '_' and '-', "
            "starting with a letter or digit"
        )
    return name


def restore_db_name(db_name: str) -> str:
    return f"{db_name}_restore"


# --- commands run in the containers ---


def _db(repo_root: Path, *args: str) -> list[str]:
    return stack.compose_command(repo_root, "exec", "-T", "db", *args)


def dump_command(repo_root: Path, db_name: str) -> list[str]:
    return _db(repo_root, "pg_dump", "-U", "odoo", "--format=custom", "--no-owner", db_name)


def counts_command(repo_root: Path, db_name: str) -> list[str]:
    select = "SELECT " + ", ".join(f"({query})" for query in COUNT_QUERIES.values())
    return _db(repo_root, "psql", "-U", "odoo", "-d", db_name, "-tA", "-F", ",", "-c", select)


def size_command(repo_root: Path, db_name: str) -> list[str]:
    return _db(
        repo_root, "psql", "-U", "odoo", "-d", "postgres", "-tAc", f"SELECT pg_database_size('{db_name}')"
    )


def psql_commands(repo_root: Path, *statements: str) -> list[str]:
    """Each `-c` runs on its own: CREATE and DROP DATABASE cannot run inside a transaction block."""
    args = [arg for statement in statements for arg in ("-c", statement)]
    return _db(repo_root, "psql", "-U", "odoo", "-d", "postgres", "-v", "ON_ERROR_STOP=1", *args)


def create_restore_db_command(repo_root: Path, db_name: str) -> list[str]:
    target = restore_db_name(db_name)
    # Same settings as Odoo 19.0 (service/db.py::_create_empty_database): UTF8, collation C, template0.
    return psql_commands(
        repo_root,
        f'DROP DATABASE IF EXISTS "{target}"',
        f"CREATE DATABASE \"{target}\" ENCODING 'unicode' LC_COLLATE 'C' TEMPLATE template0",
    )


def upload_dump_command(repo_root: Path) -> list[str]:
    # pg_restore needs a seekable file (not stdin) to restore in parallel.
    return _db(repo_root, "sh", "-c", f"cat > {RESTORE_DUMP_PATH}")


def pg_restore_command(repo_root: Path, db_name: str) -> list[str]:
    # Parallel jobs: 21 s instead of 39 s with one job for the 65 MB database of Task 1.2b (4-CPU Docker VM).
    # --exit-on-error: stop at the first error instead of restoring part of the data.
    return _db(
        repo_root,
        "pg_restore",
        "-U",
        "odoo",
        "--no-owner",
        "--exit-on-error",
        f"--jobs={RESTORE_JOBS}",
        "-d",
        restore_db_name(db_name),
        RESTORE_DUMP_PATH,
    )


def remove_uploaded_dump_command(repo_root: Path) -> list[str]:
    return _db(repo_root, "rm", "-f", RESTORE_DUMP_PATH)


def swap_db_command(repo_root: Path, db_name: str) -> list[str]:
    return psql_commands(
        repo_root,
        f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)',
        f'ALTER DATABASE "{restore_db_name(db_name)}" RENAME TO "{db_name}"',
    )


def drop_restore_db_command(repo_root: Path, db_name: str) -> list[str]:
    return psql_commands(repo_root, f'DROP DATABASE IF EXISTS "{restore_db_name(db_name)}" WITH (FORCE)')


def filestore_export_command(repo_root: Path, db_name: str) -> list[str]:
    return stack.compose_command(
        repo_root, "exec", "-T", "odoo", "tar", "-C", FILESTORE_PARENT, "-cf", "-", db_name
    )


def _filestore_shell(repo_root: Path, script: str) -> list[str]:
    # A one-off container on the odoo-data volume: works while the odoo service is stopped.
    return stack.compose_command(
        repo_root, "run", "--rm", "--no-deps", "-T", "--entrypoint", "sh", "odoo", "-c", f"set -e; {script}"
    )


def filestore_stage_command(repo_root: Path, db_name: str) -> list[str]:
    staging = f"{FILESTORE_PARENT}/.restore-{db_name}"
    return _filestore_shell(
        repo_root,
        f"rm -rf {staging}; mkdir -p {staging}; tar -C {staging} -xf -; test -d {staging}/{db_name}",
    )


def filestore_swap_command(repo_root: Path, db_name: str) -> list[str]:
    current, staging, old = (f"{FILESTORE_PARENT}/{prefix}{db_name}" for prefix in ("", ".restore-", ".old-"))
    return _filestore_shell(
        repo_root,
        f"rm -rf {old}; if [ -d {current} ]; then mv {current} {old}; fi; "
        f"mv {staging}/{db_name} {current}; rm -rf {staging} {old}",
    )


def filestore_cleanup_command(repo_root: Path, db_name: str) -> list[str]:
    return _filestore_shell(repo_root, f"rm -rf {FILESTORE_PARENT}/.restore-{db_name}")


# --- metadata ---


def parse_counts(stdout: str) -> dict[str, int]:
    values = stdout.strip().split(",")
    if len(values) != len(COUNT_QUERIES):
        raise SnapshotError(f"unexpected row counts: {stdout.strip()!r}")
    return dict(zip(COUNT_QUERIES, (int(value) for value in values), strict=True))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def metadata_text(metadata: Metadata) -> str:
    lines = [
        "# Written by `uv run shop snapshot save` (Task 1.2b). Checked by `uv run shop snapshot restore`.",
        f"name = {_toml_string(metadata.name)}",
        f"created_at = {_toml_string(metadata.created_at)}",
        f"git_sha = {_toml_string(metadata.git_sha)}",
        f"odoo_image = {_toml_string(metadata.odoo_image)}",
        f"db_name = {_toml_string(metadata.db_name)}",
        "",
        "[counts]",
        *(f"{key} = {value}" for key, value in metadata.counts.items()),
    ]
    for file_name, info in metadata.files.items():
        lines += ["", f"[files.{_toml_string(file_name)}]", f"bytes = {info['bytes']}"]
        lines.append(f"sha256 = {_toml_string(str(info['sha256']))}")
    return "\n".join(lines) + "\n"


def read_metadata(folder: Path) -> Metadata:
    try:
        data = tomllib.loads((folder / METADATA_FILE).read_text(encoding="utf-8"))
        return Metadata(
            name=data["name"],
            created_at=data["created_at"],
            git_sha=data["git_sha"],
            odoo_image=data["odoo_image"],
            db_name=data["db_name"],
            files=data["files"],
            counts=data["counts"],
        )
    except (OSError, tomllib.TOMLDecodeError, KeyError) as error:
        raise SnapshotError(f"{folder / METADATA_FILE} is missing or invalid: {error}") from error


def verify_files(folder: Path, metadata: Metadata) -> None:
    for file_name in (DB_FILE, FILESTORE_FILE):
        info = metadata.files.get(file_name)
        path = folder / file_name
        if info is None or not path.is_file():
            raise SnapshotError(f"{path} is missing")
        if sha256_file(path) != info["sha256"]:
            raise SnapshotError(f"{path} does not match its checksum: the snapshot is damaged")


def compare_counts(expected: dict[str, int], found: dict[str, int]) -> list[str]:
    return [
        f"{key}: {found.get(key)} (snapshot: {value})"
        for key, value in expected.items()
        if found.get(key) != value
    ]


# --- running the steps ---


def _run(
    step: str, command: list[str], stdin_path: Path | None = None, stdout_path: Path | None = None
) -> str:
    """Run one step, streaming files on stdin/stdout when given. Returns stdout text when not streamed."""
    with ExitStack() as files:
        # stdin is never the terminal: `docker compose exec` would read what the person types.
        stdin = files.enter_context(stdin_path.open("rb")) if stdin_path else subprocess.DEVNULL
        stdout = files.enter_context(stdout_path.open("wb")) if stdout_path else subprocess.PIPE
        try:
            result = subprocess.run(command, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, check=False)
        except FileNotFoundError as error:
            raise SnapshotError("docker is not installed") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise SnapshotError(f"step '{step}' exited with code {result.returncode}: {' | '.join(detail[-3:])}")
    return "" if stdout_path else result.stdout.decode("utf-8", errors="replace")


def _git_sha(repo_root: Path) -> str:
    git = ["git", "-C", str(repo_root)]
    try:
        sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout
        dirty = subprocess.run(
            [*git, "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha.strip()}-dirty" if dirty.strip() else sha.strip()


def _odoo_image(repo_root: Path) -> str:
    for line in (repo_root / stack.COMPOSE_FILE).read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition(":")
        if key == "image" and "/odoo:" in value:
            return value.strip()
    return "unknown"


def _prepare(repo_root: Path, command: str) -> odoodb.Settings | None:
    try:
        settings = odoodb.read_settings(repo_root / ".env")
        odoodb.require_running_stack(repo_root)
        return settings
    except odoodb.SetupError as error:
        print(f"shop snapshot {command}: {error}", file=sys.stderr)
        return None


def _fail(command: str, message: str) -> int:
    print(f"shop snapshot {command}: {message}", file=sys.stderr)
    return 1


def run_save(repo_root: Path, name: str, force: bool = False) -> int:
    started = time.monotonic()
    try:
        validate_name(name)
    except SnapshotError as error:
        return _fail("save", str(error))
    target = repo_root / SNAPSHOTS_DIR / name
    if target.exists() and not force:
        return _fail("save", f"snapshot {name!r} already exists. Replace it with `--force`.")
    settings = _prepare(repo_root, "save")
    if settings is None:
        return 1
    db = settings.db_name
    partial, old = target.with_name(f".partial-{name}"), target.with_name(f".old-{name}")
    try:
        if not odoodb.database_exists(repo_root, db):
            raise SnapshotError(f"database {db!r} does not exist. Create it with `uv run shop db create`.")
        db_bytes = int(_run("database size", size_command(repo_root, db)).strip())
        free = shutil.disk_usage(repo_root).free
        if free < db_bytes * FREE_SPACE_FACTOR:
            raise SnapshotError(
                f"not enough free disk space: {free / MB:,.0f} MB free, database {db_bytes / MB:,.0f} MB"
            )

        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        counts = parse_counts(_run("row counts", counts_command(repo_root, db)))
        print(f"Dumping database {db!r} ({db_bytes / MB:,.0f} MB) ...", flush=True)
        _run("pg_dump", dump_command(repo_root, db), stdout_path=partial / DB_FILE)
        print("Copying the filestore ...", flush=True)
        _run("filestore", filestore_export_command(repo_root, db), stdout_path=partial / FILESTORE_FILE)
        files: dict[str, dict[str, str | int]] = {
            file_name: {
                "bytes": (partial / file_name).stat().st_size,
                "sha256": sha256_file(partial / file_name),
            }
            for file_name in (DB_FILE, FILESTORE_FILE)
        }
        metadata = Metadata(
            name=name,
            created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            git_sha=_git_sha(repo_root),
            odoo_image=_odoo_image(repo_root),
            db_name=db,
            files=files,
            counts=counts,
        )
        (partial / METADATA_FILE).write_text(metadata_text(metadata), encoding="utf-8")
    except (SnapshotError, odoodb.SetupError, OSError, ValueError) as error:
        shutil.rmtree(partial, ignore_errors=True)
        return _fail("save", f"{error} (no snapshot written)")
    except KeyboardInterrupt:
        shutil.rmtree(partial, ignore_errors=True)
        return _fail("save", "interrupted (no snapshot written)")

    # Replace an existing snapshot only once the new one is complete.
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    partial.rename(target)
    shutil.rmtree(old, ignore_errors=True)

    size = sum(int(info["bytes"]) for info in files.values())
    print(f"Saved snapshot {name!r} ({size / MB:,.1f} MB) in {time.monotonic() - started:.0f} s: {target}")
    print("  " + ", ".join(f"{key} {value}" for key, value in counts.items()))
    return 0


def run_restore(repo_root: Path, name: str, ask: Callable[[str], str] = input) -> int:
    """Destructive: replace the database and its filestore with a snapshot. Asks first."""
    try:
        folder = repo_root / SNAPSHOTS_DIR / validate_name(name)
        if not folder.is_dir():
            raise SnapshotError(f"no snapshot {name!r} in {folder.parent}. See `uv run shop snapshot list`.")
        metadata = read_metadata(folder)
        verify_files(folder, metadata)
    except SnapshotError as error:
        return _fail("restore", str(error))
    settings = _prepare(repo_root, "restore")
    if settings is None:
        return 1
    db = settings.db_name
    if metadata.db_name != db:
        return _fail("restore", f"snapshot of database {metadata.db_name!r}, but ODOO_DB_NAME is {db!r}")

    print(
        f"This replaces the database {db!r} and its filestore with snapshot {name!r} ({metadata.created_at})."
    )
    try:
        answer = ask(f"Type the database name ({db}) to confirm: ")
    except EOFError:  # no terminal to answer from: never treat silence as a yes
        answer = ""
    if answer.strip() != db:
        print("Cancelled: nothing changed.")
        return 1

    started = time.monotonic()
    swapped = False
    try:
        print("Stopping Odoo ...", flush=True)
        _run("stop odoo", stack.compose_command(repo_root, "stop", "odoo"))
        print(f"Restoring the database into {restore_db_name(db)!r} ...", flush=True)
        _run("create restore database", create_restore_db_command(repo_root, db))
        _run("upload dump", upload_dump_command(repo_root), stdin_path=folder / DB_FILE)
        _run("pg_restore", pg_restore_command(repo_root, db))
        _run("remove uploaded dump", remove_uploaded_dump_command(repo_root))
        print("Unpacking the filestore ...", flush=True)
        _run("stage filestore", filestore_stage_command(repo_root, db), stdin_path=folder / FILESTORE_FILE)
        print("Replacing the current database and filestore ...", flush=True)
        _run("swap database", swap_db_command(repo_root, db))
        swapped = True
        _run("swap filestore", filestore_swap_command(repo_root, db))
    except SnapshotError as error:
        if not swapped:
            _cleanup_after_failure(repo_root, db)
        _start_odoo(repo_root)
        state = "the database was replaced but not the filestore" if swapped else "nothing changed"
        return _fail("restore", f"{error} ({state}).")
    if not _start_odoo(repo_root):
        return _fail("restore", "restored, but Odoo did not become healthy. See `uv run shop logs odoo`.")
    return _verify(repo_root, db, metadata, time.monotonic() - started)


def _cleanup_after_failure(repo_root: Path, db: str) -> None:
    for step, command in (
        ("drop restore database", drop_restore_db_command(repo_root, db)),
        ("remove uploaded dump", remove_uploaded_dump_command(repo_root)),
        ("clean filestore staging", filestore_cleanup_command(repo_root, db)),
    ):
        try:
            _run(step, command)
        except SnapshotError as error:
            print(f"  cleanup: {error}", file=sys.stderr)


def _start_odoo(repo_root: Path) -> bool:
    print("Starting Odoo ...", flush=True)
    try:
        _run("start odoo", stack.compose_command(repo_root, "up", "-d", "--wait", "odoo"))
        return True
    except SnapshotError as error:
        print(f"  {error}", file=sys.stderr)
        return False


def _verify(repo_root: Path, db: str, metadata: Metadata, seconds: float) -> int:
    try:
        found = parse_counts(_run("row counts", counts_command(repo_root, db)))
    except SnapshotError as error:
        return _fail("restore", f"restored, but the row counts could not be read: {error}")
    print(f"Restored snapshot {metadata.name!r} in {seconds:.0f} s.")
    differences = compare_counts(metadata.counts, found)
    if differences:
        # Counts are taken just before the dump: activity during the save can explain a small difference.
        print("  WARNING: row counts differ from the snapshot: " + "; ".join(differences), file=sys.stderr)
    else:
        print("  row counts match: " + ", ".join(f"{key} {value}" for key, value in found.items()))
    api_key = parse_env((repo_root / ".env").read_text(encoding="utf-8")).get(odoodb.API_KEY_ENV, "")
    try:
        odoodb.check_json2(db, api_key)
        print("  API key in .env: JSON-2 check OK")
    except odoodb.SetupError as error:
        print(
            f"  WARNING: the API key in .env does not work with this snapshot ({error}). "
            "The key belongs to the database it was created in.",
            file=sys.stderr,
        )
    return 1 if differences else 0


def run_list(repo_root: Path) -> None:
    folder = repo_root / SNAPSHOTS_DIR
    snapshots = sorted(path for path in folder.glob("*") if path.is_dir() and not path.name.startswith("."))
    if not snapshots:
        print(f"No snapshots in {folder}. Save one with `uv run shop snapshot save <name>`.")
        return
    print(f"{'name':<24} {'created (UTC)':<21} {'size':>9} {'products':>9} {'orders':>7}  git")
    for path in snapshots:
        try:
            metadata = read_metadata(path)
        except SnapshotError:
            print(f"{path.name:<24} (no readable {METADATA_FILE})")
            continue
        size = sum(int(info["bytes"]) for info in metadata.files.values()) / MB
        print(
            f"{metadata.name:<24} {metadata.created_at:<21} {size:>7.1f}MB "
            f"{metadata.counts.get('products', '?'):>9} {metadata.counts.get('sale_orders', '?'):>7}  "
            f"{metadata.git_sha[:12]}"
        )
