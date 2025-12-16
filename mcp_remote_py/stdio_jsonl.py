from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, AsyncIterator, Dict, Optional

from .logging_utils import log


JsonObject = Dict[str, Any]


async def iter_stdin_messages() -> AsyncIterator[JsonObject]:
    """Yield newline-delimited JSON-RPC messages from stdin.

    Node MCP SDK stdio framing is JSON per line with a trailing '\n'.
    """

    # On Unix, we can integrate stdin into asyncio without threads.
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        while True:
            line = await reader.readline()
            if not line:
                return
            # Allow CRLF.
            line = line.rstrip(b"\r\n")
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception as e:
                log("Invalid JSON from stdin; ignoring:", e)
                continue
            if isinstance(msg, dict):
                yield msg
            else:
                log("Non-object JSON from stdin; ignoring")
        
    # Windows fallback: blocking readline in a thread.
    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline)
        if not line:
            return
        line = line.rstrip(b"\r\n")
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception as e:
            log("Invalid JSON from stdin; ignoring:", e)
            continue
        if isinstance(msg, dict):
            yield msg
        else:
            log("Non-object JSON from stdin; ignoring")


async def write_stdout_message(message: JsonObject) -> None:
    """Write a JSON-RPC message to stdout as a single line."""

    data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")

    # Use the underlying buffer for consistent bytes writes.
    sys.stdout.buffer.write(data)
    await asyncio.to_thread(sys.stdout.buffer.flush)


def parse_header_arg(value: str) -> Optional[tuple[str, str]]:
    """Parse a single header arg like 'Name: value'."""

    if ":" not in value:
        return None
    name, rest = value.split(":", 1)
    name = name.strip()
    header_value = rest.strip()
    if not name:
        return None
    return name, header_value
