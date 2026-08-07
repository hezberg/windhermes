"""Standalone smoke test for the wind tools (no Hermes needed).

Covers all 20 wind-bridge tools, including the 13 WindClaw MCP tools.

Usage:
    python3 scripts/smoke_wind_tools.py                       # auto session
    WIND_SESSION_ID=<session> python3 scripts/smoke_wind_tools.py
    python3 scripts/smoke_wind_tools.py --session-id <token>
    python3 scripts/smoke_wind_tools.py --tool get_wind_data  # single tool

Session resolution: --session-id > WIND_SESSION_FILE (real-time file)
> WIND_SESSION_ID (env / ~/.hermes/.env) > WindClaw runtime session file.

Plugin resolution: HERMES_HOME/plugins/wind_tool first, then
HERMES_HOME/plugins/wind-bridge, then the repo copy next to this script
(works both inside a profile and from the project checkout).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path


def _env_value(name: str) -> str:
    """Read a var from HERMES_HOME/.env, falling back to the process env."""
    hermes_home = os.environ.get("HERMES_HOME", "").strip() or str(Path.home() / ".hermes")
    try:
        for raw in (Path(hermes_home) / ".env").read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("\"").strip("'")
    except Exception:
        pass
    return os.environ.get(name, "").strip()


def resolve_plugin_init() -> Path:
    """Locate the wind plugin __init__.py across profile / user / repo layouts."""
    script_dir = Path(__file__).resolve().parent
    candidates = []
    hermes_home = os.environ.get("HERMES_HOME", "").strip() or str(Path.home() / ".hermes")
    for plugin_dir in ("wind_tool", "wind-bridge"):
        candidates.append(Path(hermes_home) / "plugins" / plugin_dir / "__init__.py")
    # Repo copy: <project>/plugins/wind-bridge/__init__.py (parent of scripts/)
    candidates.append(script_dir.parent / "plugins" / "wind-bridge" / "__init__.py")
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "找不到 wind 插件 __init__.py。已查找：\n  " + "\n  ".join(str(p) for p in candidates)
    )


def load_plugin():
    path = resolve_plugin_init()
    spec = importlib.util.spec_from_file_location("wind_bridge", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_session(explicit: str = "") -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    session_file = _env_value("WIND_SESSION_FILE")
    if session_file:
        try:
            value = Path(session_file).read_text(encoding="utf-8").strip()
            if value:
                return value
        except Exception:
            pass
    env = _env_value("WIND_SESSION_ID")
    if env:
        return env
    # Test-only fallback: current WindClaw runtime session file
    candidates = sorted(Path.home().glob(".openclaw-windclaw/users/*/openclaw/.windclaw-aigw-session"))
    for path in candidates:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return ""


def _handler_for(module, name: str):
    """Find a tool handler by name (works for both _handle_* and MCP tools)."""
    handler = getattr(module, f"_handle_{name}", None)
    if handler is not None:
        return handler
    for tool in module._TOOLS:
        if tool["name"] == name:
            return tool["handler"]
    raise KeyError(f"未注册的工具: {name}")


def build_cases(session_id: str) -> list[tuple[str, dict]]:
    """20 cases: 4 data/search + 3 quote + 13 WindClaw MCP."""
    return [
        # -- AB1 data / search / research --
        ("get_wind_data", {"query": "贵州茅台最新收盘价和今日涨跌幅", "session_id": session_id}),
        ("document_search", {"query": "贵州茅台最新公告", "session_id": session_id}),
        (
            "wind_financial_reference_content",
            {"query": "贵州茅台投资逻辑分析", "session_id": session_id},
        ),
        (
            "wind_web_search",
            {"query": "贵州茅台", "freshness": "最近一周", "count": "3", "session_id": session_id},
        ),
        # -- quote realtime --
        (
            "quote_get_stock_realtime_performance",
            {"windcode": "600519.SH", "session_id": session_id},
        ),
        (
            "quote_get_sector_realtime_performance",
            {"indexcode": "886063.WI", "session_id": session_id},
        ),
        (
            "quote_get_market_realtime_performance",
            {"market_type": "1", "session_id": session_id},
        ),
        # -- WindClaw MCP 13 --
        (
            "wechat_extract_article_content",
            {"url": "https://mp.weixin.qq.com/s/IIothtmpCfDOyrT_5RnrFw", "session_id": session_id},
        ),
        (
            "wechat_search_articles_by_account",
            {"weixinIdOrName": "rmrbwx", "limit": 2, "session_id": session_id},
        ),
        ("stock_get_market_realtime_analysis", {"session_id": session_id}),
        (
            "stock_get_sector_realtime_analysis",
            {"query": "886063.WI", "session_id": session_id},
        ),
        (
            "stock_get_industry_research",
            {"keyword": "光模块", "session_id": session_id},
        ),
        (
            "stock_get_company_profile",
            {"windCode": "002384.SZ", "session_id": session_id},
        ),
        (
            "stock_get_company_finance_analysis",
            {"windcode": "002384.SZ", "session_id": session_id},
        ),
        (
            "stock_get_company_earnings_estimate",
            {"windCode": "002384.SZ", "session_id": session_id},
        ),
        (
            "stock_get_company_valuation",
            {"windCode": "002384.SZ", "session_id": session_id},
        ),
        (
            "stock_get_company_updates",
            {"windCode": "002384.SZ", "session_id": session_id},
        ),
        (
            "stock_get_money_flow_analysis",
            {"windCode": "002384.SZ", "session_id": session_id},
        ),
        (
            "stock_get_technical_analysis",
            {"windCode": "002384.SZ", "session_id": session_id},
        ),
        (
            "stock_get_realtime_analysis",
            {"query": "002384.SZ", "session_id": session_id},
        ),
    ]


async def run_case(module, name: str, args: dict, timeout: float) -> str:
    try:
        output = await asyncio.wait_for(
            _handler_for(module, name)(args),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return f"错误：超时（>{timeout:.0f}s 无响应）"
    except Exception as exc:  # noqa: BLE001
        output = f"EXCEPTION: {type(exc).__name__}: {exc}"
    return output


async def main() -> int:
    parser = argparse.ArgumentParser(description="Wind 工具冒烟测试（20 个工具）")
    parser.add_argument("--session-id", default="", help="万得会话 ID")
    parser.add_argument("--tool", default="", help="只测单个工具名（默认全部 20 个）")
    parser.add_argument("--max-chars", type=int, default=700, help="每个工具输出截断长度")
    parser.add_argument("--timeout", type=float, default=60.0, help="每个工具超时秒数（默认 60）")
    args = parser.parse_args()

    module = load_plugin()
    session_id = load_session(args.session_id)
    if not session_id:
        print("错误：找不到 session。请设置 WIND_SESSION_ID / WIND_SESSION_FILE，或用 --session-id 传入。", file=sys.stderr)
        return 2
    print(f"session: len={len(session_id)} prefix={session_id[:4]}****")

    cases = build_cases(session_id)
    if args.tool:
        cases = [c for c in cases if c[0] == args.tool]
        if not cases:
            print(f"错误：未知工具 {args.tool}", file=sys.stderr)
            return 2

    failed = 0
    total = len(cases)
    for i, (name, case_args) in enumerate(cases, 1):
        started = time.monotonic()
        print(f"\n[{i:>2}/{total}] {name} …", flush=True)
        output = await run_case(module, name, case_args, args.timeout)
        elapsed = time.monotonic() - started
        ok = not (output.startswith("错误：") or output.startswith("EXCEPTION"))
        mark = "✓" if ok else "✗"
        print(f"    {mark} {elapsed:5.1f}s", flush=True)
        print(output[: args.max_chars])
        if output.startswith("错误：") or output.startswith("EXCEPTION"):
            failed += 1

    print(f"\n结果：{len(cases) - failed}/{len(cases)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
