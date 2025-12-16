from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import urljoin, urlparse

import aiohttp

from .logging_utils import log


JsonObject = Dict[str, Any]


def _is_jsonrpc_message(obj: object) -> bool:
    """Best-effort JSON-RPC 2.0 shape check.

    We intentionally keep this lightweight to avoid forwarding non-protocol
    JSON blobs (e.g. server-side validation errors) to STDIO clients.
    """

    if not isinstance(obj, dict):
        return False

    if obj.get("jsonrpc") != "2.0":
        return False

    # Request/notification
    if "method" in obj:
        return isinstance(obj.get("method"), str)

    # Response
    if "id" not in obj:
        return False

    msg_id = obj.get("id")
    if not isinstance(msg_id, (str, int)):
        # Some servers use null; MCP SDK rejects it, so we drop it.
        return False

    return "result" in obj or "error" in obj


@dataclass
class SseEvent:
    event: str
    data: str


async def iter_sse_events(content: aiohttp.StreamReader) -> AsyncIterator[SseEvent]:
    """Parse an SSE stream into events.

    Minimal SSE parsing:
    - event: <name>
    - data: <line> (may repeat; joined with '\n')
    - blank line dispatches event
    """

    event_name: str = "message"
    data_lines: list[str] = []

    while True:
        raw = await content.readline()
        if raw == b"":
            # EOF
            if data_lines:
                yield SseEvent(event=event_name, data="\n".join(data_lines))
            return

        line = raw.decode("utf-8", errors="replace")
        line = line.rstrip("\r\n")

        if line == "":
            if data_lines:
                yield SseEvent(event=event_name, data="\n".join(data_lines))
            event_name = "message"
            data_lines = []
            continue

        if line.startswith(":"):
            # comment
            continue

        if line.startswith("event:"):
            event_name = line[len("event:") :].strip() or "message"
            continue

        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
            continue

        # ignore other fields (id:, retry:, etc.)


class SseRemoteTransport:
    """Remote MCP transport compatible with the SDK's SSE pattern.

    - Connect to base SSE URL.
    - Wait for an SSE event named 'endpoint' whose data is the POST URL.
    - Receive JSON-RPC messages via default 'message' SSE events (data is JSON).
    - Send JSON-RPC messages by POSTing to the endpoint.

    No OAuth/auth support.
    """

    def __init__(self, base_url: str, headers: Optional[dict[str, str]] = None):
        self._base_url = base_url
        self._headers = headers or {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._resp: Optional[aiohttp.ClientResponse] = None
        self._endpoint: Optional[str] = None

        self.onmessage: Optional[callable[[JsonObject], None]] = None
        self.onerror: Optional[callable[[Exception], None]] = None
        self.onclose: Optional[callable[[], None]] = None

        self._closed = False
        self._started = asyncio.Event()
        self._endpoint_ready = asyncio.Event()
        self._onclose_called = False

        # Some modern MCP servers do not emit an explicit SSE `endpoint` event.
        # In that case, the SDK typically POSTs back to the same URL.
        self._endpoint_wait_timeout_s = 2.0

    async def wait_ready(self) -> None:
        """Wait until the SSE connection is established (HTTP 2xx + stream opened)."""

        await self._started.wait()

    @property
    def endpoint(self) -> Optional[str]:
        return self._endpoint

    async def start(self) -> None:
        if self._session is not None:
            raise RuntimeError("SseRemoteTransport already started")

        self._session = aiohttp.ClientSession()
        try:
            self._resp = await self._session.get(
                self._base_url,
                headers={"Accept": "text/event-stream", **self._headers},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None),
            )
            self._resp.raise_for_status()

            # Connection is open; allow send() to proceed.
            self._started.set()

            async for event in iter_sse_events(self._resp.content):
                if self._closed:
                    return

                if event.event == "endpoint":
                    self._set_endpoint(event.data)
                    continue

                # Match Node MCP SDK behavior: only default 'message' events are treated as JSON-RPC.
                # Other named events may exist (ping/keepalive/error) and must not be forwarded.
                if event.event != "message":
                    continue

                try:
                    msg = json.loads(event.data)
                except Exception:
                    log("Non-JSON SSE data; ignoring")
                    continue

                if not _is_jsonrpc_message(msg):
                    log("Non-JSON-RPC SSE JSON; ignoring")
                    continue

                if self.onmessage:
                    self.onmessage(msg)

        except Exception as e:
            if self.onerror:
                self.onerror(e)
            raise
        finally:
            await self.close()

    async def _ensure_endpoint(self) -> None:
        if self._endpoint_ready.is_set():
            return

        try:
            await asyncio.wait_for(self._endpoint_ready.wait(), timeout=self._endpoint_wait_timeout_s)
        except asyncio.TimeoutError:
            # Fall back to POSTing to the base URL (common SDK behavior).
            self._endpoint = self._base_url
            self._endpoint_ready.set()
            log("No SSE endpoint event; defaulting POST endpoint to base URL:", self._endpoint)

    def _set_endpoint(self, endpoint_value: str) -> None:
        # Endpoint may be relative. Join against base.
        resolved = urljoin(self._base_url, endpoint_value)
        base = urlparse(self._base_url)
        ep = urlparse(resolved)
        if (base.scheme, base.netloc) != (ep.scheme, ep.netloc):
            raise RuntimeError(f"Endpoint origin mismatch: {resolved}")

        self._endpoint = resolved
        self._endpoint_ready.set()
        log("Received endpoint:", self._endpoint)

    async def send(self, message: JsonObject) -> None:
        if self._closed:
            raise RuntimeError("Transport is closed")

        # Proxy starts start() concurrently with stdin pumping; avoid a race.
        await self._started.wait()

        if not self._session:
            raise RuntimeError("Transport not started")

        await self._ensure_endpoint()
        if not self._endpoint:
            raise RuntimeError("Not connected (no endpoint)")

        try:
            async with self._session.post(
                self._endpoint,
                headers={"Content-Type": "application/json", **self._headers},
                data=json.dumps(message, separators=(",", ":")),
            ) as resp:
                if resp.status < 200 or resp.status >= 300:
                    text = await resp.text()
                    raise RuntimeError(f"POST failed (HTTP {resp.status}): {text}")
                # Drain/close
                await resp.release()
        except Exception as e:
            if self.onerror:
                self.onerror(e)
            raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # Unblock any waiters.
        self._started.set()
        self._endpoint_ready.set()

        try:
            if self._resp is not None:
                self._resp.close()
        finally:
            self._resp = None

        try:
            if self._session is not None:
                await self._session.close()
        finally:
            self._session = None

        if self.onclose and not self._onclose_called:
            self._onclose_called = True
            self.onclose()
