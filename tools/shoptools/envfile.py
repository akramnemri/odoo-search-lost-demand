"""`uv run shop env init`: write `.env` from `.env.example`, generating every secret.

`.env.example` is the single list of variables; a value of `<generated>` marks a secret. Re-running keeps
every value already in `.env` and only fills what is missing, so it is the way to pick up keys added later.
Secret values are never printed (docs/ai/01_ARCHITECTURE.md §12).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

GENERATED = "<generated>"

# Memory settings per RAM profile (docs/ai/01_ARCHITECTURE.md §5.3). `standard` must match .env.example.
PROFILES: dict[str, dict[str, str]] = {
    "standard": {
        "RAM_PROFILE": "standard",
        "ES_HEAP": "2g",
        "ES_MEM_LIMIT": "3g",
        "KIBANA_MEM_LIMIT": "2g",
        "ODOO_MEM_LIMIT": "1536m",
        "DB_MEM_LIMIT": "1g",
    },
    "lowmem": {
        "RAM_PROFILE": "lowmem",
        "ES_HEAP": "1g",
        "ES_MEM_LIMIT": "2g",
        "KIBANA_MEM_LIMIT": "1280m",
        "ODOO_MEM_LIMIT": "1g",
        "DB_MEM_LIMIT": "512m",
    },
}


def generate_secret() -> str:
    # URL-safe characters only, so a secret never needs quoting in .env, JSON or a URL.
    return secrets.token_urlsafe(32)


@dataclass
class EnvInitResult:
    created: bool
    generated: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    profile_applied: str | None = None


def parse_env(text: str) -> dict[str, str]:
    """`KEY=value` lines in order; comments and blank lines are ignored."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.removeprefix("export ").strip()] = value.strip()
    return values


def init_env(
    example_path: Path,
    env_path: Path,
    profile: str | None = None,
    make_secret: Callable[[], str] = generate_secret,
) -> EnvInitResult:
    """Write `env_path` with the layout of `example_path`, keeping existing values and generating secrets.

    `profile` (re)applies the memory settings of a RAM profile even when `.env` already has values.
    """
    example_text = example_path.read_text(encoding="utf-8")
    existing = parse_env(env_path.read_text(encoding="utf-8")) if env_path.is_file() else {}
    overrides = PROFILES[profile] if profile is not None else {}
    result = EnvInitResult(created=not env_path.is_file(), profile_applied=profile)

    lines = []
    for line in example_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            lines.append(line)
            continue
        key, example_value = (part.strip() for part in stripped.split("=", 1))
        value = _choose_value(key, example_value, existing, overrides, make_secret, result)
        lines.append(f"{key}={value}")

    # Keys the developer added by hand stay, below the generated part.
    extra = [key for key in existing if key not in parse_env(example_text)]
    if extra:
        lines += ["", "# --- Local additions (not in .env.example) ---"]
        lines += [f"{key}={existing[key]}" for key in extra]

    # LF endings: the file is read inside Linux containers too.
    with env_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines) + "\n")
    if os.name != "nt":
        env_path.chmod(0o600)
    return result


def set_env_value(env_path: Path, key: str, value: str) -> None:
    """Set one key in `.env` (e.g. the API key written by `shop db create`), keeping every other line.

    Written to a temporary file and renamed, so an interruption never leaves a truncated `.env`.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().removeprefix("export ").split("=", 1)[0].strip() == key and "=" in line:
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    temporary = env_path.with_name(env_path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines) + "\n")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(env_path)


def _choose_value(
    key: str,
    example_value: str,
    existing: dict[str, str],
    overrides: dict[str, str],
    make_secret: Callable[[], str],
    result: EnvInitResult,
) -> str:
    if key in overrides:
        return overrides[key]
    current = existing.get(key)
    if current is not None and current != GENERATED:
        result.kept.append(key)
        return current
    if not result.created and current is None:
        result.added.append(key)
    if example_value == GENERATED:
        result.generated.append(key)
        return make_secret()
    return example_value
