from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeSystem

from shoptools.doctor.checks import (
    GB,
    DoctorContext,
    check_docker,
    check_machine,
    check_ports,
    check_repo,
    check_tools,
    is_forbidden_tracked_file,
)
from shoptools.doctor.model import CheckResult, Status
from shoptools.stack import project_name


def by_name(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {result.name: result for result in results}


def respond_all_tools(system: FakeSystem) -> None:
    system.respond("git", "--version", stdout="git version 2.51.0.windows.2")
    system.respond("git", "lfs", "version", stdout="git-lfs/3.7.0 (GitHub; windows amd64)")
    system.respond("gh", "--version", stdout="gh version 2.102.0 (2026-09-30)")
    system.respond("uv", "--version", stdout="uv 0.13.6 (329bf9448 2026-10-26)")
    system.respond("docker", "--version", stdout="Docker version 29.2.0, build 0b9d198")
    system.respond("docker", "compose", "version", stdout="Docker Compose version v5.0.2")
    system.respond("wsl", "--version", stdout="WSL version: 2.6.3.0")
    system.respond("uv", "python", "find", "3.12", stdout="C:/python312/python.exe")


def respond_running_docker(
    system: FakeSystem, memory_bytes: int = 8_329_084_928, map_count: str = "1048576"
) -> None:
    system.respond("docker", "version", "--format", "{{.Server.Version}}", stdout="29.2.0")
    system.respond(
        "docker", "version", "--format", "{{.Server.Platform.Name}}", stdout="Docker Desktop 4.60.1 (1)"
    )
    system.respond(
        "docker",
        "info",
        "--format",
        "{{.MemTotal}}|{{.NCPU}}|{{.KernelVersion}}",
        stdout=f"{memory_bytes}|4|6.6.87.2-microsoft-standard-WSL2",
    )
    system.respond("wsl", "-d", "docker-desktop", "cat", "/proc/sys/vm/max_map_count", stdout=map_count)


# --- machine ---


@pytest.mark.parametrize(
    ("ram_gb", "status"),
    [(16.9, Status.OK), (8.4, Status.WARN), (6.0, Status.FAIL)],
)
def test_ram_thresholds(
    context: DoctorContext, fake_system: FakeSystem, ram_gb: float, status: Status
) -> None:
    fake_system.ram = int(ram_gb * GB)
    assert by_name(check_machine(context))["RAM"].status is status


@pytest.mark.parametrize(
    ("free_gb", "status"),
    [(68, Status.OK), (45, Status.WARN), (10, Status.FAIL)],
)
def test_disk_thresholds(
    context: DoctorContext, fake_system: FakeSystem, free_gb: int, status: Status
) -> None:
    fake_system.disk_free = free_gb * GB
    assert by_name(check_machine(context))["free disk"].status is status


def test_two_cpu_cores_is_a_warning(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.cpus = 2
    assert by_name(check_machine(context))["CPU cores"].status is Status.WARN


def test_unknown_ram_is_a_warning_not_a_crash(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.ram = None
    assert by_name(check_machine(context))["RAM"].status is Status.WARN


# --- tools ---


def test_all_tools_present_on_windows(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_all_tools(fake_system)
    results = check_tools(context)

    assert all(result.status is Status.OK for result in results), results
    assert "WSL" in by_name(results)


def test_wsl_is_only_checked_on_windows(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.platform = "Linux"
    respond_all_tools(fake_system)

    assert "WSL" not in by_name(check_tools(context))


def test_old_git_fails_with_upgrade_hint(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_all_tools(fake_system)
    fake_system.respond("git", "--version", stdout="git version 2.30.1")
    git = by_name(check_tools(context))["Git"]

    assert git.status is Status.FAIL
    assert git.found == "2.30.1"
    assert git.hint.startswith("upgrade:")


def test_missing_gh_is_only_a_warning(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_all_tools(fake_system)
    del fake_system.commands[("gh", "--version")]
    gh = by_name(check_tools(context))["GitHub CLI"]

    assert gh.status is Status.WARN
    assert gh.found == "not found"


def test_missing_uv_fails_with_platform_install_hint(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.platform = "Darwin"
    respond_all_tools(fake_system)
    del fake_system.commands[("uv", "--version")]
    uv = by_name(check_tools(context))["uv"]

    assert uv.status is Status.FAIL
    assert uv.hint == "brew install uv"


def test_missing_python_points_to_uv_python_install(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_all_tools(fake_system)
    fake_system.respond("uv", "python", "find", "3.12", returncode=2, stderr="No interpreter found")
    python = by_name(check_tools(context))["Python 3.12"]

    assert python.status is Status.FAIL
    assert "uv python install 3.12" in python.hint


def test_tool_command_error_is_reported(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_all_tools(fake_system)
    fake_system.respond("wsl", "--version", returncode=1, stderr="Invalid command line option: --version")
    wsl = by_name(check_tools(context))["WSL"]

    assert wsl.status is Status.FAIL
    assert "Invalid command line option" in wsl.found


# --- docker ---


def test_docker_daemon_down_fails_and_skips_the_rest(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.respond(
        "docker", "version", "--format", "{{.Server.Version}}", returncode=1, stderr="failed to connect"
    )
    results = check_docker(context)

    assert [result.status for result in results] == [Status.FAIL, Status.SKIP]
    assert "Docker Desktop" in results[0].hint


def test_docker_running_with_standard_memory(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_running_docker(fake_system)
    results = by_name(check_docker(context))

    assert results["memory for Docker"].status is Status.OK
    assert "standard" in results["memory for Docker"].found
    assert results["Docker Desktop"].found == "4.60.1"
    assert results["backend"].status is Status.OK
    assert results["vm.max_map_count"].status is Status.OK


def test_docker_memory_for_lowmem_profile_is_a_warning(
    context: DoctorContext, fake_system: FakeSystem
) -> None:
    respond_running_docker(fake_system, memory_bytes=6 * GB)
    memory = by_name(check_docker(context))["memory for Docker"]

    assert memory.status is Status.WARN
    assert "lowmem" in memory.found


def test_low_max_map_count_fails(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_running_docker(fake_system, map_count="65530")
    result = by_name(check_docker(context))["vm.max_map_count"]

    assert result.status is Status.FAIL
    assert "sysctl -w vm.max_map_count=262144" in result.hint


def test_max_map_count_is_read_from_proc_on_linux(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.platform = "Linux"
    respond_running_docker(fake_system)
    fake_system.files["/proc/sys/vm/max_map_count"] = "262144\n"
    results = by_name(check_docker(context))

    assert results["vm.max_map_count"].status is Status.OK
    assert "backend" not in results  # the WSL2 backend check is Windows-only


def test_max_map_count_is_skipped_on_macos(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.platform = "Darwin"
    respond_running_docker(fake_system)

    assert by_name(check_docker(context))["vm.max_map_count"].status is Status.SKIP


def test_missing_images_warn_and_present_images_pass(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_running_docker(fake_system)
    present = context.expected.stack_images[0]
    fake_system.respond("docker", "image", "inspect", "--format", "{{.Id}}", present, stdout="sha256:abc")
    images = [result for result in check_docker(context) if result.name.startswith("image ")]

    assert [result.status for result in images] == [Status.OK] + [Status.WARN] * (len(images) - 1)


# --- ports ---


def test_free_and_busy_ports(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.busy_ports = {8069}
    results = by_name(check_ports(context))

    assert results["port 8069"].status is Status.FAIL
    assert "Get-NetTCPConnection -LocalPort 8069" in results["port 8069"].hint
    assert results["port 9200"].status is Status.OK


def test_port_used_by_our_own_stack_is_ok(context: DoctorContext, fake_system: FakeSystem) -> None:
    fake_system.busy_ports = {9200}
    project = project_name(context.repo_root)
    fake_system.respond(
        "docker",
        "ps",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--format",
        "{{.Ports}}",
        stdout="127.0.0.1:9200->9200/tcp\n127.0.0.1:5601->5601/tcp",
    )

    assert by_name(check_ports(context))["port 9200"].status is Status.OK


def test_project_name_comes_from_compose_yaml(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(
        "# comment\nname: odoo-search-lost-demand\n\nservices: {}\n", encoding="utf-8"
    )

    assert project_name(tmp_path) == "odoo-search-lost-demand"


def test_project_name_without_compose_name_follows_compose_rules() -> None:
    assert project_name(Path("C:/work/Odoo-Search Lost.Demand")) == "odoo-searchlostdemand"


# --- repo ---


def git_args(context: DoctorContext, *args: str) -> tuple[str, ...]:
    return ("git", "-C", str(context.repo_root), *args)


def respond_healthy_repo(context: DoctorContext, system: FakeSystem) -> None:
    system.respond(*git_args(context, "rev-parse", "--show-toplevel"), stdout=str(context.repo_root))
    system.respond(*git_args(context, "config", "--get", "core.autocrlf"), stdout="false")
    system.respond(*git_args(context, "config", "--get", "core.longpaths"), stdout="true")
    system.respond(
        *git_args(context, "config", "--get", "filter.lfs.process"), stdout="git-lfs filter-process"
    )
    system.respond(
        *git_args(context, "ls-files", "-z"), stdout="README.md\0data/README.md\0tools/shoptools/cli.py\0"
    )
    (context.repo_root / ".gitattributes").write_text("* text=auto eol=lf\n", encoding="utf-8")
    (context.repo_root / ".odoo-src").mkdir()


def test_healthy_repository(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_healthy_repo(context, fake_system)
    results = check_repo(context)

    statuses = {result.name: result.status for result in results}
    assert statuses.pop(".env") is Status.SKIP  # no .env.example before Task 1.1
    assert set(statuses.values()) == {Status.OK}


def test_outside_a_git_checkout_fails(context: DoctorContext, fake_system: FakeSystem) -> None:
    results = check_repo(context)

    assert len(results) == 1
    assert results[0].status is Status.FAIL


def test_autocrlf_true_warns_and_offers_a_local_fix(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_healthy_repo(context, fake_system)
    fake_system.respond(*git_args(context, "config", "--get", "core.autocrlf"), stdout="true")
    result = by_name(check_repo(context))["core.autocrlf"]

    assert result.status is Status.WARN
    assert result.fix is not None
    assert result.fix.command == git_args(context, "config", "--local", "core.autocrlf", "false")


def test_tracked_secret_and_dataset_fail(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_healthy_repo(context, fake_system)
    fake_system.respond(
        *git_args(context, "ls-files", "-z"), stdout="README.md\0.env\0data/raw/esci/products.parquet\0"
    )
    result = by_name(check_repo(context))["tracked files"]

    assert result.status is Status.FAIL
    assert ".env" in result.found
    assert "products.parquet" in result.found


def test_env_missing_keys_are_named_without_values(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_healthy_repo(context, fake_system)
    (context.repo_root / ".env.example").write_text(
        "# comment\nELASTIC_PASSWORD=\nODOO_DB=shop\n", encoding="utf-8"
    )
    (context.repo_root / ".env").write_text("ODOO_DB=shop\n", encoding="utf-8")
    result = by_name(check_repo(context))[".env"]

    assert result.status is Status.FAIL
    assert result.found == "missing keys: ELASTIC_PASSWORD"


def test_env_with_every_key_passes(context: DoctorContext, fake_system: FakeSystem) -> None:
    respond_healthy_repo(context, fake_system)
    (context.repo_root / ".env.example").write_text("A=\nB=\n", encoding="utf-8")
    (context.repo_root / ".env").write_text("export A=secret\nB=x\n", encoding="utf-8")

    assert by_name(check_repo(context))[".env"].status is Status.OK


@pytest.mark.parametrize(
    ("path", "forbidden"),
    [
        (".env", True),
        ("docker/.env.local", True),
        (".env.example", False),
        ("data/README.md", False),
        ("data/manifest.toml", False),
        ("data/raw/esci/x.csv", True),
        ("results/summary/ndcg.csv", False),
        ("results/2027-01-01_run/run.json", True),
        ("local/machine-report.md", True),
        ("dump/odoo.sql.gz", True),
        ("kaggle.json", True),
        ("docs/sources/project-specification.pdf", False),
        ("tools/shoptools/cli.py", False),
    ],
)
def test_forbidden_tracked_files(path: str, forbidden: bool) -> None:
    assert is_forbidden_tracked_file(path) is forbidden
