"""`uv run shop odoo-src`: copy the Odoo package of the pinned image into .odoo-src/ (docs/ai/06_ENVIRONMENT_SETUP.md §5).

The agent reads the real 19.0 code there before overriding or calling it (CLAUDE.md), so the copy comes from the pinned
image: it is exactly the code that runs. Layout `.odoo-src/odoo/...`: an IDE that marks `.odoo-src/` as a source root
resolves `import odoo`. The copy is reference material, git-ignored; never edit it.

`tar` in a throw-away container streams the package to this process, which unpacks it with tarfile's `data` filter.
Compared with `docker create` + `docker cp`: no container is left behind, translations are excluded at the source, and
symbolic links (fonts that point outside the package) are skipped instead of failing on Windows.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from shoptools import stack

# In 19.0 `odoo` is a namespace package (`odoo.__file__` is None), so the path is fixed here, checked in the image.
PACKAGE_PARENT = "/usr/lib/python3/dist-packages"
PACKAGE = "odoo"
TARGET_DIR = ".odoo-src"
PARTIAL_DIR = ".odoo-src.partial"  # unpacked here first, so an interrupted copy never looks complete
OLD_DIR = ".odoo-src.old"
STAMP_FILE = "SOURCE.toml"

# Translations are ~870 MB of the 1.5 GB package and the shop is English-only. Templates (*.pot) are kept.
TRANSLATION_PATTERNS = ("*/i18n/*.po", "*/i18n_extra/*.po")
MEASURE_TIMEOUT_SECONDS = 120
FREE_SPACE_FACTOR = 1.5  # many small files take more room on disk than their byte count
PROGRESS_INTERVAL_SECONDS = 5.0

MB = 1024 * 1024


@dataclass(frozen=True)
class PackageSize:
    files: int
    bytes: int
    version: str


@dataclass
class UnpackResult:
    files: int = 0
    bytes: int = 0
    skipped_links: list[str] = field(default_factory=list)


def excluded_patterns(with_translations: bool) -> tuple[str, ...]:
    return () if with_translations else TRANSLATION_PATTERNS


def _docker_run(image: str, entrypoint: str) -> list[str]:
    # No network: the container only reads its own files.
    return ["docker", "run", "--rm", "--network", "none", "--entrypoint", entrypoint, image]


def measure_command(image: str, excluded: Sequence[str]) -> list[str]:
    """Count the files and bytes that will be copied (symbolic links excluded), and read the package version."""
    filters = " ".join(f"! -path '{pattern}'" for pattern in excluded)
    script = (
        f"cd {PACKAGE_PARENT}"
        f" && find {PACKAGE} -type f {filters} -printf '%s\\n' | awk '{{n++; s+=$1}} END {{print n+0, s+0}}'"
        f" && sed -n 's/^Version: //p' {PACKAGE}-*.egg-info/PKG-INFO"
    )
    return [*_docker_run(image, "sh"), "-c", script]


def export_command(image: str, excluded: Sequence[str]) -> list[str]:
    # GNU tar matches --exclude patterns against the whole member name, `*` included `/`.
    return [
        *_docker_run(image, "tar"),
        "-C",
        PACKAGE_PARENT,
        *(f"--exclude={pattern}" for pattern in excluded),
        "-cf",
        "-",
        PACKAGE,
    ]


def parse_measure(stdout: str) -> PackageSize:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        raise ValueError(f"unexpected measurement output: {stdout!r}")
    files, size = lines[0].split()
    return PackageSize(files=int(files), bytes=int(size), version=lines[1])


def unpack(
    stream: IO[bytes], destination: Path, progress: Callable[[UnpackResult], None] | None = None
) -> UnpackResult:
    """Unpack a tar stream; links are skipped and listed, anything but files and folders is refused."""
    result = UnpackResult()
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            if member.issym() or member.islnk():
                result.skipped_links.append(member.name)
                continue
            if not (member.isfile() or member.isdir()):
                raise tarfile.TarError(f"unexpected member type in the Odoo package: {member.name}")
            # The `data` filter refuses absolute paths and `..`, and drops special permission bits.
            archive.extract(member, destination, filter="data")
            if member.isfile():
                result.files += 1
                result.bytes += member.size
                if progress is not None:
                    progress(result)
    return result


def stamp_text(image: str, image_id: str, version: str, excluded: Sequence[str], result: UnpackResult) -> str:
    """Provenance of the copy, read back by the doctor (TOML; JSON strings are valid TOML basic strings)."""

    def toml_list(values: Sequence[str]) -> str:
        return "[" + ", ".join(_toml_string(value) for value in values) + "]"

    copied_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "\n".join(
        [
            "# Written by `uv run shop odoo-src` (Task 1.4a). Reference copy of the Odoo package: never edit it.",
            f"image = {_toml_string(image)}",
            f"image_id = {_toml_string(image_id)}",
            f"odoo_version = {_toml_string(version)}",
            f"package_path = {_toml_string(f'{PACKAGE_PARENT}/{PACKAGE}')}",
            f"copied_at = {_toml_string(copied_at)}",
            f"excluded = {toml_list(excluded)}",
            f"files = {result.files}",
            f"bytes = {result.bytes}",
            f"skipped_links = {toml_list(result.skipped_links)}",
            "",
        ]
    )


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _remove_tree(path: Path) -> None:
    def make_writable_and_retry(function: Callable[[str], object], target: str, error: BaseException) -> None:
        # Windows refuses to delete read-only files.
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onexc=make_writable_and_retry)


# --- command (prints for the person at the terminal) ---


def _fail(message: str) -> int:
    print(f"shop odoo-src: {message}", file=sys.stderr)
    return 1


def _image_id(image: str) -> str | None:
    result = stack._run(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture=True)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip()


def _measure(image: str, excluded: Sequence[str]) -> PackageSize | None:
    try:
        result = subprocess.run(
            measure_command(image, excluded),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=MEASURE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return parse_measure(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _print_progress(total_bytes: int) -> Callable[[UnpackResult], None]:
    started = last_print = time.monotonic()

    def show(result: UnpackResult) -> None:
        nonlocal last_print
        now = time.monotonic()
        if now - last_print < PROGRESS_INTERVAL_SECONDS:
            return
        last_print = now
        done = result.bytes / total_bytes if total_bytes else 1.0
        eta = (now - started) * (1 - done) / done if done else 0.0
        print(
            f"  {result.files:,} files, {result.bytes / MB:,.0f} / {total_bytes / MB:,.0f} MB "
            f"({done:.0%}), about {eta:.0f} s left",
            flush=True,
        )

    return show


def _export(image: str, excluded: Sequence[str], destination: Path, total_bytes: int) -> UnpackResult:
    """Stream the package out of the image into `destination`; raises on any failure."""
    with tempfile.TemporaryFile() as errors:
        # stderr goes to a file, not a pipe: a full stderr pipe would block tar while we read stdout.
        process = subprocess.Popen(export_command(image, excluded), stdout=subprocess.PIPE, stderr=errors)
        assert process.stdout is not None
        try:
            result = unpack(process.stdout, destination, _print_progress(total_bytes))
        except BaseException:
            process.kill()
            raise
        finally:
            process.stdout.close()
            returncode = process.wait()
        if returncode != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", errors="replace").strip().splitlines()
            raise RuntimeError(f"tar in the container exited with {returncode}: {' | '.join(message[:3])}")
    return result


def run_copy(
    repo_root: Path, image: str, force: bool = False, with_translations: bool = False, dry_run: bool = False
) -> int:
    target, partial, old = repo_root / TARGET_DIR, repo_root / PARTIAL_DIR, repo_root / OLD_DIR
    if target.exists() and not (force or dry_run):
        return _fail(f"{target} already exists. Replace it with `uv run shop odoo-src --force`.")
    if not stack.docker_reachable():
        return _fail("Docker is not running. Start Docker Desktop, then retry.")
    image_id = _image_id(image)
    if image_id is None:
        # No surprise downloads (CLAUDE.md): pulling is a separate, explicit step.
        return _fail(f"image {image} is not pulled yet. Pull it with `docker pull {image}` (docs/setup/VERSIONS.md).")

    excluded = excluded_patterns(with_translations)
    size = _measure(image, excluded)
    if size is None:
        return _fail(f"could not measure {PACKAGE_PARENT}/{PACKAGE} in {image}. Is it still an Odoo image?")
    what = "translations included" if with_translations else "translations (*.po) excluded"
    print(f"Odoo {size.version} in {image}: {size.files:,} files, {size.bytes / MB:,.0f} MB ({what}).")
    if dry_run:
        print("Dry run: nothing copied.")
        return 0

    needed = int(size.bytes * FREE_SPACE_FACTOR)
    free = shutil.disk_usage(repo_root).free
    if free < needed:
        return _fail(f"not enough free disk space: {free / MB:,.0f} MB free, {needed / MB:,.0f} MB needed.")

    print(f"Copying into {target} ...", flush=True)
    started = time.monotonic()
    _remove_tree(partial)  # left over by an interrupted run
    partial.mkdir()
    try:
        result = _export(image, excluded, partial, size.bytes)
        if result.files != size.files:
            raise RuntimeError(f"copied {result.files} files, the image has {size.files}")
        (partial / STAMP_FILE).write_text(
            stamp_text(image, image_id, size.version, excluded, result), encoding="utf-8"
        )
    except (OSError, RuntimeError, tarfile.TarError) as error:
        _remove_tree(partial)
        return _fail(f"copy failed, nothing changed in {target}: {error}")
    except KeyboardInterrupt:
        _remove_tree(partial)
        return _fail(f"interrupted, nothing changed in {target}.")

    # Swap only once the new copy is complete, so .odoo-src/ is never half-written.
    _remove_tree(old)
    if target.exists():
        target.rename(old)
    partial.rename(target)
    _remove_tree(old)

    print(
        f"Copied {result.files:,} files ({result.bytes / MB:,.0f} MB) in {time.monotonic() - started:.0f} s "
        f"to {target / PACKAGE}"
    )
    if result.skipped_links:
        print(f"  skipped {len(result.skipped_links)} symbolic links (listed in {TARGET_DIR}/{STAMP_FILE})")
    print(f"  example: {TARGET_DIR}/{PACKAGE}/addons/website_sale/controllers/main.py")
    print("Read-only reference: never edit it. `uv run shop doctor --section repo` checks it.")
    return 0
