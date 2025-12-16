from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

import aiohttp

from .http_transport import StreamableHttpRemoteTransport
from .logging_utils import log
from .sse_transport import SseRemoteTransport


JsonObject = Dict[str, Any]
TransportStrategy = Literal["sse-only", "http-only", "sse-first", "http-first"]


def _should_fallback(exc: BaseException) -> bool:
    if isinstance(exc, aiohttp.ClientResponseError):
        return exc.status in (404, 405)

    msg = str(exc)
    return (
        " 404" in msg
        or "Not Found" in msg
        or " 405" in msg
        or "Method Not Allowed" in msg
        or "HTTP 404" in msg
        or "HTTP 405" in msg
    )


@dataclass
class _Active:
    kind: Literal["sse", "http"]
    transport: Any


class RemoteTransport:
    """A small wrapper that mimics mcp-remote's transport strategies.

    Node mcp-remote defaults to http-first and falls back on 404/405.
    Our Python project originally implemented SSE-only; this wrapper makes it
    much more compatible with modern MCP servers.
    """

    def __init__(self, url: str, headers: Optional[dict[str, str]] = None, transport: TransportStrategy = "http-first"):
        self._url = url
        self._headers = headers or {}
        self._strategy: TransportStrategy = transport

        self.onmessage: Optional[callable[[JsonObject], None]] = None
        self.onerror: Optional[callable[[Exception], None]] = None
        self.onclose: Optional[callable[[], None]] = None

        self._closed = False
        self._switch_lock = asyncio.Lock()
        self._switching = False
        self._runner_task: Optional[asyncio.Task[None]] = None

        first_kind: Literal["sse", "http"]
        if transport in ("sse-only", "sse-first"):
            first_kind = "sse"
        else:
            first_kind = "http"

        self._active = self._make_active(first_kind)

    def _make_active(self, kind: Literal["sse", "http"]) -> _Active:
        if kind == "sse":
            t = SseRemoteTransport(self._url, headers=self._headers)
        else:
            t = StreamableHttpRemoteTransport(self._url, headers=self._headers)

        t.onmessage = lambda msg: self.onmessage(msg) if self.onmessage else None
        t.onerror = self._handle_underlying_error
        t.onclose = self._handle_underlying_close

        return _Active(kind=kind, transport=t)

    def _can_fallback(self) -> bool:
        return self._strategy in ("http-first", "sse-first")

    def _other_kind(self) -> Literal["sse", "http"]:
        return "sse" if self._active.kind == "http" else "http"

    def _handle_underlying_error(self, e: Exception) -> None:
        if self.onerror:
            self.onerror(e)

    def _handle_underlying_close(self) -> None:
        # During a transport switch we don't want to signal the proxy to stop.
        if self._switching:
            return
        if self.onclose:
            self.onclose()

    async def wait_ready(self) -> None:
        await self._active.transport.wait_ready()

    async def start_background(self) -> None:
        """Start the underlying transport in a background task.

        This mirrors Node's behavior where the transport runs concurrently with
        STDIO pumping.
        """

        if self._runner_task is not None:
            return

        await self._start_active_runner_with_fallback()

    async def _start_active_runner_with_fallback(self) -> None:
        """Start current transport and apply fallback if it fails immediately."""

        while True:
            self._runner_task = asyncio.create_task(self._active.transport.start(), name=f"remote.{self._active.kind}.start")

            ready = asyncio.create_task(self._active.transport.wait_ready(), name=f"remote.{self._active.kind}.ready")
            done, pending = await asyncio.wait({self._runner_task, ready}, return_when=asyncio.FIRST_COMPLETED)

            # If the runner failed immediately, consider fallback.
            if self._runner_task in done and self._runner_task.exception() is not None:
                exc = self._runner_task.exception()
                assert exc is not None
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)

                if self._closed:
                    return

                if self._can_fallback() and _should_fallback(exc):
                    log(f"Transport {self._active.kind} failed on start; switching:", exc)
                    await self._switch_to(self._other_kind())
                    continue

                raise exc

            # Otherwise we are ready (or the transport start exited cleanly).
            # Keep the runner task alive; only cancel/gather the helper task.
            to_cancel: list[asyncio.Task[Any]] = []
            for p in pending:
                if p is not self._runner_task:
                    p.cancel()
                    to_cancel.append(p)
            if to_cancel:
                await asyncio.gather(*to_cancel, return_exceptions=True)
            return

    async def start(self) -> None:
        """Compatibility: run background transport until closed."""

        await self.start_background()
        if self._runner_task is not None:
            await self._runner_task

    async def _switch_to(self, new_kind: Literal["sse", "http"]) -> None:
        async with self._switch_lock:
            if self._closed:
                return
            if self._active.kind == new_kind:
                return

            self._switching = True
            try:
                old = self._active
                old_task = self._runner_task

                # Closing the old transport causes its runner task to unwind.
                await old.transport.close()
                if old_task is not None:
                    await asyncio.gather(old_task, return_exceptions=True)

                self._active = self._make_active(new_kind)
                self._runner_task = None
                await self._start_active_runner_with_fallback()
            finally:
                self._switching = False

    async def send(self, message: JsonObject) -> None:
        if self._closed:
            raise RuntimeError("Transport is closed")

        # Ensure there's a running transport task.
        await self.start_background()

        try:
            await self._active.transport.send(message)
        except Exception as e:
            if self._closed:
                raise
            if self._can_fallback() and _should_fallback(e):
                log(f"Send failed on {self._active.kind} with fallback-eligible error; switching:", e)
                await self._switch_to(self._other_kind())
                await self._active.transport.send(message)
                return
            raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        task = self._runner_task
        await self._active.transport.close()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        self._runner_task = None
