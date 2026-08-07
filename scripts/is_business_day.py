#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判断今天（或指定日期）是否为 A 股交易日。

数据源：上交所官网「年度休市安排」
  https://www.sse.com.cn/disclosure/dealinstruc/closed/

简化逻辑：
  基准：周一~周五开市，周末休市
  休市表回答两类例外：
    特例1（closed）：原本的周一~周五因放假变成休市
    特例2（open）：  原本的周末变成开市（未来年份如出现则自动生效，2026 没有）
  调休补班等其余信息全部忽略
  1. 取日期所在年份
  2. 查缓存（脚本同目录 wind-business-days.json）有没有当年休市表
  3. 没有 → 抓上交所页面，同时提取休市范围与开市说明 → 写缓存
  4. 判断：在 open（周末开市）→ 交易日；在 closed（工作日休市）→ 非交易日；
     其余遵循基准（周一~周五开市、周末休市）

退出码：0=交易日；1=非交易日；2=拿不到当年休市表（无法判断）
用法：
  python3 is_business_day.py            # 判断今天
  python3 is_business_day.py --date 2026-09-28
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent / "wind-business-days.json"
SSE_URL = "https://www.sse.com.cn/disclosure/dealinstruc/closed/"

# 休市范围：「1月1日（星期四）至1月3日（星期六）休市」
_RANGE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日（[^）]*）至(\d{1,2})月(\d{1,2})日（[^）]*）休市")
# 单日休市：「6月2日（星期一）休市」（周末休市的「为周末休市」不会匹配）
_SINGLE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日（[^）]*）休市")
# 开市说明：「1月5日（星期一）起照常开市」（特例2 可能形如「X月X日（周六）开市」）
_OPEN_RE = re.compile(r"(\d{1,2})月(\d{1,2})日（[^）]*）(?:起照常)?开市")


def fetch_sse_html() -> str:
    proc = subprocess.run(
        [
            "curl", "-sS", "--connect-timeout", "10", "--max-time", "20",
            "-A", "Mozilla/5.0",
            SSE_URL,
        ],
        capture_output=True,
        text=True,
        timeout=25,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"curl 退出码 {proc.returncode}")
    return proc.stdout


def parse_calendar(html: str, year: int) -> dict:
    """从上交所页面提取指定年份的两类例外。

    返回 {"closed": [工作日休市...], "open": [周末开市...]}。
    """
    # 定位「YYYY年休市安排」段落（页面上可能有多年的表格）
    m = re.search(rf"<strong>\s*{year}年休市安排\s*</strong>", html)
    if not m:
        raise RuntimeError(f"页面中没有 {year} 年休市安排")
    section = html[m.end():]
    # 段落到下一个 h2 标题为止
    next_section = re.search(r"<h2", section)
    if next_section:
        section = section[: next_section.start()]

    rows = re.findall(r"<td[^>]*>([^<]+)：</td>\s*<td[^>]*>([^<]+)</td>", section)
    if not rows:
        raise RuntimeError(f"未解析到 {year} 年休市安排表格")

    closed: set[str] = set()
    opened: set[str] = set()
    for _festival, desc in rows:
        for mth1, day1, mth2, day2 in _RANGE_RE.findall(desc):
            start = dt.date(year, int(mth1), int(day1))
            end = dt.date(year, int(mth2), int(day2))
            d = start
            while d <= end:
                if d.weekday() < 5:  # 特例1：周一~周五休市
                    closed.add(d.isoformat())
                d += dt.timedelta(days=1)
        for mth, day in _SINGLE_RE.findall(desc):
            d = dt.date(year, int(mth), int(day))
            if d.weekday() < 5:  # 特例1：周一~周五休市
                closed.add(d.isoformat())
        for mth, day in _OPEN_RE.findall(desc):
            d = dt.date(year, int(mth), int(day))
            if d.weekday() >= 5:  # 特例2：周末开市
                opened.add(d.isoformat())
    return {"closed": sorted(closed), "open": sorted(opened)}


def load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="A 股交易日判断（上交所官方休市安排）")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD，默认今天")
    args = parser.parse_args()

    day = dt.date.fromisoformat(args.date)
    year = str(day.year)

    cache = load_cache()
    if year not in cache:
        try:
            cache[year] = parse_calendar(fetch_sse_html(), day.year)
            save_cache(cache)
        except Exception as exc:
            print(f"无法获取 {year} 年休市表: {exc}", file=sys.stderr)
            return 2

    cal = cache.get(year, {})
    if day.isoformat() in set(cal.get("open", [])):
        return 0  # 特例2：周末开市
    if day.isoformat() in set(cal.get("closed", [])):
        return 1  # 特例1：工作日休市
    if day.weekday() >= 5:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
