#!/usr/bin/env python3
"""WindAgent 交互式安装向导（Hermes setup 风格）。

用法:
    python3 scripts/windagent_setup.py            # 交互引导
    python3 scripts/windagent_setup.py --session-id <tok>
    python3 scripts/windagent_setup.py --force    # profile 已存在时重建
    python3 scripts/windagent_setup.py --yes      # 全部接受默认值
    HERMES_NONINTERACTIVE=1 python3 scripts/windagent_setup.py

交互风格对齐 Hermes 自己的 setup 向导：分节标题、黄色 prompt + 默认值、
Y/n 确认、token 遮罩输入、分级彩色输出。
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

# ── ANSI 配色（与 Hermes 一致）──────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"


def _color(text: str, *codes: str) -> str:
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb" or not sys.stdout.isatty():
        return text
    return "".join(codes) + text + RESET


def print_header(title: str) -> None:
    print()
    print(_color(f"  {title}", BOLD, YELLOW))
    print(_color(f"  {'─' * min(len(title) + 2, 60)}", DIM))


def print_info(text: str) -> None:
    print(_color(f"  {text}", DIM))


def print_success(text: str) -> None:
    print(_color(f"✓ {text}", GREEN))


def print_warning(text: str) -> None:
    print(_color(f"⚠ {text}", YELLOW))


def print_error(text: str) -> None:
    print(_color(f"✗ {text}", RED))


def is_noninteractive() -> bool:
    return os.environ.get("HERMES_NONINTERACTIVE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def prompt(question: str, default: str | None = None) -> str:
    """黄色 prompt + 默认值。回车取默认，Ctrl+C/EOF 返回默认或空。"""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(_color(f"  {question}{suffix}: ", YELLOW)).strip()
        return value or default or ""
    except (KeyboardInterrupt, EOFError):
        print()
        return default or ""


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Y/n 确认。非交互时回退默认值。"""
    if is_noninteractive():
        return default
    hint = "Y/n" if default else "y/N"
    while True:
        value = prompt(f"{question} ({hint})")
        if not value:
            return default
        if value.lower() in {"y", "yes"}:
            return True
        if value.lower() in {"n", "no"}:
            return False
        print_error("请输入 y 或 n")


def prompt_secret(question: str) -> str:
    """遮罩输入 token。"""
    try:
        return getpass.getpass(_color(f"  {question}: ", YELLOW)).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return ""


# ── 路径与常量 ───────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent.parent
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
HERMES_ROOT = Path.home() / ".hermes"
PROFILE_NAME = "windagent"
PROFILE_DIR = HERMES_ROOT / "profiles" / PROFILE_NAME
INSTALL_SCRIPT = SCRIPT_DIR / "install.sh"


def find_windclaw_session_files() -> list[Path]:
    return sorted(
        Path.home().glob(".openclaw-windclaw/users/*/openclaw/.windclaw-aigw-session")
    )


def detect_session() -> str:
    for path in find_windclaw_session_files():
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except Exception:
            continue
    return ""


def check_hermes() -> str:
    """返回 Hermes 版本行，失败返回空。"""
    try:
        out = subprocess.run(
            [HERMES_BIN, "version"],
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode == 0:
            return out.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return ""


def profile_exists() -> bool:
    return PROFILE_DIR.is_dir()


def run_install(session_id: str, force: bool) -> int:
    """调用 install.sh（静默安装引擎），实时转发输出。"""
    cmd = [str(INSTALL_SCRIPT)]
    if force:
        cmd.append("--force")
    if session_id:
        cmd += ["--session-id", session_id]
    print()
    print_header("执行安装")
    proc = subprocess.run(cmd)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="WindAgent 交互式安装向导")
    parser.add_argument("--session-id", default="", help="万得会话 ID（跳过交互）")
    parser.add_argument("--force", action="store_true", help="profile 已存在时重建")
    parser.add_argument("--yes", action="store_true", help="全部接受默认值")
    args = parser.parse_args()

    session_id = args.session_id
    force = args.force

    # ── 欢迎 ──────────────────────────────────────────────────────────────
    print()
    print(_color("  ══════════════════════════════════════════════════", CYAN, BOLD))
    print(_color("   WindAgent — 把 Hermes 打造成 Wind 金融客户端", CYAN, BOLD))
    print(_color("  ══════════════════════════════════════════════════", CYAN, BOLD))

    # ── 1. 检查 Hermes ────────────────────────────────────────────────────
    print_header("1. 检查环境")
    version = check_hermes()
    if not version:
        print_error(f"未找到 Hermes（{HERMES_BIN}）。请先安装 Hermes Agent。")
        return 1
    print_success(version)

    # ── 2. Profile 状态 ───────────────────────────────────────────────────
    print_header("2. Profile")
    if profile_exists():
        if args.yes:
            print_info(f"保留现有 profile '{PROFILE_NAME}'（--yes 接受默认值）")
        elif prompt_yes_no(
            f"profile '{PROFILE_NAME}' 已存在，是否删除重建？", default=False
        ):
            force = True
            print_info("将删除并重建 profile")
        else:
            print_info(f"保留现有 profile '{PROFILE_NAME}'，继续安装")
    else:
        print_info(f"将创建全新 profile '{PROFILE_NAME}'")

    # ── 3. Session ID ─────────────────────────────────────────────────────
    print_header("3. Wind session")
    if not session_id:
        detected = detect_session()
        if detected:
            if args.yes:
                session_id = detected
            else:
                print_info(f"检测到 WindClaw 会话文件：{find_windclaw_session_files()[0]}")
                if prompt_yes_no("使用检测到的 session？", default=True):
                    session_id = detected
        if not session_id and not args.yes:
            session_id = prompt_secret("粘贴 WIND_SESSION_ID（回车跳过）")

    if session_id:
        print_success(f"session 已就绪（长度 {len(session_id)}）")
    else:
        print_warning("未提供 session，稍后可手动更新 ~/.hermes/profiles/windagent/.env")

    # ── 4. 确认并安装 ────────────────────────────────────────────────────
    if not args.yes:
        proceed = prompt_yes_no("开始安装？", default=True)
        if not proceed:
            print_warning("已取消")
            return 0

    rc = run_install(session_id, force)

    # ── 5. 完成 ───────────────────────────────────────────────────────────
    print_header("5. 完成")
    if rc == 0:
        print_success("安装完成")
        print()
        print_info("下一步：")
        print_info(f"  hermes -p {PROFILE_NAME} chat")
        print_info(f"  hermes -p {PROFILE_NAME} skills list --enabled-only")
        print_info(f"  hermes -p {PROFILE_NAME} plugins list")
    else:
        print_error(f"安装未完全成功（退出码 {rc}），请查看上方提示。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
