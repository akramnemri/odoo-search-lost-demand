"""Entry point of `uv run shop <command>`.

Every command of the roadmap is declared here so `shop --help` shows the whole tool from day one.
Commands not built yet exit with code 1 and name the task that will implement them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from shoptools import __version__

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shop",
        description="Tools for the Odoo search and lost-demand project.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name, (help_text, task) in PLANNED_COMMANDS.items():
        subparsers.add_parser(name, help=f"{help_text} [Task {task}]")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    # Placeholders accept any arguments, so the message names the missing task instead of a usage error.
    namespace, extra_args = parser.parse_known_args(argv)
    if namespace.command is None:
        if extra_args:
            parser.error(f"unrecognized arguments: {' '.join(extra_args)}")
        parser.print_help()
        return 0

    _, task = PLANNED_COMMANDS[namespace.command]
    print(
        f"shop {namespace.command}: not implemented yet (planned in Task {task}, see docs/ai/05_ROADMAP.md).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
