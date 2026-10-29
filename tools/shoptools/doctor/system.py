"""Thin access to the machine: commands, memory, disk and ports.

The checks only talk to a `System`; tests replace it with a fake that returns recorded outputs.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str

    def json(self) -> Any:
        return json.loads(self.body)


class System(Protocol):
    platform: str  # "Windows", "Darwin" or "Linux" (platform.system())

    def run(
        self, args: Sequence[str], timeout: float = 15.0, encoding: str = "utf-8"
    ) -> CommandResult | None:
        """Run a command; None when the executable is not installed."""
        ...

    def os_description(self) -> str: ...

    def ram_bytes(self) -> int | None: ...

    def cpu_count(self) -> int | None: ...

    def disk_free_bytes(self, path: Path) -> int: ...

    def read_text(self, path: Path) -> str | None: ...

    def port_in_use(self, port: int) -> bool: ...

    def http_get(
        self,
        url: str,
        auth: tuple[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
    ) -> HttpResponse | None:
        """GET a URL; None when nothing answers (connection refused, timeout). HTTP errors are responses."""
        ...


def decode_output(raw: bytes, encoding: str) -> str:
    # wsl.exe prints its own messages in UTF-16LE, unless WSL_UTF8=1 is set (then there are no NUL bytes).
    if encoding == "utf-16-le" and b"\x00" not in raw:
        encoding = "utf-8"
    return raw.decode(encoding, errors="replace").strip()


class _MemoryStatus(ctypes.Structure):
    """MEMORYSTATUSEX from the Windows API (GlobalMemoryStatusEx)."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class RealSystem:
    def __init__(self) -> None:
        self.platform = platform.system()

    def run(
        self, args: Sequence[str], timeout: float = 15.0, encoding: str = "utf-8"
    ) -> CommandResult | None:
        executable = shutil.which(args[0])
        if executable is None:
            return None
        try:
            completed = subprocess.run(
                [executable, *args[1:]], capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return CommandResult(-1, "", f"timed out after {timeout:.0f} s")
        except OSError as error:
            return CommandResult(-1, "", str(error))
        return CommandResult(
            completed.returncode,
            decode_output(completed.stdout, encoding),
            decode_output(completed.stderr, encoding),
        )

    def os_description(self) -> str:
        if self.platform == "Darwin":
            return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
        return f"{self.platform} {platform.release()} {platform.version()} ({platform.machine()})"

    def ram_bytes(self) -> int | None:
        if self.platform == "Windows":
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
            return None
        if self.platform == "Darwin":
            output = self.run(["sysctl", "-n", "hw.memsize"])
            return (
                int(output.stdout) if output is not None and output.ok and output.stdout.isdigit() else None
            )
        meminfo = self.read_text(Path("/proc/meminfo"))
        for line in (meminfo or "").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
        return None

    def cpu_count(self) -> int | None:
        return os.cpu_count()

    def disk_free_bytes(self, path: Path) -> int:
        return shutil.disk_usage(path).free

    def read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def port_in_use(self, port: int) -> bool:
        # A successful connection means something listens there (also catches listeners on 0.0.0.0).
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            return False

    def http_get(
        self,
        url: str,
        auth: tuple[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
    ) -> HttpResponse | None:
        request = urllib.request.Request(url, headers=dict(headers or {}))
        if auth is not None:
            token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, error.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return None
