#!/usr/bin/env python3
"""Run the market realtime overview skill over plain HTTP."""

from __future__ import annotations

import argparse
import json
import sys

from common import McpRequestError, call_mcp_tool, resolve_wind_session_id


TOOL_NAME = "quote_get_market_realtime_performance"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch realtime market overview data from Wind MCP over HTTP.")
    parser.add_argument("--request-context", default="default")
    parser.add_argument("--session-id", dest="wind_session_id")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--raw", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    wind_session_id = resolve_wind_session_id(args.wind_session_id)
    if not wind_session_id:
        print("Wind session id is required. Pass --session-id or set WIND_SESSION_ID.", file=sys.stderr)
        return 2

    try:
        data, outer = call_mcp_tool(
            tool_name=TOOL_NAME,
            arguments={"request_context": args.request_context or "default"},
            wind_session_id=wind_session_id,
            timeout=args.timeout,
        )
    except McpRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = {
        "tool": TOOL_NAME,
        "meta": {
            "request_context": args.request_context or "default",
        },
        "data": data,
    }
    if args.raw:
        result["raw"] = outer

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
