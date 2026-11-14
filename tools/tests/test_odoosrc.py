from __future__ import annotations

import io
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

from shoptools import odoosrc, stack
from shoptools.cli import main
from shoptools.doctor.checks import odoo_source_result
from shoptools.doctor.model import Status
from shoptools.odoosrc import (
    TRANSLATION_PATTERNS,
    UnpackResult,
    excluded_patterns,
    export_command,
    measure_command,
    parse_measure,
    stamp_text,
    unpack,
)

IMAGE = "odoo:19.0-20261015"


def build_tar(members: list[tuple[str, str]]) -> io.BytesIO:
    """members: (name, kind) with kind 'file', 'dir', 'symlink', 'hardlink' or 'fifo'."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, kind in members:
            info = tarfile.TarInfo(name)
            data = b""
            if kind == "file":
                data = f"content of {name}\n".encode()
                info.size = len(data)
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
            elif kind == "symlink":
                info.type, info.linkname = tarfile.SYMTYPE, "../../../share/fonts/x.ttf"
            elif kind == "hardlink":
                info.type, info.linkname = tarfile.LNKTYPE, "odoo/release.py"
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
            archive.addfile(info, io.BytesIO(data) if kind == "file" else None)
    buffer.seek(0)
    return buffer


# --- docker commands ---


def test_translations_are_excluded_by_default_and_templates_kept() -> None:
    assert excluded_patterns(with_translations=False) == TRANSLATION_PATTERNS
    assert excluded_patterns(with_translations=True) == ()
    assert all(pattern.endswith(".po") for pattern in TRANSLATION_PATTERNS)  # *.pot templates stay


def test_export_streams_the_package_from_a_throwaway_container_without_network() -> None:
    command = export_command(IMAGE, TRANSLATION_PATTERNS)

    assert command[:8] == ["docker", "run", "--rm", "--network", "none", "--entrypoint", "tar", IMAGE]
    assert command[8:10] == ["-C", "/usr/lib/python3/dist-packages"]
    assert "--exclude=*/i18n/*.po" in command
    assert command[-3:] == ["-cf", "-", "odoo"]


def test_measure_excludes_the_same_patterns_as_the_export() -> None:
    script = measure_command(IMAGE, TRANSLATION_PATTERNS)[-1]

    for pattern in TRANSLATION_PATTERNS:
        assert f"! -path '{pattern}'" in script
    assert "-type f" in script  # symbolic links are not counted: they are skipped when unpacking


def test_parse_measure() -> None:
    size = parse_measure("38948 428622270\n19.0.post20261015\n")

    assert (size.files, size.bytes, size.version) == (38948, 428622270, "19.0.post20261015")
    with pytest.raises(ValueError):
        parse_measure("38948 428622270\n")


# --- unpacking ---


def test_unpack_writes_files_and_skips_links(tmp_path: Path) -> None:
    stream = build_tar(
        [
            ("odoo", "dir"),
            ("odoo/release.py", "file"),
            ("odoo/addons/web/static/fonts/Roboto.ttf", "symlink"),
            ("odoo/release_copy.py", "hardlink"),
        ]
    )
    seen: list[int] = []

    result = unpack(stream, tmp_path, progress=lambda progress: seen.append(progress.files))

    assert (tmp_path / "odoo" / "release.py").read_text() == "content of odoo/release.py\n"
    assert result.files == 1 and result.bytes == len("content of odoo/release.py\n")
    assert result.skipped_links == ["odoo/addons/web/static/fonts/Roboto.ttf", "odoo/release_copy.py"]
    assert not (tmp_path / "odoo" / "addons" / "web" / "static" / "fonts" / "Roboto.ttf").exists()
    assert seen == [1]


def test_unpack_refuses_paths_outside_the_destination(tmp_path: Path) -> None:
    destination = tmp_path / "copy"
    destination.mkdir()

    with pytest.raises(tarfile.TarError):
        unpack(build_tar([("../escape.py", "file")]), destination)
    assert not (tmp_path / "escape.py").exists()


def test_unpack_keeps_absolute_names_inside_the_destination(tmp_path: Path) -> None:
    # The `data` filter strips the leading slash instead of writing to /etc.
    unpack(build_tar([("/etc/escape.py", "file")]), tmp_path)

    assert (tmp_path / "etc" / "escape.py").is_file()


def test_unpack_refuses_special_files(tmp_path: Path) -> None:
    with pytest.raises(tarfile.TarError, match="unexpected member type"):
        unpack(build_tar([("odoo/pipe", "fifo")]), tmp_path)


def test_stamp_is_valid_toml_with_provenance() -> None:
    result = UnpackResult(files=2, bytes=10, skipped_links=['odoo/a "quoted" link'])

    stamp = tomllib.loads(stamp_text(IMAGE, "sha256:abc", "19.0.post20261015", TRANSLATION_PATTERNS, result))

    assert stamp["image"] == IMAGE
    assert stamp["image_id"] == "sha256:abc"
    assert stamp["odoo_version"] == "19.0.post20261015"
    assert stamp["excluded"] == list(TRANSLATION_PATTERNS)
    assert (stamp["files"], stamp["bytes"]) == (2, 10)
    assert stamp["skipped_links"] == ['odoo/a "quoted" link']
    assert stamp["copied_at"].endswith("Z")


# --- shop odoo-src (no call reaches the real Docker daemon) ---


@pytest.fixture
def fake_docker(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Docker running, the image present, the package measured as 2 files; the export sends that package."""
    calls: list[list[str]] = []

    def fake_stack_run(command: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="sha256:abc\n", stderr="")

    def fake_measure(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="2 60\n19.0.post20261015\n", stderr="")

    def fake_export(image: str, excluded: object, destination: Path, total_bytes: int) -> UnpackResult:
        calls.append(["export", image])
        stream = build_tar([("odoo", "dir"), ("odoo/release.py", "file"), ("odoo/http.py", "file")])
        return unpack(stream, destination)

    monkeypatch.setattr(stack, "_run", fake_stack_run)
    monkeypatch.setattr(subprocess, "run", fake_measure)
    monkeypatch.setattr(odoosrc, "_export", fake_export)
    return calls


