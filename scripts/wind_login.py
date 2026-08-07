#!/usr/bin/env python3
"""WindClaw 手机号 + 验证码登录 → 获取 session id（独立脚本，不依赖 WindClaw）。

逆向自 WindClaw app.asar 的 Visa 认证流程：
  1. POST /wstock_business_service/visa/sendVerifyCode   发验证码
  2. POST /wstock_business_service/visa/registerAndLogin 手机号+验证码登录
  3. 从响应 authData.sessionID 拿到 session id

用法:
    python3 scripts/wind_login.py send <手机号>                 # 发验证码
    python3 scripts/wind_login.py login <手机号> <验证码>        # 登录，打印 session
    python3 scripts/wind_login.py login <手机号> <验证码> --save # 同时写入 profile .env
    python3 scripts/wind_login.py login <手机号> <验证码> --smoke # 登录后跑冒烟测试

只依赖标准库（urllib），任何机器可跑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://m.wind.com.cn/wstock_business_service"
APP_VERSION = "22.30"
TERMINAL_TYPE = "10060" if sys.platform == "darwin" else "10062"
LOGIN_MODE_PC = 0
VERIFY_CODE_LENGTH = 6
TEMPLATE_CODE = "SMS_DEFAULT_001"
SOURCE_NAME = "WindClaw-Mac" if sys.platform == "darwin" else "WindClaw"
ISP_TYPE = "4"


# ── 工具函数（对齐 WindClaw 源码）────────────────────────────────────────

def _digits(value: str) -> str:
    """Xn(): 只保留数字。"""
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _valid_phone(phone: str) -> bool:
    return len(_digits(phone)) == 11


def _valid_code(code: str) -> bool:
    return len(_digits(code)) == VERIFY_CODE_LENGTH


def _verify_code_type(purpose: str) -> str:
    """q5(): login=00, reset=03, register=05。"""
    return {"login": "00", "reset": "03", "register": "05"}.get(purpose, "00")


def _local_ipv4() -> str:
    """H5(): 第一个非 internal IPv4。"""
    try:
        for addrs in socket.getaddrinfo(socket.gethostname(), None):
            ip = addrs[4][0]
            if ":" not in ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    # 兜底：UDP 连公网 DNS 探测出口 IP（不真正发包）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def _win_hardware() -> tuple[str, str, str]:
    """Bg(): Windows 用 PowerShell 采集 CPUID/DiskID/DiskSN。非 Windows 返回空。"""
    if sys.platform != "win32":
        return "", "", ""
    cmds = [
        "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty ProcessorId)",
        "(Get-CimInstance Win32_DiskDrive | Select-Object -First 1 -ExpandProperty DeviceID)",
        "(Get-CimInstance Win32_DiskDrive | Select-Object -First 1 -ExpandProperty SerialNumber)",
    ]
    outs = []
    for cmd in cmds:
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=3,
            )
            outs.append(r.stdout.strip())
        except Exception:
            outs.append("")
    return outs[0], outs[1], outs[2]


def device_context() -> dict:
    """G5(): 设备上下文（指纹 + otherInfo + fromIP）。"""
    hostname = socket.gethostname().strip()
    cpuid, disk_id, disk_sn = _win_hardware()
    from_ip = _local_ipv4()
    # WindClaw: deviceFingerprint = MD5([host,cpuid,diskid,disksn].filter.join("|"))
    fingerprint_raw = "|".join(x for x in (hostname, cpuid, disk_id, disk_sn) if x)
    fingerprint = hashlib.md5(fingerprint_raw.encode()).hexdigest() if fingerprint_raw else ""
    other_info = "|".join(
        [
            f"ComputerName:{hostname}",
            f"DiskID:{disk_id}",
            f"DiskSN:{disk_sn}",
            f"CPUID:{cpuid}",
            f"Version:{APP_VERSION}",
            f"ISPType:{ISP_TYPE}",
        ]
    )
    return {
        "deviceFingerprint": fingerprint,
        "otherInfo": other_info,
        "fromIP": from_ip,
        "hostname": hostname,
    }


def _auth_config() -> dict:
    """eo(): 认证配置。"""
    return {
        "baseUrl": os.environ.get("CLAWX_VISA_AUTH_BASE_URL", BASE_URL).strip(),
        "appVersion": APP_VERSION,
        "terminalType": TERMINAL_TYPE,
        "verifyCodeLength": VERIFY_CODE_LENGTH,
        "templateCode": TEMPLATE_CODE,
        "loginModePc": LOGIN_MODE_PC,
        "defaultCountryCode": "86",
    }


def _post(path: str, body: dict) -> dict:
    """aw(): POST JSON 到 Visa 接口。"""
    cfg = _auth_config()
    url = cfg["baseUrl"].rstrip("/") + path
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw[:200]}") from exc
    except Exception as exc:
        raise RuntimeError(f"请求失败: {exc}") from exc
    try:
        return json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"响应不是有效 JSON: {raw[:200]}") from exc


# ── 登录流程 ─────────────────────────────────────────────────────────────

def send_code(phone: str, purpose: str = "login") -> dict:
    """发送短信验证码。"""
    if not _valid_phone(phone):
        raise RuntimeError("手机号格式错误（需 11 位数字）")
    cfg = _auth_config()
    phone_digits = _digits(phone)
    body = {
        "verifyCodeType": _verify_code_type(purpose),
        "verifyCodeLength": cfg["verifyCodeLength"],
        "sendType": 1,
        "sendTo": f"+86{phone_digits}",
        "terminalType": cfg["terminalType"],
        "templateCode": cfg["templateCode"],
        "templateParams": json.dumps({"expiredMinutes": 30}),
        "captchaParams": "",
        "extraInfo": "",
    }
    resp = _post("/visa/sendVerifyCode", body)
    if resp.get("code") == 200 and resp.get("data", {}).get("retCode") == 1:
        return {"success": True, "countdownSeconds": 60, "codeLength": cfg["verifyCodeLength"]}
    msg = resp.get("message") or resp.get("data", {}).get("message") or "发送失败"
    raise RuntimeError(f"发送验证码失败: {msg}")


def login_with_code(phone: str, code: str) -> dict:
    """手机号 + 验证码登录，返回 {sessionId, userInfo, raw}。"""
    if not _valid_phone(phone):
        raise RuntimeError("手机号格式错误（需 11 位数字）")
    if not _valid_code(code):
        raise RuntimeError(f"验证码格式错误（需 {VERIFY_CODE_LENGTH} 位数字）")

    cfg = _auth_config()
    phone_digits = _digits(phone)
    dev = device_context()
    other_info = f"{dev['otherInfo']}|Source:{SOURCE_NAME}|specificusertype:210"
    body = {
        "verifyMode": 1,
        "loginName": phone_digits,
        "intAreaCode": "86",
        "verifyCode": _digits(code),
        "deviceFingerprint": dev["deviceFingerprint"],
        "terminalType": cfg["terminalType"],
        "loginMode": cfg["loginModePc"],
        "otherInfo": other_info,
        "fromIP": dev["fromIP"],
    }
    resp = _post("/visa/registerAndLogin", body)

    if resp.get("code") == 200 and resp.get("data", {}).get("retvalue") == 0:
        session_id = (resp.get("data", {}).get("authData") or {}).get("sessionID", "").strip()
        if session_id:
            user_info = resp.get("data", {}).get("authData", {}).get("userInfo") or {}
            return {
                "success": True,
                "sessionId": session_id,
                "userInfo": user_info,
                "raw": resp,
            }

    # 业务错误码映射（K5()）
    retvalue = resp.get("data", {}).get("retvalue")
    messages = {
        1: "参数错误",
        12: "版本过低，请升级",
        1001: "验证码错误",
        1002: "验证码已过期",
        1003: "验证码发送太频繁",
        1004: "手机号未注册",
        1005: "手机号已注册",
        1006: "账号被锁定",
    }
    msg = resp.get("message") or messages.get(retvalue) or f"登录失败（retvalue={retvalue}）"
    raise RuntimeError(msg)


# ── 主流程 ───────────────────────────────────────────────────────────────

def _save_session(session_id: str) -> Path:
    """写入 windagent profile 的 .env。"""
    env_path = Path.home() / ".hermes" / "profiles" / "windagent" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    lines = [l for l in lines if not l.startswith("WIND_SESSION_ID=")]
    lines.append(f"WIND_SESSION_ID={session_id}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass
    return env_path


def main() -> int:
    parser = argparse.ArgumentParser(description="WindClaw 手机号+验证码登录 → session id")
    sub = parser.add_subparsers(dest="action", required=True)

    p_send = sub.add_parser("send", help="发送验证码")
    p_send.add_argument("phone", help="11 位手机号")
    p_send.add_argument("--purpose", default="login", choices=["login", "reset", "register"])

    p_login = sub.add_parser("login", help="验证码登录")
    p_login.add_argument("phone", help="11 位手机号")
    p_login.add_argument("code", help="6 位验证码")
    p_login.add_argument("--save", action="store_true", help="写入 windagent profile .env")
    p_login.add_argument("--smoke", action="store_true", help="登录后跑冒烟测试")
    p_login.add_argument("--profile", default="windagent", help="profile 名（--save 用）")

    args = parser.parse_args()

    if args.action == "send":
        try:
            result = send_code(args.phone, args.purpose)
        except RuntimeError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
        print(f"✓ 验证码已发送（{result['countdownSeconds']}s 有效）")
        return 0

    # login
    try:
        result = login_with_code(args.phone, args.code)
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    session_id = result["sessionId"]
    print(f"✓ 登录成功")
    print(f"  session id: {session_id}")
    user = result["userInfo"]
    if user:
        print(f"  用户: {user.get('userName') or user.get('userPhone') or user.get('loginName') or ''} "
              f"(userID={user.get('userID')})")

    if args.save:
        env_path = _save_session(session_id)
        print(f"  ✓ 已写入 {env_path}")

    if args.smoke:
        print("\n运行冒烟测试…")
        script = Path(__file__).resolve().parent / "smoke_wind_tools.py"
        env = dict(os.environ)
        env["WIND_SESSION_ID"] = session_id
        rc = subprocess.call([sys.executable, str(script), "--session-id", session_id, "--quiet"], env=env)
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
