from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from .logging_utils import log
from .remote_transport import RemoteTransport, TransportStrategy
from .stdio_jsonl import iter_stdin_messages, write_stdout_message


JsonObject = Dict[str, Any]


async def run_proxy(
    server_url: str,
    headers: Optional[dict[str, str]] = None,
    transport: TransportStrategy = "http-first",
) -> None:
    """Run a minimal STDIO <-> remote proxy."""

    remote = RemoteTransport(server_url, headers=headers, transport=transport)

    remote_closed = asyncio.Event()
    local_eof = asyncio.Event()

    # Remote -> Local
    remote_to_local_queue: asyncio.Queue[JsonObject] = asyncio.Queue(maxsize=256)

    def on_remote_message(msg: JsonObject) -> None:
        try:
            remote_to_local_queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Backpressure policy: drop with log.
            log("Remote->Local queue full; dropping message")

    def on_remote_close() -> None:
        remote_closed.set()

    def on_remote_error(e: Exception) -> None:
        log("Remote error:", e)

    remote.onmessage = on_remote_message
    remote.onclose = on_remote_close
    remote.onerror = on_remote_error

    await remote.start_background()

    async def pump_remote_to_local() -> None:
        while True:
            if remote_closed.is_set() and remote_to_local_queue.empty():
                return
            try:
                msg = await asyncio.wait_for(remote_to_local_queue.get(), timeout=0.25)
            except asyncio.TimeoutError:
                continue
            await write_stdout_message(msg)

    async def pump_local_to_remote() -> None:
        try:
            async for msg in iter_stdin_messages():
                # Forward as-is.
                await remote.send(msg)
        finally:
            local_eof.set()

    log("Starting minimal proxy")
    log("Remote URL:", server_url)
    log("Transport strategy:", transport)

    # Start both pumps.
    tasks = [
        asyncio.create_task(pump_remote_to_local(), name="pump.remote_to_local"),
        asyncio.create_task(pump_local_to_remote(), name="pump.local_to_remote"),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # If any task finishes (EOF, remote close, or exception), shut down.
    for t in done:
        exc = t.exception()
        if exc:
            log("Task failed:", t.get_name(), exc)

    for t in pending:
        t.cancel()

    await remote.close()

    # Best-effort gather.
    await asyncio.gather(*pending, return_exceptions=True)

    log("Proxy stopped")
