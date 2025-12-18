from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import aiohttp

from .logging_utils import log
from .sse_transport import _is_jsonrpc_message, iter_sse_events


JsonObject = Dict[str, Any]

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0  # seconds


class StreamableHttpRemoteTransport:
    """Very small HTTP transport for MCP JSON-RPC.

    This is intentionally minimal and aims to cover the most common case:
    - Client sends JSON-RPC via HTTP POST to the provided URL
    - Server responds with JSON (single object) or JSONL/NDJSON (one JSON per line)

    Note: This does not implement OAuth flows.
    """

    def __init__(self, url: str, headers: Optional[dict[str, str]] = None):
        self._url = url
        self._headers = headers or {}

        self._session: Optional[aiohttp.ClientSession] = None
        self._closed = False
        self._started = asyncio.Event()
        self._closed_event = asyncio.Event()
        self._onclose_called = False

        self.onmessage: Optional[callable[[JsonObject], None]] = None
        self.onerror: Optional[callable[[Exception], None]] = None
        self.onclose: Optional[callable[[], None]] = None

    async def wait_ready(self) -> None:
        await self._started.wait()

    def _create_connector(self) -> aiohttp.TCPConnector:
        """Create a TCP connector with keepalive enabled."""
        return aiohttp.TCPConnector(
            keepalive_timeout=60,  # Keep connections alive for 60 seconds
            enable_cleanup_closed=True,
            force_close=False,
        )

    async def start(self) -> None:
        if self._session is not None:
            raise RuntimeError("StreamableHttpRemoteTransport already started")

        self._session = aiohttp.ClientSession(connector=self._create_connector())
        self._started.set()

        # Keep the start() task alive until close().
        await self._closed_event.wait()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure we have a valid session, recreating if needed."""
        if self._session is None or self._session.closed:
            if self._closed:
                raise RuntimeError("Transport is closed")
            log("Recreating HTTP session")
            self._session = aiohttp.ClientSession(connector=self._create_connector())
        return self._session

    async def send(self, message: JsonObject) -> None:
        if self._closed:
            raise RuntimeError("Transport is closed")

        await self._started.wait()

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._ensure_session()

                async with session.post(
                    self._url,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, application/x-ndjson, application/jsonl, text/event-stream",
                        **self._headers,
                    },
                    data=json.dumps(message, separators=(",", ":")),
                    timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None),
                ) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        text = await resp.text()
                        raise RuntimeError(f"HTTP POST failed (HTTP {resp.status}): {text}")

                    await self._drain_response(resp)
                    return  # Success

            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                last_error = e
                if self._closed:
                    break

                # Retryable error
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    log(f"HTTP request failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                    # Close and recreate session on connection errors
                    if self._session and not self._session.closed:
                        await self._session.close()
                        self._session = None
                else:
                    log(f"HTTP request failed after {MAX_RETRIES} attempts: {e}")

            except Exception as e:
                # Non-retryable error
                last_error = e
                break

        if last_error:
            if self.onerror:
                self.onerror(last_error)
            raise last_error

    async def _drain_response(self, resp: aiohttp.ClientResponse) -> None:
        """Parse JSON or JSONL from response and forward JSON-RPC messages."""

        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in content_type:
            # Some servers stream responses using SSE framing even for the "HTTP" transport.
            async for event in iter_sse_events(resp.content):
                if event.event != "message":
                    continue
                try:
                    obj = json.loads(event.data)
                except Exception:
                    log("Non-JSON SSE data in HTTP response; ignoring")
                    continue
                self._handle_message_obj(obj)
            await resp.release()
            return

        # Prefer streaming, but also handle a single JSON object without newlines.
        buffer = b""

        async for chunk in resp.content.iter_chunked(8192):
            if not chunk:
                continue
            buffer += chunk

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.rstrip(b"\r")
                self._handle_json_line(line)

        if buffer.strip():
            # Try parse the remaining bytes as one JSON object.
            self._handle_json_bytes(buffer)

        # Ensure connection is fully drained.
        await resp.release()

    def _handle_json_line(self, line: bytes) -> None:
        if not line.strip():
            return
        self._handle_json_bytes(line)

    def _handle_json_bytes(self, payload: bytes) -> None:
        try:
            obj = json.loads(payload.decode("utf-8"))
        except Exception:
            # Not JSON; ignore.
            return

        if isinstance(obj, list):
            for item in obj:
                self._handle_message_obj(item)
            return

        self._handle_message_obj(obj)

    def _handle_message_obj(self, obj: object) -> None:
        if not _is_jsonrpc_message(obj):
            return
        if self.onmessage:
            self.onmessage(obj)  # type: ignore[arg-type]

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._closed_event.set()
        self._started.set()

        try:
            if self._session is not None:
                await self._session.close()
        finally:
            self._session = None

        if self.onclose and not self._onclose_called:
            self._onclose_called = True
            self.onclose()
