"""Decision logic of the doctor sections (docs/ai/06_ENVIRONMENT_SETUP.md §7.2).

Checks never touch the machine directly: they ask `context.system` for facts and command outputs,
so tests run them with recorded outputs for Windows, macOS and Linux.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from shoptools.doctor.expected import Expected, ToolRequirement, parse_version, version_at_least
from shoptools.doctor.model import CheckResult, Fix, Status
from shoptools.doctor.system import CommandResult, System

GB = 1_000_000_000  # thresholds in the docs are decimal gigabytes
TROUBLESHOOTING = "docs/setup/TROUBLESHOOTING.md"
SUPPORTED_PLATFORMS = ("Windows", "Darwin", "Linux")

INSTALL_HINTS: dict[str, dict[str, str]] = {
    "git": {
        "Windows": "winget install --id Git.Git -e --source winget",
        "Darwin": "brew install git",
        "Linux": "sudo apt-get install git",
    },
    "git_lfs": {
        "Windows": "included in Git for Windows; then run `git lfs install`",
        "Darwin": "brew install git-lfs && git lfs install",
        "Linux": "sudo apt-get install git-lfs && git lfs install",
    },
    "gh": {
        "Windows": "winget install --id GitHub.cli -e --source winget",
        "Darwin": "brew install gh",
        "Linux": "official apt repository: https://cli.github.com",
    },
    "uv": {
        "Windows": "winget install --id astral-sh.uv -e --source winget",
        "Darwin": "brew install uv",
        "Linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
    },
    "docker_engine": {
        "Windows": "winget install --id Docker.DockerDesktop -e --source winget",
        "Darwin": "brew install --cask docker-desktop",
        "Linux": "https://docs.docker.com/engine/install/",
    },
    "docker_compose": {
        "Windows": "update Docker Desktop",
        "Darwin": "update Docker Desktop",
        "Linux": "sudo apt-get install docker-compose-plugin",
    },
    "wsl": {"Windows": "wsl --update (administrator PowerShell)"},
}

# (key in versions.toml [tools], label, command printing the version)
TOOL_PROBES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("git", "Git", ("git", "--version")),
    ("git_lfs", "Git LFS", ("git", "lfs", "version")),
    ("gh", "GitHub CLI", ("gh", "--version")),
    ("uv", "uv", ("uv", "--version")),
    ("docker_engine", "Docker CLI", ("docker", "--version")),
    ("docker_compose", "Docker Compose v2", ("docker", "compose", "version")),
)

_PUBLISHED_PORT = re.compile(r":(\d+)->")
_FORBIDDEN_SUFFIXES = (".parquet", ".dump", ".sql", ".sql.gz", ".backup", ".pem", ".key")


@dataclass(frozen=True)
class DoctorContext:
    system: System
    expected: Expected
    repo_root: Path


def _install_hint(tool: str, platform: str) -> str:
    return INSTALL_HINTS.get(tool, {}).get(platform, f"see {TROUBLESHOOTING}")


def _first_line(output: CommandResult) -> str:
    text = output.stderr or output.stdout
    return text.splitlines()[0] if text else f"exit code {output.returncode}"


def version_check(
    section: str, name: str, output: CommandResult | None, requirement: ToolRequirement, hint: str
) -> CheckResult:
    expected = f">= {requirement.min_version}"
    if output is None:
        return CheckResult(section, name, requirement.severity, "not found", expected, hint)
    if not output.ok:
        return CheckResult(
            section, name, requirement.severity, f"error: {_first_line(output)}", expected, hint
        )
    version = parse_version(output.stdout)
    if version is None:
        return CheckResult(section, name, Status.WARN, "version not recognised", expected, hint)
    found = ".".join(str(part) for part in version)
    if version_at_least(version, requirement.min_version):
        return CheckResult(section, name, Status.OK, found, expected)
    return CheckResult(section, name, requirement.severity, found, expected, f"upgrade: {hint}")


# --- machine ---


def check_machine(context: DoctorContext) -> list[CheckResult]:
    system, expected = context.system, context.expected
    os_status = Status.OK if system.platform in SUPPORTED_PLATFORMS else Status.FAIL
    return [
        CheckResult(
            "machine", "operating system", os_status, system.os_description(), "Windows, macOS or Linux"
        ),
        ram_result(system.ram_bytes(), expected),
        cpu_result("machine", "CPU cores", system.cpu_count()),
        disk_result(system.disk_free_bytes(context.repo_root), expected),
    ]


def ram_result(ram_bytes: int | None, expected: Expected) -> CheckResult:
    wanted = f">= {expected.ram_gb_recommended:g} GB (min {expected.ram_gb_min:g} GB)"
    if ram_bytes is None:
        return CheckResult("machine", "RAM", Status.WARN, "unknown", wanted)
    gigabytes = ram_bytes / GB
    if gigabytes >= expected.ram_gb_recommended:
        return CheckResult("machine", "RAM", Status.OK, f"{gigabytes:.1f} GB -> standard profile", wanted)
    if gigabytes >= expected.ram_gb_min:
        return CheckResult(
            "machine",
            "RAM",
            Status.WARN,
            f"{gigabytes:.1f} GB -> lowmem profile",
            wanted,
            "use the lowmem profile and close other heavy applications",
        )
    return CheckResult(
        "machine",
        "RAM",
        Status.FAIL,
        f"{gigabytes:.1f} GB",
        wanted,
        "below the minimum in docs/ai/06_ENVIRONMENT_SETUP.md, section 2.1",
    )


def cpu_result(section: str, name: str, count: int | None) -> CheckResult:
    wanted = ">= 4 (min 2)"
    if count is None:
        return CheckResult(section, name, Status.WARN, "unknown", wanted)
    if count >= 4:
        return CheckResult(section, name, Status.OK, str(count), wanted)
    status = Status.WARN if count >= 2 else Status.FAIL
    return CheckResult(section, name, status, str(count), wanted, "load tests and replays will be slow")


def disk_result(free_bytes: int, expected: Expected) -> CheckResult:
    gigabytes = free_bytes / GB
    wanted = f">= {expected.disk_free_gb_warn:g} GB (min {expected.disk_free_gb_fail:g} GB)"
    found = f"{gigabytes:.1f} GB"
    hint = "images, datasets and Elasticsearch data need about 50 GB; free some space"
    if gigabytes < expected.disk_free_gb_fail:
        return CheckResult("machine", "free disk", Status.FAIL, found, wanted, hint)
    if gigabytes < expected.disk_free_gb_warn:
        return CheckResult("machine", "free disk", Status.WARN, found, wanted, hint)
    return CheckResult("machine", "free disk", Status.OK, found, wanted)


# --- tools ---


def check_tools(context: DoctorContext) -> list[CheckResult]:
    system, expected = context.system, context.expected
    results = [
        version_check(
            "tools", label, system.run(command), expected.tools[key], _install_hint(key, system.platform)
        )
        for key, label, command in TOOL_PROBES
    ]
    if system.platform == "Windows":
        output = system.run(("wsl", "--version"), encoding="utf-16-le")
        results.append(
            version_check("tools", "WSL", output, expected.tools["wsl"], _install_hint("wsl", "Windows"))
        )
    results.append(python_result(system, expected.host_python))
    return results


def python_result(system: System, minor: str) -> CheckResult:
    name = f"Python {minor}"
    output = system.run(("uv", "python", "find", minor))
    if output is not None and output.ok:
        return CheckResult("tools", name, Status.OK, "available", minor)
    return CheckResult(
        "tools",
        name,
        Status.FAIL,
        "not found",
        minor,
        f"uv python install {minor} (from a normal terminal, see {TROUBLESHOOTING})",
    )


# --- docker ---


def check_docker(context: DoctorContext) -> list[CheckResult]:
    system, expected = context.system, context.expected
    server = system.run(("docker", "version", "--format", "{{.Server.Version}}"))
    if server is None or not server.ok:
        found = "Docker not installed" if server is None else "not reachable"
        return [
            CheckResult(
                "docker", "daemon", Status.FAIL, found, "running", _start_docker_hint(system.platform)
            ),
            CheckResult("docker", "other docker checks", Status.SKIP, "daemon not reachable"),
        ]

    results = [
        CheckResult("docker", "daemon", Status.OK, "running", "running"),
        version_check(
            "docker",
            "Docker Engine",
            server,
            expected.tools["docker_engine"],
            _install_hint("docker_engine", system.platform),
        ),
    ]
    platform_name = system.run(("docker", "version", "--format", "{{.Server.Platform.Name}}"))
    if platform_name is not None and platform_name.ok and "Docker Desktop" in platform_name.stdout:
        results.append(
            version_check(
                "docker",
                "Docker Desktop",
                platform_name,
                expected.tools["docker_desktop"],
                "update Docker Desktop (Settings > Software updates)",
            )
        )
    results.extend(_docker_resources(system, expected))
    results.append(max_map_count_result(system, expected.vm_max_map_count_min))
    results.extend(_image_results(system, expected.stack_images))
    return results


def _start_docker_hint(platform: str) -> str:
    if platform == "Linux":
        return "sudo systemctl start docker"
    return "start Docker Desktop and wait until it says 'Engine running'"


def _docker_resources(system: System, expected: Expected) -> list[CheckResult]:
    info = system.run(("docker", "info", "--format", "{{.MemTotal}}|{{.NCPU}}|{{.KernelVersion}}"))
    if info is None or not info.ok:
        return [CheckResult("docker", "resources", Status.WARN, "docker info failed")]
    try:
        memory_text, cpu_text, kernel = info.stdout.split("|", 2)
        memory_bytes, cpus = int(memory_text), int(cpu_text)
    except ValueError:
        return [CheckResult("docker", "resources", Status.WARN, f"unexpected output: {info.stdout[:60]}")]

    results = [docker_memory_result(memory_bytes, expected), cpu_result("docker", "CPUs for Docker", cpus)]
    if system.platform == "Windows":
        if "WSL2" in kernel:
            results.append(CheckResult("docker", "backend", Status.OK, "WSL2", "WSL2"))
        else:
            results.append(
                CheckResult(
                    "docker",
                    "backend",
                    Status.WARN,
                    kernel,
                    "WSL2",
                    "Docker Desktop > Settings > General > Use the WSL 2 based engine",
                )
            )
    return results


def docker_memory_result(memory_bytes: int, expected: Expected) -> CheckResult:
    standard, lowmem = expected.docker_memory_gb["standard"], expected.docker_memory_gb["lowmem"]
    gigabytes = memory_bytes / GB
    wanted = f">= {standard:g} GB (standard), >= {lowmem:g} GB (lowmem)"
    hint = f"give Docker more memory (Windows: %USERPROFILE%\\.wslconfig), see {TROUBLESHOOTING}"
    if gigabytes >= standard:
        return CheckResult(
            "docker", "memory for Docker", Status.OK, f"{gigabytes:.1f} GB -> standard profile", wanted
        )
    if gigabytes >= lowmem:
        return CheckResult(
            "docker", "memory for Docker", Status.WARN, f"{gigabytes:.1f} GB -> lowmem profile", wanted, hint
        )
    return CheckResult("docker", "memory for Docker", Status.FAIL, f"{gigabytes:.1f} GB", wanted, hint)


def max_map_count_result(system: System, minimum: int) -> CheckResult:
    name, wanted = "vm.max_map_count", f">= {minimum}"
    if system.platform == "Windows":
        # All WSL2 distributions share one kernel: Docker Desktop's distro shows what Elasticsearch gets.
        output = system.run(("wsl", "-d", "docker-desktop", "cat", "/proc/sys/vm/max_map_count"))
        text = output.stdout if output is not None and output.ok else None
        hint = (
            f"wsl -d docker-desktop -u root sysctl -w vm.max_map_count={minimum} (until restart), "
            f"see {TROUBLESHOOTING}"
        )
    elif system.platform == "Linux":
        text = system.read_text(Path("/proc/sys/vm/max_map_count"))
        hint = (
            f"sudo sysctl -w vm.max_map_count={minimum} and add it to /etc/sysctl.d/, see {TROUBLESHOOTING}"
        )
    else:
        # macOS: the value lives inside Docker Desktop's VM; reading it would need an image pull.
        return CheckResult(
            "docker", name, Status.SKIP, "checked when Elasticsearch starts (Task 1.1)", wanted
        )

    if text is None or not text.strip().isdigit():
        return CheckResult("docker", name, Status.WARN, "unknown", wanted, hint)
    value = int(text.strip())
    if value >= minimum:
        return CheckResult("docker", name, Status.OK, str(value), wanted)
    return CheckResult("docker", name, Status.FAIL, str(value), wanted, hint)


def _image_results(system: System, images: tuple[str, ...]) -> list[CheckResult]:
    results = []
    for image in images:
        name = f"image {image.rsplit('/', 1)[-1]}"
        output = system.run(("docker", "image", "inspect", "--format", "{{.Id}}", image))
        if output is not None and output.ok:
            results.append(CheckResult("docker", name, Status.OK, "present", "present"))
        else:
            results.append(
                CheckResult(
                    "docker",
                    name,
                    Status.WARN,
                    "not pulled yet",
                    "present",
                    "pulled by `uv run shop up` (Task 1.1b)",
                )
            )
    return results


# --- ports ---


def compose_project_name(repo_root: Path) -> str:
    # Docker Compose's default project name is the folder name, lower-cased, keeping [a-z0-9_-].
    # compose.yaml sets the same `name:`; Task 1.1b reads it from there.
    return re.sub(r"[^a-z0-9_-]", "", repo_root.name.lower())


def check_ports(context: DoctorContext) -> list[CheckResult]:
    system = context.system
    project = compose_project_name(context.repo_root)
    ours = _ports_published_by(system, project)
    results = []
    for port in context.expected.ports:
        name = f"port {port}"
        if not system.port_in_use(port):
            results.append(CheckResult("ports", name, Status.OK, "free", "free"))
        elif port in ours:
            results.append(CheckResult("ports", name, Status.OK, f"used by our stack ({project})", "free"))
        else:
            results.append(
                CheckResult(
                    "ports",
                    name,
                    Status.FAIL,
                    "in use by another program",
                    "free",
                    _port_hint(system.platform, port),
                )
            )
    return results


def _ports_published_by(system: System, project: str) -> set[int]:
    output = system.run(
        ("docker", "ps", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Ports}}")
    )
    if output is None or not output.ok:
        return set()
    return {int(port) for port in _PUBLISHED_PORT.findall(output.stdout)}


def _port_hint(platform: str, port: int) -> str:
    if platform == "Windows":
        finder = f"Get-NetTCPConnection -LocalPort {port} -State Listen"
    else:
        finder = f"lsof -iTCP:{port} -sTCP:LISTEN"
    return f"find the program with `{finder}` and stop it, see {TROUBLESHOOTING}"


# --- repo ---


def check_repo(context: DoctorContext) -> list[CheckResult]:
    system, root = context.system, context.repo_root
    git = ("git", "-C", str(root))
    toplevel = system.run((*git, "rev-parse", "--show-toplevel"))
    if toplevel is None or not toplevel.ok:
        return [
            CheckResult(
                "repo",
                "git repository",
                Status.FAIL,
                "not a git checkout",
                "clone of the repository",
                "git clone https://github.com/akramnemri/odoo-search-lost-demand.git",
            )
        ]

    results = [
        CheckResult("repo", "git repository", Status.OK, "yes", "yes"),
        gitattributes_result(root),
        git_setting_result(system, git, "core.autocrlf", "false"),
    ]
    if system.platform == "Windows":
        results.append(git_setting_result(system, git, "core.longpaths", "true"))
    results.append(_lfs_result(system, git))
    results.append(tracked_files_result(system, git))
    results.append(env_file_result(root))
    results.append(_odoo_source_result(root))
    return results


def gitattributes_result(root: Path) -> CheckResult:
    path = root / ".gitattributes"
    if path.is_file() and "eol=lf" in path.read_text(encoding="utf-8"):
        return CheckResult("repo", ".gitattributes", Status.OK, "LF rule present", "LF rule present")
    return CheckResult(
        "repo",
        ".gitattributes",
        Status.FAIL,
        "LF rule missing",
        "LF rule present",
        "restore .gitattributes from the develop branch",
    )


def git_setting_result(system: System, git: tuple[str, ...], key: str, wanted: str) -> CheckResult:
    output = system.run((*git, "config", "--get", key))
    value = output.stdout.strip() if output is not None and output.ok and output.stdout.strip() else "unset"
    if value.lower() == wanted:
        return CheckResult("repo", key, Status.OK, value, wanted)
    return CheckResult(
        "repo",
        key,
        Status.WARN,
        value,
        wanted,
        f"git config --local {key} {wanted}",
        fix=Fix(f"set {key}={wanted} for this repository only", (*git, "config", "--local", key, wanted)),
    )


def _lfs_result(system: System, git: tuple[str, ...]) -> CheckResult:
    output = system.run((*git, "config", "--get", "filter.lfs.process"))
    if output is not None and output.ok and output.stdout.strip():
        return CheckResult("repo", "Git LFS filter", Status.OK, "installed", "installed")
    return CheckResult(
        "repo",
        "Git LFS filter",
        Status.WARN,
        "not installed",
        "installed",
        "git lfs install",
        fix=Fix("install the Git LFS filter (user-level git config)", ("git", "lfs", "install")),
    )


def is_forbidden_tracked_file(path: str) -> bool:
    """Files that must never be in a public repository: secrets, datasets, dumps, local folders."""
    parts = PurePosixPath(path).parts
    name = parts[-1]
    if name == ".env" or (name.startswith(".env.") and name != ".env.example") or name == "kaggle.json":
        return True
    if name.endswith(_FORBIDDEN_SUFFIXES):
        return True
    top = parts[0]
    if top in ("local", ".odoo-src", ".venv"):
        return True
    if top == "data" and path not in ("data/README.md", "data/manifest.toml"):
        return True
    return top == "results" and not path.startswith("results/summary/")


def tracked_files_result(system: System, git: tuple[str, ...]) -> CheckResult:
    output = system.run((*git, "ls-files", "-z"))
    if output is None or not output.ok:
        return CheckResult("repo", "tracked files", Status.WARN, "git ls-files failed")
    paths = [path for path in output.stdout.split("\0") if path]
    forbidden = [path for path in paths if is_forbidden_tracked_file(path)]
    wanted = "no secrets, datasets, dumps or local files"
    if not forbidden:
        return CheckResult("repo", "tracked files", Status.OK, f"{len(paths)} files, none forbidden", wanted)
    found = ", ".join(forbidden[:5]) + (f" (+{len(forbidden) - 5} more)" if len(forbidden) > 5 else "")
    return CheckResult(
        "repo",
        "tracked files",
        Status.FAIL,
        found,
        wanted,
        "git rm --cached <file>, fix .gitignore; rotate any pushed secret (03_GIT_TESTING_PIPELINE.md)",
    )


def env_keys(text: str) -> set[str]:
    keys = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            keys.add(stripped.split("=", 1)[0].removeprefix("export ").strip())
    return keys


def env_file_result(root: Path) -> CheckResult:
    example, env = root / ".env.example", root / ".env"
    if not example.is_file():
        return CheckResult(
            "repo", ".env", Status.SKIP, "available from Task 1.1 (.env.example not created yet)"
        )
    wanted = "every key of .env.example"
    if not env.is_file():
        return CheckResult("repo", ".env", Status.FAIL, "missing", wanted, "uv run shop env init")
    missing = sorted(
        env_keys(example.read_text(encoding="utf-8")) - env_keys(env.read_text(encoding="utf-8"))
    )
    if missing:
        return CheckResult(
            "repo",
            ".env",
            Status.FAIL,
            f"missing keys: {', '.join(missing)}",
            wanted,
            "add them from .env.example or regenerate with `uv run shop env init`",
        )
    return CheckResult("repo", ".env", Status.OK, "all keys present", wanted)


def _odoo_source_result(root: Path) -> CheckResult:
    if (root / ".odoo-src").is_dir():
        return CheckResult("repo", ".odoo-src/", Status.OK, "present", "present")
    return CheckResult(
        "repo", ".odoo-src/", Status.WARN, "missing", "present", "uv run shop odoo-src (Task 1.4a)"
    )
