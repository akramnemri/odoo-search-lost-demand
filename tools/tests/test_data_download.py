from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from shoptools.data.download import DownloadError, Expected, fetch, is_verified

CONTENT = bytes(range(256)) * 40  # 10,240 bytes
URL = "https://example.test/file.bin"


def expected(content: bytes = CONTENT) -> Expected:
    return Expected(URL, len(content), hashlib.sha256(content).hexdigest())


class FakeServer:
    """Serves CONTENT; honours Range unless told not to; can stop early to simulate a broken connection."""

    def __init__(self, content: bytes = CONTENT, ranges: bool = True, cut_after: int | None = None) -> None:
        self.content = content
        self.ranges = ranges
        self.cut_after = cut_after
        self.starts: list[int] = []

    def __call__(self, url: str, start: int) -> tuple[int, io.BytesIO]:
        self.starts.append(start)
        body = self.content[start:] if (start and self.ranges) else self.content
        if self.cut_after is not None:
            body = body[: self.cut_after]
        return (206 if start and self.ranges else 200), io.BytesIO(body)


def test_download_is_verified_then_renamed(tmp_path: Path) -> None:
    target = tmp_path / "raw" / "file.bin"

    fetch(expected(), target, opener=FakeServer())

    assert target.read_bytes() == CONTENT
    assert not target.with_name("file.bin.part").exists()
    assert is_verified(target, expected())


def test_interrupted_download_resumes_with_a_range_request(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    with pytest.raises(DownloadError, match="resume"):
        fetch(expected(), target, opener=FakeServer(cut_after=4000))
    assert not target.exists()  # a half file never gets the final name

    server = FakeServer()
    fetch(expected(), target, opener=server)

    assert server.starts == [4000]
    assert target.read_bytes() == CONTENT


def test_server_ignoring_range_rewrites_from_the_start(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    target.with_name("file.bin.part").write_bytes(CONTENT[:3000])

    fetch(expected(), target, opener=FakeServer(ranges=False))

    assert target.read_bytes() == CONTENT


def test_wrong_checksum_is_rejected_and_never_resumed(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    corrupted = b"X" + CONTENT[1:]

    with pytest.raises(DownloadError, match="SHA-256"):
        fetch(expected(), target, opener=FakeServer(content=corrupted))

    assert not target.exists()
    assert not target.with_name("file.bin.part").exists()


def test_partial_larger_than_the_file_starts_again(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    target.with_name("file.bin.part").write_bytes(CONTENT + b"extra")
    server = FakeServer()

    fetch(expected(), target, opener=server)

    assert server.starts == [0]
    assert target.read_bytes() == CONTENT


def test_http_error_status_is_reported(tmp_path: Path) -> None:
    def not_found(url: str, start: int) -> tuple[int, io.BytesIO]:
        return 404, io.BytesIO(b"")

    with pytest.raises(DownloadError, match="HTTP 404"):
        fetch(expected(), tmp_path / "file.bin", opener=not_found)
