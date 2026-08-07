#!/usr/bin/env python3
"""Shared helpers for HTTP-based Wind MCP skills."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request


MCP_URL = "https://180.96.8.44/Wind.MCP.Server/vserver/vserver_test/mcp"


class McpRequestError(RuntimeError):
    """Raised when an HTTP or MCP-layer request fails."""


def load_wind_session_id_from_config(config_path: Path) -> str | None:
    try:
        parsed = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    providers = parsed.get("models", {}).get("providers", {})
    if not isinstance(providers, dict):
        return None

    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        headers = provider.get("headers")
        if not isinstance(headers, dict):
            continue
        value = headers.get("wind.sessionid")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_runtime_wind_session_id_from_file() -> str | None:
    home = Path.home()
    active_user_id = os.environ.get("WINDCLAW_ACTIVE_USER_ID", "").strip()

    state_dir: Path | None = None
    if active_user_id:
        sanitized = active_user_id.lower()
        sanitized = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in sanitized)
        sanitized = sanitized.strip("-")[:32] or "user"
        digest = hashlib.sha1(active_user_id.encode("utf-8")).hexdigest()[:12]
        state_dir = home / ".openclaw-windclaw" / "users" / f"{sanitized}-{digest}" / "openclaw"
    else:
        fallback_state_dir = os.environ.get("OPENCLAW_STATE_DIR", "").strip()
        if fallback_state_dir:
            state_dir = Path(fallback_state_dir)

    candidate_files: list[Path] = []
    if state_dir is not None:
        candidate_files.append(state_dir / ".windclaw-aigw-session")
    else:
        root = home / ".openclaw-windclaw"
        try:
            candidate_files.extend(root.glob("users/*/openclaw/.windclaw-aigw-session"))
            candidate_files.extend(root.glob("anonymous/openclaw/.windclaw-aigw-session"))
        except Exception:
            return None
        candidate_files.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)

    for runtime_file in candidate_files:
        try:
            value = runtime_file.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if value:
            return value
    return None


def resolve_wind_session_id(explicit: str | None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()

    runtime_value = load_runtime_wind_session_id_from_file()
    if runtime_value:
        return runtime_value

    env_value = os.environ.get("WIND_SESSION_ID", "").strip()
    if env_value:
        return env_value

    script_path = Path(__file__).resolve()
    checked: set[Path] = set()
    candidates = [Path.home() / ".openclaw" / "openclaw.json"]

    for parent in script_path.parents:
        candidates.append(parent / "openclaw.json")
        candidates.append(parent / ".openclaw" / "openclaw.json")

    for candidate in candidates:
        if candidate in checked:
            continue
        checked.add(candidate)
        if not candidate.is_file():
            continue
        resolved = load_wind_session_id_from_config(candidate)
        if resolved:
            return resolved
    return None


def call_mcp_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    wind_session_id: str,
    timeout: int,
) -> tuple[Any, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    req = request.Request(
        MCP_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream,application/json",
            "wind.sessionid": wind_session_id,
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", None) or resp.getcode()
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace").strip()
        if exc.code == 401:
            raise McpRequestError("Wind MCP gateway returned 401 Unauthorized. wind.sessionid may be expired.") from exc
        raise McpRequestError(
            f"Wind MCP gateway request failed with HTTP {exc.code}: {details or exc.reason}"
        ) from exc
    except error.URLError as exc:
        raise McpRequestError(f"Wind MCP gateway request could not be completed: {exc.reason}") from exc

    if status == 401:
        raise McpRequestError("Wind MCP gateway returned 401 Unauthorized. wind.sessionid may be expired.")

    outer = parse_sse_or_json(raw)
    if looks_like_auth_failure(outer):
        raise McpRequestError("Wind MCP gateway authentication failed. wind.sessionid may be expired.")
    return extract_business_data(outer), outer


def parse_sse_or_json(payload: Any) -> Any:
    text = payload.strip() if isinstance(payload, str) else payload
    if not isinstance(text, str):
        return text or {}
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)

    data_lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        if line.startswith("data:"):
            data = line[5:].strip()
            if data != "[DONE]":
                data_lines.append(data)

    for data in reversed(data_lines):
        try:
            return json.loads(data)
        except Exception:
            continue

    if not data_lines:
        raise McpRequestError("Wind MCP gateway returned empty SSE content.")
    return json.loads("\n".join(data_lines))


def extract_business_data(outer: Any) -> Any:
    if not isinstance(outer, dict):
        return outer

    result = outer.get("result") or {}
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list) and content:
        first = content[0]
        text = first.get("text") if isinstance(first, dict) else first
        tool_result = json_loads_maybe(text)
        if isinstance(tool_result, dict):
            error_code = str(tool_result.get("mcp_tool_error_code", "0"))
            if error_code not in {"0", ""}:
                msg = tool_result.get("mcp_tool_error_msg", "")
                raise McpRequestError(f"MCP tool call failed: {error_code} {msg}".strip())
            return json_loads_maybe(tool_result.get("mcp_tool_data", tool_result))
        return tool_result

    return outer


def json_loads_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return {}
    if stripped[0] not in "{[":
        return value
    return json.loads(stripped)


def looks_like_auth_failure(data: Any) -> bool:
    text = json.dumps(data, ensure_ascii=False).lower()
    auth_tokens = ("401", "unauthorized", "session", "login", "invalid session", "session expired")
    return any(token in text for token in auth_tokens)
