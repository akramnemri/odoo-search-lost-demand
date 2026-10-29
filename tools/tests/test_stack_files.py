import re
from pathlib import Path

from shoptools.envfile import parse_env

REPO_ROOT = Path(__file__).resolve().parents[2]

# ${NAME}, ${NAME:-default}, ${NAME:?message}; `$${NAME}` is escaped and read inside the container instead.
_COMPOSE_VARIABLE = re.compile(r"(?<!\$)\$\{([A-Z0-9_]+)")


def test_every_compose_variable_is_listed_in_env_example() -> None:
    used = set(_COMPOSE_VARIABLE.findall((REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")))
    listed = set(parse_env((REPO_ROOT / ".env.example").read_text(encoding="utf-8")))

    assert used, "compose.yaml should read its settings from .env"
    assert used - listed == set(), "add these variables to .env.example"


def test_published_ports_are_bound_to_localhost_only() -> None:
    compose = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")
    blocks = re.findall(r"^\s+ports:\n((?:\s+- .*\n)+)", compose, re.MULTILINE)
    published = [
        item.strip().removeprefix("- ").strip('"') for block in blocks for item in block.splitlines()
    ]

    assert len(published) == 3, "expected Elasticsearch, Kibana and Odoo ports in compose.yaml"
    for port in published:
        assert port.startswith("127.0.0.1:"), (
            f"port {port} must be bound to 127.0.0.1 (01_ARCHITECTURE.md §12)"
        )
