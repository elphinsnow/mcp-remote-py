#!/usr/bin/env bash
set -euo pipefail

# Uninstalls the global uv tool.

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found." >&2
  exit 1
fi

echo "Uninstalling mcp-remote-py (uv tool)..." >&2
uv tool uninstall mcp-remote-py || true

echo "Done." >&2