def test_copy_creates_the_folder_with_a_stamp_the_doctor_accepts(
    tmp_path: Path, fake_docker: list[list[str]]
) -> None:
    assert odoosrc.run_copy(tmp_path, IMAGE) == 0

    assert (tmp_path / ".odoo-src" / "odoo" / "release.py").is_file()
    assert not (tmp_path / ".odoo-src.partial").exists()
    assert odoo_source_result(tmp_path, IMAGE).status is Status.OK


def test_copy_refuses_to_replace_an_existing_copy_without_force(
    tmp_path: Path, fake_docker: list[list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    old_file = tmp_path / ".odoo-src" / "odoo" / "old.py"
    old_file.parent.mkdir(parents=True)
    old_file.write_text("old", encoding="utf-8")

    assert odoosrc.run_copy(tmp_path, IMAGE) == 1
    assert "--force" in capsys.readouterr().err
    assert old_file.exists()
    assert fake_docker == []

    assert odoosrc.run_copy(tmp_path, IMAGE, force=True) == 0
    assert not old_file.exists()
    assert (tmp_path / ".odoo-src" / "odoo" / "release.py").is_file()
    assert not (tmp_path / ".odoo-src.old").exists()


def test_dry_run_measures_and_copies_nothing(
    tmp_path: Path, fake_docker: list[list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert odoosrc.run_copy(tmp_path, IMAGE, dry_run=True) == 0

    assert "2 files" in capsys.readouterr().out
    assert not (tmp_path / ".odoo-src").exists()
    assert not any(call[0] == "export" for call in fake_docker)


def test_a_file_count_mismatch_keeps_the_previous_copy(
    tmp_path: Path, fake_docker: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def measure_three_files(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="3 90\n19.0.post20261015\n", stderr="")

    monkeypatch.setattr(subprocess, "run", measure_three_files)
    previous = tmp_path / ".odoo-src" / "odoo" / "release.py"
    previous.parent.mkdir(parents=True)
    previous.write_text("previous", encoding="utf-8")

    assert odoosrc.run_copy(tmp_path, IMAGE, force=True) == 1

    assert previous.read_text(encoding="utf-8") == "previous"
    assert not (tmp_path / ".odoo-src.partial").exists()


def test_copy_never_pulls_a_missing_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []

    def image_missing(command: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        missing = command[:3] == ["docker", "image", "inspect"]
        return subprocess.CompletedProcess(command, 1 if missing else 0, stdout="", stderr="")

    monkeypatch.setattr(stack, "_run", image_missing)

    assert odoosrc.run_copy(tmp_path, IMAGE) == 1
    assert f"docker pull {IMAGE}" in capsys.readouterr().err
    assert not any("run" in command or "pull" in command for command in calls)


def test_cli_passes_the_pinned_image(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, object] = {}

    def fake_copy(repo_root: Path, image: str, **options: bool) -> int:
        received.update(image=image, **options)
        return 0

    monkeypatch.setattr(odoosrc, "run_copy", fake_copy)

    assert main(["odoo-src", "--dry-run"]) == 0
    assert received == {"image": IMAGE, "force": False, "with_translations": False, "dry_run": True}


# --- doctor ---


def test_doctor_warns_when_the_copy_is_missing_unstamped_or_stale(tmp_path: Path) -> None:
    assert odoo_source_result(tmp_path, IMAGE).status is Status.WARN

    (tmp_path / ".odoo-src").mkdir()
    unstamped = odoo_source_result(tmp_path, IMAGE)
    assert unstamped.status is Status.WARN and "SOURCE.toml" in unstamped.found

    (tmp_path / ".odoo-src" / "SOURCE.toml").write_text('image = "odoo:19.0-20250101"\n', encoding="utf-8")
    stale = odoo_source_result(tmp_path, IMAGE)
    assert stale.status is Status.WARN and "--force" in stale.hint
