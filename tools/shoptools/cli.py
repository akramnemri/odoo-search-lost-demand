"""Entry point of `uv run shop <command>`.

Every command of the roadmap is declared here so `shop --help` shows the whole tool from day one.
Commands not built yet exit with code 1 and name the task that will implement them.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence

from shoptools import __version__
from shoptools.doctor.report import SECTIONS, run_doctor

# command -> (help text, roadmap task that implements it; see docs/ai/05_ROADMAP.md)
PLANNED_COMMANDS: dict[str, tuple[str, str]] = {
    "doctor": ("check the machine, tools, stack and data", "0.5"),
    "lint": ("run the pre-commit quality gate", "0.6"),
    "env": ("generate .env secrets from .env.example", "1.1"),
    "up": ("start the Docker Compose stack", "1.1"),
    "down": ("stop the stack (never removes volumes)", "1.1"),
    "status": ("show the state of the stack", "1.1"),
    "logs": ("show logs of a stack service", "1.1"),
    "db": ("create or reset the Odoo database", "1.2"),
    "snapshot": ("save, restore or list database snapshots", "1.2"),
    "test": ("run the tools or module test suites", "1.3"),
    "odoo-src": ("copy the Odoo source from the pinned image into .odoo-src/", "1.4"),
    "data": ("fetch datasets and build the catalog slice", "2.1"),
    "import": ("import the catalog into Odoo", "2.4"),
    "index": ("rebuild or check the product index", "3.1"),
    "probe": ("measure freshness of products and events", "3.2"),
    "eval": ("run evaluation campaigns (NDCG, detection, speed)", "3.4"),
    "kibana": ("import or export Kibana saved objects", "4.5"),
    "shoppers": ("run Locust virtual shoppers", "5.3"),
    "scenario": ("run scripted end-to-end scenarios", "6.4"),
    "replay": ("replay REES46 events into Elasticsearch", "7.3"),
}


def _add_doctor_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--section",
        action="append",
        choices=SECTIONS,
        help="check only this section (repeatable); default: all",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="show expected values and hints for every line"
    )
    parser.add_argument(
        "--fix", action="store_true", help="offer safe repository-level fixes, asking before each one"
    )


def _run_doctor(namespace: argparse.Namespace) -> int:
    return run_doctor(namespace.section, as_json=namespace.json, verbose=namespace.verbose, fix=namespace.fix)


def _add_no_arguments(parser: argparse.ArgumentParser) -> None:
    pass


def _run_lint(namespace: argparse.Namespace) -> int:
    # Same command as the CI `lint` job, run with this environment's pre-commit (pinned in uv.lock).
    return subprocess.run([sys.executable, "-m", "pre_commit", "run", "--all-files"], check=False).returncode


# command -> (function adding its arguments, function running it)
IMPLEMENTED_COMMANDS: dict[
    str, tuple[Callable[[argparse.ArgumentParser], None], Callable[[argparse.Namespace], int]]
] = {
    "doctor": (_add_doctor_arguments, _run_doctor),
    "lint": (_add_no_arguments, _run_lint),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shop",
        description="Tools for the Odoo search and lost-demand project.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name, (help_text, task) in PLANNED_COMMANDS.items():
        command = subparsers.add_parser(name, help=f"{help_text} [Task {task}]")
        if name in IMPLEMENTED_COMMANDS:
            add_arguments, _ = IMPLEMENTED_COMMANDS[name]
            add_arguments(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    # Placeholders accept any arguments, so the message names the missing task instead of a usage error.
    namespace, extra_args = parser.parse_known_args(argv)
    implemented = IMPLEMENTED_COMMANDS.get(namespace.command)
    if extra_args and (namespace.command is None or implemented is not None):
        parser.error(f"unrecognized arguments: {' '.join(extra_args)}")
    if namespace.command is None:
        parser.print_help()
        return 0
    if implemented is not None:
        _, run = implemented
        return run(namespace)

    _, task = PLANNED_COMMANDS[namespace.command]
    print(
        f"shop {namespace.command}: not implemented yet (planned in Task {task}, see docs/ai/05_ROADMAP.md).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
