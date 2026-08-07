#!/usr/bin/env python3
"""查询万得剩余积分（总积分 / 付费积分 / 赠送积分）。

用法：
    wind_balance                       # 用 WIND_SESSION_ID / WIND_SESSION_FILE 鉴权
    wind_balance --session-id <token>  # 显式传 session id
    wind_balance --raw                 # 输出原始 JSON

鉴权优先级：--session-id 参数 > WIND_SESSION_FILE（实时读文件）> WIND_SESSION_ID（环境变量 / ~/.hermes/.env）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_ORIGIN = "https://m.wind.com.cn"
BALANCE_PATH = "/wstock_business_service/point/balance"


def load_env_value(key: str) -> str:
    env_file = Path.home() / ".hermes" / ".env"
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip("\"").strip("'")
    except Exception:
        pass
    return ""


def resolve_session(explicit: str) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    session_file = os.environ.get("WIND_SESSION_FILE", "").strip() or load_env_value("WIND_SESSION_FILE")
    if session_file:
        try:
            value = Path(session_file).read_text(encoding="utf-8").strip()
            if value:
                return value
        except Exception:
            pass
    env = os.environ.get("WIND_SESSION_ID", "").strip() or load_env_value("WIND_SESSION_ID")
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="查询万得剩余积分")
    parser.add_argument("--session-id", default="", help="万得会话 ID（可选）")
    parser.add_argument("--raw", action="store_true", help="输出原始 JSON")
    parser.add_argument("--origin", default=os.environ.get("WIND_POINTS_API_ORIGIN", DEFAULT_ORIGIN), help="接口域名")
    args = parser.parse_args()

    session_id = resolve_session(args.session_id)
    if not session_id:
        print("错误：缺少 Wind session id。请用 --session-id 传入，或设置 WIND_SESSION_ID / WIND_SESSION_FILE。", file=sys.stderr)
        return 2

    url = args.origin.rstrip("/") + BALANCE_PATH
    req = urllib.request.Request(
        url,
        headers={"wind.sessionid": session_id, "windsessionid": session_id},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        print(f"错误：请求失败 - {exc}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(raw)
    except Exception:
        print(f"错误：响应不是有效 JSON：{raw[:200]}", file=sys.stderr)
        return 1

    if payload.get("code") != 200:
        print(f"错误：{payload.get('message') or payload}", file=sys.stderr)
        return 1

    data = payload.get("data") or {}
    if args.raw:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    total = data.get("totalBalance")
    paid = data.get("paidBalance")
    temp = data.get("tempBalance")
    print(f"总积分：{total}")
    print(f"付费积分：{paid}")
    print(f"赠送/临时积分：{temp}")
    try:
        ext = json.loads(data.get("extendInfo") or "{}")
        tips = ext.get("bonusTips")
        if tips:
            print(f"提示：{tips}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
