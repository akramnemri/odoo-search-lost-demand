"""Resumable, verified download of one file (standard library only).

The bytes go to `<target>.part`; an interrupted download resumes with an HTTP Range request. The file is renamed
to its final name only when its size and SHA-256 match the pinned values, so a file at the final path is always
complete and correct (docs/ai/02_CODING_STANDARDS.md §5: atomic outputs, checksums).
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK = 1024 * 1024
USER_AGENT = "shoptools-data-fetch"
TIMEOUT_SECONDS = 60


class DownloadError(Exception):
    """The download failed or the bytes do not match the pinned size or SHA-256."""


@dataclass(frozen=True)
class Expected:
    url: str
    size_bytes: int
    sha256: str


Opener = Callable[[str, int], tuple[int, BinaryIO]]  # (url, start offset) -> (HTTP status, body)
Progress = Callable[[int, int], None]  # (bytes so far, total)


def open_url(url: str, start: int) -> tuple[int, BinaryIO]:
    headers = {"User-Agent": USER_AGENT}
    if start:
        headers["Range"] = f"bytes={start}-"
    response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_SECONDS)
    return response.status, response


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def is_verified(path: Path, expected: Expected) -> bool:
    return path.is_file() and path.stat().st_size == expected.size_bytes and sha256_of(path) == expected.sha256


def fetch(
    expected: Expected,
    target: Path,
    opener: Opener = open_url,
    progress: Progress | None = None,
) -> None:
    """Download `expected.url` to `target`; resume from `<target>.part`; verify before the rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    start = partial.stat().st_size if partial.is_file() else 0
    if start > expected.size_bytes:
        partial.unlink()  # larger than the real file: never valid, start again
        start = 0
    if start < expected.size_bytes:
        status, body = opener(expected.url, start)
        with body:
            if start and status != 206:
                start = 0  # the server ignored the Range header: rewrite from the beginning
            if status not in (200, 206):
                raise DownloadError(f"{expected.url}: HTTP {status}")
            with partial.open("r+b" if start else "wb") as handle:
                handle.seek(start)
                handle.truncate()
                written = start
                while chunk := body.read(CHUNK):
                    handle.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, expected.size_bytes)
    _verify_and_rename(partial, target, expected)


def _verify_and_rename(partial: Path, target: Path, expected: Expected) -> None:
    size = partial.stat().st_size
    if size != expected.size_bytes:
        raise DownloadError(
            f"{target.name}: {size} bytes, expected {expected.size_bytes}. Run the fetch again to resume."
        )
    actual = sha256_of(partial)
    if actual != expected.sha256:
        partial.unlink()  # complete but wrong: never resume from it
        raise DownloadError(f"{target.name}: SHA-256 {actual} does not match the pinned {expected.sha256}")
    os.replace(partial, target)


class ProgressLine:
    """One updating line: percent, MB, speed and ETA, at most twice a second."""

    def __init__(self, label: str, write: Callable[[str], None]) -> None:
        self.label = label
        self.write = write
        self.started = time.monotonic()
        self.first: int | None = None
        self.last_print = 0.0

    def __call__(self, done: int, total: int) -> None:
        now = time.monotonic()
        if self.first is None:
            self.first = done
        if now - self.last_print < 0.5 and done < total:
            return
        self.last_print = now
        elapsed = max(now - self.started, 1e-6)
        speed = (done - self.first) / elapsed
        eta = (total - done) / speed if speed > 0 else 0
        self.write(
            f"\r  {self.label}: {done / total:6.1%}  {done / 1e6:,.0f}/{total / 1e6:,.0f} MB"
            f"  {speed / 1e6:5.1f} MB/s  ETA {eta:4.0f} s"
        )
