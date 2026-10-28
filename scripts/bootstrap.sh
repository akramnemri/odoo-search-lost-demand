#!/usr/bin/env bash
# First command after cloning (macOS/Linux): checks uv, installs the project environment, runs the doctor.
# Usage (from anywhere): bash scripts/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Official install command (user level, no sudo):"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  read -r -p "Run it now? [y/N] " answer
  case "$answer" in
    [yY] | [yY][eE][sS])
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="$HOME/.local/bin:$PATH"
      ;;
    *)
      echo "Install uv, open a new terminal, then run this script again."
      exit 1
      ;;
  esac
fi

uv sync
exec uv run shop doctor
