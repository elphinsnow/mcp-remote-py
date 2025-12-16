from __future__ import annotations

import argparse
import asyncio
from typing import Dict

from .logging_utils import log
from .proxy import run_proxy
from .stdio_jsonl import parse_header_arg


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mcp-remote-py",
        description="Minimal MCP STDIO <-> remote SSE proxy (no auth)",
    )
    p.add_argument("server_url", help="Remote MCP SSE base URL (e.g. https://host/sse)")
    p.add_argument(
        "--header",
        action="append",
        default=[],
        help="Custom header to send to remote (repeatable), format: 'Name: value'",
    )
    p.add_argument(
        "--transport",
        default="http-first",
        choices=["sse-only", "http-only", "sse-first", "http-first"],
        help="Transport strategy (default: http-first)",
    )
    return p


def main() -> None:
    args = build_arg_parser().parse_args()

    headers: Dict[str, str] = {}
    for raw in args.header:
        parsed = parse_header_arg(raw)
        if not parsed:
            log("Ignoring invalid --header:", raw)
            continue
        k, v = parsed
        headers[k] = v

    try:
        asyncio.run(run_proxy(args.server_url, headers=headers, transport=args.transport))
    except KeyboardInterrupt:
        # Clean exit.
        return


if __name__ == "__main__":
    main()
