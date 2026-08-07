#!/usr/bin/env python3
"""Run the stock realtime insight skill over plain HTTP."""

from __future__ import annotations

import argparse
import json
import re
import sys

from common import McpRequestError, call_mcp_tool, resolve_wind_session_id


TOOL_NAME = "quote_get_stock_realtime_performance"
WINDCODE_PATTERNS = (
    re.compile(r"\b\d{6}\.(?:SH|SZ|BJ)\b", re.IGNORECASE),
    re.compile(r"\b\d{4,6}\.HK\b", re.IGNORECASE),
    re.compile(r"\b[A-Z][A-Z0-9-]{0,9}\.(?:O|N|A|K|L|P)\b", re.IGNORECASE),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch realtime stock insight data from Wind MCP over HTTP.")
    parser.add_argument("--security", required=True)
    parser.add_argument("--session-id", dest="wind_session_id")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--raw", action="store_true")
    return parser.parse_args(argv)


def extract_windcode(text: str) -> str | None:
    candidate = text.strip().upper()
    for pattern in WINDCODE_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(0).upper()
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    windcode = extract_windcode(args.security)
    if not windcode:
        print(
            "A standard windcode is required, for example 600519.SH, 0700.HK, or AAPL.O.",
            file=sys.stderr,
        )
        return 2

    wind_session_id = resolve_wind_session_id(args.wind_session_id)
    if not wind_session_id:
        print("Wind session id is required. Pass --session-id or set WIND_SESSION_ID.", file=sys.stderr)
        return 2

    try:
        data, outer = call_mcp_tool(
            tool_name=TOOL_NAME,
            arguments={"windcode": windcode},
            wind_session_id=wind_session_id,
            timeout=args.timeout,
        )
    except McpRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = {
        "tool": TOOL_NAME,
        "meta": {
            "windcode": windcode,
            "input_security": args.security,
        },
        "data": data,
    }
    if args.raw:
        result["raw"] = outer

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
