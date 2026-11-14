# Scripts

First command after cloning: checks that uv is installed (asks before installing it), then runs `uv sync` and
`uv run shop doctor`.

| OS | Command (from the repository root) |
|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1` |
| macOS / Linux | `bash scripts/bootstrap.sh` |
