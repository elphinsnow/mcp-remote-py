from __future__ import annotations

import asyncio
import pytest

from mcp_remote_py.sse_transport import iter_sse_events


class _FakeContent:
    def __init__(self, lines: list[bytes]):
        self._lines = lines
        self._i = 0

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if self._i >= len(self._lines):
            return b""
        v = self._lines[self._i]
        self._i += 1
        return v


@pytest.mark.asyncio
async def test_iter_sse_events_endpoint_then_message():
    content = _FakeContent(
        [
            b"event: endpoint\n",
            b"data: /messages\n",
            b"\n",
            b"data: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{}}\n",
            b"\n",
        ]
    )

    events = []
    async for ev in iter_sse_events(content):
        events.append((ev.event, ev.data))

    assert events == [
        ("endpoint", "/messages"),
        ("message", '{"jsonrpc":"2.0","id":1,"result":{}}'),
    ]
