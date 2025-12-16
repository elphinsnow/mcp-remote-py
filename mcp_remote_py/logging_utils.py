from __future__ import annotations

import os
import sys
from typing import Any


def log(*parts: Any) -> None:
    """Write logs to stderr only (stdout is reserved for MCP protocol)."""

    pid = os.getpid()
    msg = " ".join(str(p) for p in parts)
    sys.stderr.write(f"[{pid}] {msg}\n")
    sys.stderr.flush()
