#!/usr/bin/env python3
"""查询万得积分流水（分页）。

用法：
    wind_balance_log                       # 第 1 页，每页 20 条
    wind_balance_log --page 2 --page-size 10
    wind_balance_log --session-id <token>  # 显式传 session id
    wind_balance_log --raw                 # 输出原始 JSON

鉴权优先级：--session-id 参数 > WIND_SESSION_FILE（实时读文件）> WIND_SESSION_ID（环境变量 / ~/.hermes/.env）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_ORIGIN = "https://m.wind.com.cn"
LOGS_PATH = "/wstock_business_service/point/logs"


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


TYPE_NAMES = {
    1: "充值",
    2: "赠送",
    3: "扣减",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="查询万得积分流水")
    parser.add_argument("--session-id", default="", help="万得会话 ID（可选）")
    parser.add_argument("--page", type=int, default=1, help="页码，默认 1")
    parser.add_argument("--page-size", type=int, default=20, help="每页条数，默认 20")
    parser.add_argument("--raw", action="store_true", help="输出原始 JSON")
    parser.add_argument("--origin", default=os.environ.get("WIND_POINTS_API_ORIGIN", DEFAULT_ORIGIN), help="接口域名")
    args = parser.parse_args()

    session_id = resolve_session(args.session_id)
    if not session_id:
        print("错误：缺少 Wind session id。请用 --session-id 传入，或设置 WIND_SESSION_ID / WIND_SESSION_FILE。", file=sys.stderr)
        return 2

    url = args.origin.rstrip("/") + LOGS_PATH
    url += "?" + urllib.parse.urlencode({"page": args.page, "pageSize": args.page_size})
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

    rows = data.get("data") or []
    total = data.get("total", 0)
    total_page = data.get("totalPage", 1)
    page_no = data.get("pageNo", args.page)
    print(f"共 {total} 条 | 第 {page_no}/{total_page} 页")
    if not rows:
        print("（暂无流水记录）")
        return 0
    for row in rows:
        point = row.get("point")
        point_str = f"{point:+d}" if isinstance(point, int) else str(point)
        asset = row.get("assetType") or ""
        remark = row.get("remark") or ""
        create_time = row.get("createTime") or ""
        type_name = TYPE_NAMES.get(row.get("type"), f"type{row.get('type')}")
        print(f"{create_time} | {point_str} | {type_name} | {asset} | {remark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
