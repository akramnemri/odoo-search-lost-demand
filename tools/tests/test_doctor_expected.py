from pathlib import Path

import pytest

from shoptools.doctor.expected import (
    VERSIONS_FILE,
    Expected,
    find_repo_root,
    parse_version,
    version_at_least,
)
from shoptools.doctor.model import Status
from shoptools.doctor.system import decode_output


@pytest.mark.parametrize(
    ("output", "version"),
    [
        ("git version 2.51.0.windows.2", (2, 51, 0)),
        ("git-lfs/3.7.0 (GitHub; windows amd64; go 1.24.4; git 92dddf56)", (3, 7, 0)),
        ("gh version 2.102.0 (2026-09-30)", (2, 102, 0)),
        ("uv 0.13.6 (329bf9448 2026-10-26 x86_64-pc-windows-msvc)", (0, 13, 6)),
        ("Docker Compose version v5.0.2", (5, 0, 2)),
        ("Docker Desktop 4.60.1 (218372)", (4, 60, 1)),
        ("WSL version: 2.6.3.0\nKernel version: 6.6.87.2-1", (2, 6, 3)),
        ("29.2", (29, 2, 0)),
        ("no version here", None),
    ],
)
def test_parse_version(output: str, version: tuple[int, int, int] | None) -> None:
    assert parse_version(output) == version


def test_version_at_least_compares_numerically() -> None:
    assert version_at_least((2, 51, 0), "2.40")
    assert version_at_least((0, 13, 6), "0.13.6")
    assert not version_at_least((0, 13, 5), "0.13.6")
    assert version_at_least((4, 100, 0), "4.60")  # numeric, not alphabetical


def test_version_at_least_rejects_a_broken_minimum() -> None:
    with pytest.raises(ValueError, match="invalid minimum"):
        version_at_least((1, 0, 0), "latest")


def test_real_versions_file_loads(expected: Expected) -> None:
    assert expected.host_python == "3.12"
    assert expected.tools["gh"].severity is Status.WARN
    assert expected.tools["git"].severity is Status.FAIL
    assert len(expected.stack_images) == 4
    assert all(":" in image for image in expected.stack_images)
    assert 9200 in expected.ports
    assert expected.docker_memory_gb["standard"] > expected.docker_memory_gb["lowmem"]


def test_find_repo_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / VERSIONS_FILE).parent.mkdir(parents=True)
    (tmp_path / VERSIONS_FILE).write_text("", encoding="utf-8")
    nested = tmp_path / "tools" / "shoptools"
    nested.mkdir(parents=True)

    assert find_repo_root(nested) == tmp_path


def test_find_repo_root_outside_a_repository(tmp_path: Path) -> None:
    assert find_repo_root(tmp_path) is None


def test_decode_output_handles_wsl_utf16_and_utf8() -> None:
    assert (
        decode_output("WSL version: 2.6.3.0\r\n".encode("utf-16-le"), "utf-16-le") == "WSL version: 2.6.3.0"
    )
    # With WSL_UTF8=1, wsl.exe prints UTF-8 even though we asked for UTF-16.
    assert decode_output(b"WSL version: 2.6.3.0\n", "utf-16-le") == "WSL version: 2.6.3.0"
