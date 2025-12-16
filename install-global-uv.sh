#!/usr/bin/env bash
set -euo pipefail

# Installs this project as a global user tool using uv.
# Expected outcome: ~/.local/bin/mcp-remote-py exists and is executable.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

# Ensure the tool bin dir matches the user's request (~/.local/bin)
export UV_TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$UV_TOOL_BIN_DIR"

echo "Installing mcp-remote-py into: $UV_TOOL_BIN_DIR" >&2

# Editable install from local source so changes can be picked up easily during development.
# --force makes this idempotent for re-runs.
uv tool install --editable . --force

if command -v mcp-remote-py >/dev/null 2>&1; then
  echo "OK: mcp-remote-py is on PATH: $(command -v mcp-remote-py)" >&2
else
  echo "Installed, but mcp-remote-py is not on PATH." >&2
  echo "Add to your shell rc: export PATH=\"$UV_TOOL_BIN_DIR:$PATH\"" >&2
  echo "Then restart your shell." >&2
fi

echo "Run: mcp-remote-py --help" >&2
