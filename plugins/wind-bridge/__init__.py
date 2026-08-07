"""Wind financial data bridge for Hermes.

Registers native tools (no ``mcp__`` prefix):

- get_wind_data                     -- AB1 workflow, appCode abe7dbb7-...
- document_search                   -- AB1 workflow, appCode 6c31b10a-...
- wind_financial_reference_content  -- AB1 workflow, appCode 7f6e2c65-...
- wind_web_search                   -- Wind MCP JSON-RPC internet_search
- quote_get_stock_realtime_performance   -- Wind MCP JSON-RPC (实时个股行情)
- quote_get_sector_realtime_performance  -- Wind MCP JSON-RPC (实时板块行情)
- quote_get_market_realtime_performance  -- Wind MCP JSON-RPC (实时大盘行情)

Auth: explicit ``session_id`` tool argument wins; otherwise ``WIND_SESSION_ID``
is read from ``~/.hermes/.env`` (re-read on every call so token rotation takes
effect without a gateway restart), then from the process environment.

Deployment modes:
- Same machine as WindClaw: set ``WIND_SESSION_FILE`` to the WindClaw runtime
  session file (e.g. ``~/.openclaw-windclaw/users/*/openclaw/.windclaw-aigw-session``).
  The file is re-read on every call, so WindClaw token rotation is picked up
  automatically (this is checked before ``WIND_SESSION_ID``).
- Different machine: keep ``WIND_SESSION_ID`` in ``~/.hermes/.env`` updated
  manually (or via the bundled ``update_wind_session.sh`` scp helper).

Portable by design: only public Wind HTTPS endpoints, no WindClaw paths.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx

AB1_DEFAULT_URL = "https://m.wind.com.cn/wstock_share/ai/run_workflow"
WEB_SEARCH_DEFAULT_URL = "https://m.wind.com.cn/Wind.MCP.Server/vserver/vserver_windclaw/mcp"
QUOTE_MCP_DEFAULT_URL = "https://180.96.8.44/Wind.MCP.Server/vserver/vserver_test/mcp"
WINDCLAW_MCP_DEFAULT_URL = "https://m.wind.com.cn/Wind.MCP.Server/vserver/vserver_windclaw_wx/mcp"

APP_CODES = {
    "get_wind_data": "abe7dbb7-e9ac-455c-9057-98d721d27299",
    "document_search": "6c31b10a-0224-4e14-b3ea-7bb2c37dc41e",
    "wind_financial_reference_content": "7f6e2c65-81eb-4365-aec4-fac5063c871c",
}

DEFAULT_DOCTYPE = "1,2,3,4,12"
DEFAULT_TIMEOUT = 60

_AUTH_FAIL_RE = re.compile(
    r"请先登录|登录失效|会话失效|登录已过期|session expired|invalid session|unauthorized|login first|wind\.sessionid",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _env_value(name: str) -> str:
    """Prefer ~/.hermes/.env so rotating the token needs no gateway restart."""
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
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"").strip("'")
            if key == name and value:
                return value
    except Exception:
        pass
    return os.environ.get(name, "").strip()


def _resolve_session(args: dict) -> str:
    sid = str(args.get("session_id") or args.get("sessionId") or "").strip()
    if sid:
        return sid
    session_file = _env_value("WIND_SESSION_FILE")
    if session_file:
        try:
            value = Path(session_file).read_text(encoding="utf-8").strip()
            if value:
                return value
        except Exception:
            pass
    return _env_value("WIND_SESSION_ID")


def _missing_session_error() -> str:
    return (
        "错误：缺少 Wind session id。请通过参数 session_id 传入，"
        "或在 ~/.hermes/.env 中设置 WIND_SESSION_ID。"
    )


def _is_auth_failure(status: int, text: str) -> bool:
    return status in (401, 403) or bool(_AUTH_FAIL_RE.search(text))


def _auth_error(status: int, text: str) -> str:
    hint = text[:200] if text.strip() else ""
    return (
        f"错误：Wind 会话鉴权失败（HTTP {status}）。"
        "session id 可能已失效，请更新 WIND_SESSION_ID 或传入新的 session_id。"
        + (f" 详情：{hint}" if hint else "")
    )


# ---------------------------------------------------------------------------
# Response parsing (mirrors the WindClaw plugin's extraction logic)
# ---------------------------------------------------------------------------

def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except Exception:
                return value
    return value


def _extract_text(payload: Any) -> str | None:
    """Recursively find the first useful text in an AB1-style payload."""
    payload = _maybe_json(payload)
    if isinstance(payload, str):
        text = payload.strip()
        return text or None
    if isinstance(payload, list):
        for item in payload:
            found = _extract_text(item)
            if found:
                return found
        return None
    if isinstance(payload, dict):
        for key in ("result", "answer", "content", "text", "output"):
            if key in payload:
                found = _extract_text(payload[key])
                if found:
                    return found
        for key in ("response", "data", "outputs", "resultData"):
            if key in payload:
                found = _extract_text(payload[key])
                if found:
                    return found
        for value in payload.values():
            found = _extract_text(value)
            if found and found.lower() not in {"success", "ok", "0", "1", "-1"}:
                return found
    return None


def _ab1_error_message(payload: dict) -> str:
    """Build a readable error from an AB1 wrapper like {isSuccess:false,...}."""
    parts: list[str] = []
    message = payload.get("resultMessage")
    if isinstance(message, str) and message.strip():
        parts.append(message.strip())
    result_data = payload.get("resultData")
    if isinstance(result_data, str) and result_data.strip():
        parsed = _maybe_json(result_data)
        if isinstance(parsed, dict):
            inner = parsed.get("message")
            if isinstance(inner, str) and inner.strip():
                parts.append(inner.strip())
        else:
            parts.append(result_data.strip()[:300])
    return "；".join(parts) if parts else json.dumps(payload, ensure_ascii=False)[:300]


def _parse_ab1_response(tool_name: str, resp: httpx.Response) -> str:
    status = resp.status_code
    raw = resp.text
    if _is_auth_failure(status, raw):
        return _auth_error(status, raw)
    if status < 200 or status >= 300:
        return f"错误：请求失败 HTTP {status}: {raw[:300]}"

    payload = _maybe_json(raw)
    if not isinstance(payload, dict):
        found = _extract_text(raw)
        return found or f"错误：无法解析响应（HTTP {status}）"

    if payload.get("isSuccess") is False or payload.get("success") is False:
        return f"错误：{tool_name} 调用失败 - {_ab1_error_message(payload)}"

    found = _extract_text(payload)
    if found:
        return found
    if payload.get("notification") is not None:
        return (
            f"错误：{tool_name} 服务端返回空结果（workflow 无输出，"
            "可能是数据源暂时不可用或会话权限不足，可稍后重试）。"
        )
    return f"错误：{tool_name} 响应中未找到数据（HTTP {status}）"


def _parse_mcp_tool_response(resp: httpx.Response) -> str:
    status = resp.status_code
    raw = resp.text
    if _is_auth_failure(status, raw):
        return _auth_error(status, raw)
    if status < 200 or status >= 300:
        return f"错误：请求失败 HTTP {status}: {raw[:300]}"

    payload = _maybe_json(raw)
    if not isinstance(payload, dict):
        # SSE: event: message / data: {...}
        data_lines: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data = line[len("data:"):].strip()
                if data and data != "[DONE]":
                    data_lines.append(data)
        for data in reversed(data_lines):
            parsed = _maybe_json(data)
            if isinstance(parsed, dict):
                payload = parsed
                break
        else:
            return f"错误：无法解析 MCP 响应（HTTP {status}）"

    result = payload.get("result")
    if not isinstance(result, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            msg = error.get("message") or json.dumps(error, ensure_ascii=False)
            return f"错误：MCP 调用失败 - {msg}"
        return f"错误：MCP 响应缺少 result（HTTP {status}）"

    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = str(item.get("text") or "")
            inner = _maybe_json(text)
            if isinstance(inner, dict) and "mcp_tool_error_code" in inner:
                code = inner.get("mcp_tool_error_code")
                if code not in (0, "0", ""):
                    msg = inner.get("mcp_tool_error_msg") or "未知错误"
                    return f"错误：Wind 搜索失败 - {code} {msg}"
                data = inner.get("mcp_tool_data")
                if data:
                    decoded = _maybe_json(data)
                    if isinstance(decoded, dict):
                        return json.dumps(decoded, ensure_ascii=False)
                    if isinstance(decoded, str) and decoded.strip():
                        return decoded
                    return data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
            return text or "（空结果）"

    return "（未找到搜索结果）"


# ---------------------------------------------------------------------------
# HTTP calls
# ---------------------------------------------------------------------------

async def _call_ab1(
    tool_name: str,
    query: str,
    session_id: str,
    request_id: str | None = None,
    doctype: str | None = None,
    timeout_ms: int | None = None,
) -> str:
    url = os.environ.get("WIND_AB1_URL", AB1_DEFAULT_URL).strip() or AB1_DEFAULT_URL
    inputs: dict[str, Any] = {
        "query": query,
        "sessionId": session_id,
        "requestId": request_id or str(uuid.uuid4()),
    }
    if doctype:
        inputs["doctype"] = doctype
    body = {
        "appCode": APP_CODES[tool_name],
        "inputs": inputs,
        "responseMode": "blocking",
        "runWorkflowUser": "1",
        "type": 1,
    }
    headers = {"Content-Type": "application/json", "wind.sessionid": session_id}
    timeout = max(1, int(timeout_ms or 0) / 1000) if timeout_ms else DEFAULT_TIMEOUT
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)
    return _parse_ab1_response(tool_name, resp)


async def _call_web_search(
    query: str,
    session_id: str,
    freshness: str,
    count: str,
    timeout_ms: int | None = None,
) -> str:
    return await _call_mcp_tool(
        "internet_search",
        {"query": query, "freshness": freshness, "count": count},
        session_id,
        os.environ.get("WIND_WEB_SEARCH_URL", WEB_SEARCH_DEFAULT_URL).strip() or WEB_SEARCH_DEFAULT_URL,
        timeout_ms,
    )


async def _call_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
    session_id: str,
    url: str,
    timeout_ms: int | None = None,
) -> str:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream,application/json",
        "x-wind-clientname": "WindClaw",
        "wind.sessionid": session_id,
    }
    timeout = max(1, int(timeout_ms or 0) / 1000) if timeout_ms else DEFAULT_TIMEOUT
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)
    return _parse_mcp_tool_response(resp)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _timeout_ms(args: dict) -> int | None:
    value = args.get("timeout_ms") or args.get("timeoutMs")
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


async def _handle_ab1(tool_name: str, args: dict, doctype: str | None = None) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "错误：query 必填"
    session_id = _resolve_session(args)
    if not session_id:
        return _missing_session_error()
    request_id = str(args.get("request_id") or args.get("requestId") or "").strip() or None
    try:
        return await _call_ab1(
            tool_name,
            query,
            session_id,
            request_id=request_id,
            doctype=doctype,
            timeout_ms=_timeout_ms(args),
        )
    except Exception as exc:
        return f"错误：请求 Wind 接口失败 - {type(exc).__name__}: {exc}"


async def _handle_get_wind_data(args: dict, **kw) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        codes = str(args.get("codes") or "").strip()
        if codes:
            fields = str(args.get("fields") or "").strip()
            option = str(args.get("option") or "").strip()
            parts = [f"查询 {codes}"]
            if option:
                parts.append(f"口径 {option}")
            if fields:
                parts.append(f"指标 {fields}")
            args = dict(args)
            args["query"] = "，".join(parts)
    return await _handle_ab1("get_wind_data", args)


async def _handle_document_search(args: dict, **kw) -> str:
    doctype = str(args.get("doctype") or "").strip() or DEFAULT_DOCTYPE
    return await _handle_ab1("document_search", args, doctype=doctype)


async def _handle_wind_financial_reference_content(args: dict, **kw) -> str:
    return await _handle_ab1("wind_financial_reference_content", args)


async def _handle_wind_web_search(args: dict, **kw) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "错误：query 必填"
    session_id = _resolve_session(args)
    if not session_id:
        return _missing_session_error()
    freshness = str(args.get("freshness") or "").strip() or "最近一周"
    count = str(args.get("count") or "").strip() or "5"
    try:
        return await _call_web_search(
            query,
            session_id,
            freshness,
            count,
            timeout_ms=_timeout_ms(args),
        )
    except Exception as exc:
        return f"错误：请求 Wind 搜索失败 - {type(exc).__name__}: {exc}"


async def _handle_quote_get_stock_realtime_performance(args: dict, **kw) -> str:
    windcode = str(args.get("windcode") or "").strip()
    if not windcode:
        return "错误：windcode 必填，如 600519.SH / 00700.HK / AAPL.O"
    session_id = _resolve_session(args)
    if not session_id:
        return _missing_session_error()
    try:
        return await _call_mcp_tool(
            "quote_get_stock_realtime_performance",
            {"windcode": windcode},
            session_id,
            os.environ.get("WIND_QUOTE_MCP_URL", QUOTE_MCP_DEFAULT_URL).strip() or QUOTE_MCP_DEFAULT_URL,
            _timeout_ms(args),
        )
    except Exception as exc:
        return f"错误：请求 Wind 个股行情失败 - {type(exc).__name__}: {exc}"


async def _handle_quote_get_sector_realtime_performance(args: dict, **kw) -> str:
    indexcode = str(args.get("indexcode") or args.get("indexCode") or "").strip()
    if not indexcode:
        return "错误：indexcode 必填，如 886063.WI（半导体指数）"
    session_id = _resolve_session(args)
    if not session_id:
        return _missing_session_error()
    try:
        return await _call_mcp_tool(
            "quote_get_sector_realtime_performance",
            {"indexcode": indexcode},
            session_id,
            os.environ.get("WIND_QUOTE_MCP_URL", QUOTE_MCP_DEFAULT_URL).strip() or QUOTE_MCP_DEFAULT_URL,
            _timeout_ms(args),
        )
    except Exception as exc:
        return f"错误：请求 Wind 板块行情失败 - {type(exc).__name__}: {exc}"


async def _handle_quote_get_market_realtime_performance(args: dict, **kw) -> str:
    session_id = _resolve_session(args)
    if not session_id:
        return _missing_session_error()
    arguments: dict[str, Any] = {}
    market_type = str(args.get("market_type") or args.get("marketType") or "").strip()
    if market_type:
        arguments["marketType"] = market_type
    try:
        return await _call_mcp_tool(
            "quote_get_market_realtime_performance",
            arguments,
            session_id,
            os.environ.get("WIND_QUOTE_MCP_URL", QUOTE_MCP_DEFAULT_URL).strip() or QUOTE_MCP_DEFAULT_URL,
            _timeout_ms(args),
        )
    except Exception as exc:
        return f"错误：请求 Wind 大盘行情失败 - {type(exc).__name__}: {exc}"


def _make_windclaw_mcp_handler(
    tool_name: str,
    required: list[str],
    friendly: str,
) -> Any:
    """Build a generic handler for the 13 WindClaw MCP tools.

    Keeps the original tool argument names (``windCode``/``windcode``/``query``/...)
    so the tool behaves exactly like the WindClaw MCP server.
    """

    async def handler(args: dict, **kw) -> str:
        session_id = _resolve_session(args)
        if not session_id:
            return _missing_session_error()
        arguments: dict[str, Any] = {}
        for key, value in args.items():
            if key in ("session_id", "sessionId", "timeout_ms", "timeoutMs"):
                continue
            if value is None:
                continue
            arguments[key] = value
        for name in required:
            if not str(arguments.get(name) or "").strip():
                return f"错误：{name} 必填"
        try:
            return await _call_mcp_tool(
                tool_name,
                arguments,
                session_id,
                os.environ.get("WIND_WINDCLAW_MCP_URL", WINDCLAW_MCP_DEFAULT_URL).strip()
                or WINDCLAW_MCP_DEFAULT_URL,
                _timeout_ms(args),
            )
        except Exception as exc:
            return f"错误：请求{friendly}失败 - {type(exc).__name__}: {exc}"

    return handler


# ---------------------------------------------------------------------------
# Slash commands (Wind 积分)
# ---------------------------------------------------------------------------

POINTS_ORIGIN = os.environ.get("WIND_POINTS_API_ORIGIN", "https://m.wind.com.cn")
POINTS_BALANCE_PATH = "/wstock_business_service/point/balance"
POINTS_LOGS_PATH = "/wstock_business_service/point/logs"


def _points_headers(session_id: str) -> dict[str, str]:
    return {"wind.sessionid": session_id, "windsessionid": session_id}


async def _cmd_wind_points(raw_args: str) -> str:
    """/wind-points — 查询万得剩余积分。"""
    session_id = _resolve_session({})
    if not session_id:
        return _missing_session_error()
    url = POINTS_ORIGIN.rstrip("/") + POINTS_BALANCE_PATH
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=_points_headers(session_id))
        payload = _maybe_json(resp.text)
    except Exception as exc:
        return f"错误：请求积分接口失败 - {type(exc).__name__}: {exc}"

    if not isinstance(payload, dict) or payload.get("code") != 200:
        msg = payload.get("message") if isinstance(payload, dict) else resp.text
        return f"错误：{msg or '积分接口返回异常'}"[:300]
    data = payload.get("data") or {}
    lines = [
        f"总积分：{data.get('totalBalance')}",
        f"付费积分：{data.get('paidBalance')}",
        f"赠送/临时积分：{data.get('tempBalance')}",
    ]
    try:
        ext = json.loads(data.get("extendInfo") or "{}")
        if ext.get("bonusTips"):
            lines.append(f"提示：{ext['bonusTips']}")
    except Exception:
        pass
    return "\n".join(lines)


async def _cmd_wind_flow(raw_args: str) -> str:
    """/wind-flow [页码] — 查询万得积分流水，默认第 1 页。"""
    session_id = _resolve_session({})
    if not session_id:
        return _missing_session_error()
    page = 1
    arg = (raw_args or "").strip()
    if arg:
        try:
            page = max(1, int(arg))
        except ValueError:
            return "用法：/wind-flow [页码]，如 /wind-flow 2"
    params = urllib.parse.urlencode({"page": page, "pageSize": 20})
    url = f"{POINTS_ORIGIN.rstrip('/')}{POINTS_LOGS_PATH}?{params}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=_points_headers(session_id))
        payload = _maybe_json(resp.text)
    except Exception as exc:
        return f"错误：请求积分流水失败 - {type(exc).__name__}: {exc}"

    if not isinstance(payload, dict) or payload.get("code") != 200:
        msg = payload.get("message") if isinstance(payload, dict) else resp.text
        return f"错误：{msg or '积分流水接口返回异常'}"[:300]
    data = payload.get("data") or {}
    rows = data.get("data") or []
    total = data.get("total", 0)
    total_page = data.get("totalPage", 1)
    if not rows:
        return f"共 {total} 条 | 第 {page}/{total_page} 页\n（暂无流水记录）"
    lines = [f"共 {total} 条 | 第 {page}/{total_page} 页"]
    type_names = {1: "充值", 2: "赠送", 3: "扣减"}
    for row in rows:
        point = row.get("point")
        point_str = f"{point:+d}" if isinstance(point, int) else str(point)
        create_time = row.get("createTime") or ""
        type_name = type_names.get(row.get("type"), f"type{row.get('type')}")
        remark = (row.get("remark") or "")[:60]
        lines.append(f"{create_time} | {point_str} | {type_name} | {remark}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_COMMON_STRING = {"type": "string"}

_SESSION_PARAM = {
    "session_id": {
        **{},
        "type": "string",
        "description": "Wind 会话 ID。不传时使用环境变量 WIND_SESSION_ID。",
    }
}


def _with_session(properties: dict, required: list[str] | None = None) -> dict:
    props = dict(properties)
    props.update(_SESSION_PARAM)
    return {"type": "object", "properties": props, "required": required or []}


_QUERY_PARAM = {
    "query": {
        "type": "string",
        "description": "自然语言查询，简短，使用 2-3 个短语或 1 个问句。",
    }
}

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_wind_data",
        "description": (
            "查询结构化金融数据，用于行情、财务、估值、宏观、市场指标数据，"
            "并支持按条件筛选证券标的。可用自然语言 query；"
            "也可传 codes/fields/option 结构化参数（自动转换为查询）。"
        ),
        "schema": _with_session(
            {
                **_QUERY_PARAM,
                "codes": {
                    "type": "string",
                    "description": "可选：万得代码，逗号分隔，如 300502.SZ。不传 query 时必填。",
                },
                "fields": {
                    "type": "string",
                    "description": "可选：指标字段，逗号分隔，如 pe_ttm,pb,close。",
                },
                "option": {
                    "type": "string",
                    "description": "可选：数据口径，如 valuation / financial / valuation_history。",
                },
            },
            required=[],
        ),
        "handler": _handle_get_wind_data,
    },
    {
        "name": "document_search",
        "description": (
            "检索金融资讯：万得新闻、研报、公告、财经会议、法律法规、金融知识、舆情。"
            "doctype 选项：1=新闻 2=研报 3=公告 4=财经会议 5=法律法规 6=金融知识 12=舆情，"
            "可英文逗号多选（如 2,4），默认 1,2,3,4,12。"
        ),
        "schema": _with_session(
            {
                **_QUERY_PARAM,
                "doctype": {
                    "type": "string",
                    "description": "文档类型，如 1,2,3,4,12（默认）。",
                },
            },
            required=["query"],
        ),
        "handler": _handle_document_search,
    },
    {
        "name": "wind_financial_reference_content",
        "description": (
            "查询高质量投资研究语料，用于公司研究、行业研究、投资逻辑和基本面分析等"
            "无需实时数据和原始资讯的场景。"
        ),
        "schema": _with_session(_QUERY_PARAM, required=["query"]),
        "handler": _handle_wind_financial_reference_content,
    },
    {
        "name": "wind_web_search",
        "description": (
            "通过 Wind MCP internet_search 进行网页新闻、资讯查询；联网搜索时优先使用。"
        ),
        "schema": _with_session(
            {
                **_QUERY_PARAM,
                "freshness": {"type": "string", "description": "时效范围，默认“最近一周”。"},
                "count": {"type": "string", "description": "返回条数，默认 5。"},
            },
            required=["query"],
        ),
        "handler": _handle_wind_web_search,
    },
    {
        "name": "quote_get_stock_realtime_performance",
        "description": (
            "按万得代码查询单个证券（A股/港股/美股）的实时行情分析："
            "价格、涨跌幅、换手、市盈率、市值、分时点位等结构化数据。"
            "只支持代码查询，如 600519.SH / 00700.HK / AAPL.O。"
        ),
        "schema": _with_session(
            {
                "windcode": {
                    "type": "string",
                    "description": "万得标准代码，单个，如 600519.SH。",
                },
            },
            required=["windcode"],
        ),
        "handler": _handle_quote_get_stock_realtime_performance,
    },
    {
        "name": "quote_get_sector_realtime_performance",
        "description": (
            "按万得指数代码查询板块实时表现：行情快照、技术指标、资金流向、"
            "分钟级时序、短线信号等。如半导体指数 886063.WI。"
        ),
        "schema": _with_session(
            {
                "indexcode": {
                    "type": "string",
                    "description": "万得板块/指数代码，如 886063.WI。",
                },
            },
            required=["indexcode"],
        ),
        "handler": _handle_quote_get_sector_realtime_performance,
    },
    {
        "name": "quote_get_market_realtime_performance",
        "description": (
            "查询指定市场当前交易日整体表现：指数涨跌、涨跌家数、成交、情绪指标、"
            "资金流向。用于“今天A股怎么样”“港股今日表现”等。"
        ),
        "schema": _with_session(
            {
                "market_type": {
                    "type": "string",
                    "description": "市场类型：0=全球 1=A股（默认） 2=港股 7=美股 br=巴西。",
                },
            },
            required=[],
        ),
        "handler": _handle_quote_get_market_realtime_performance,
    },
]


# ---------------------------------------------------------------------------
# WindClaw MCP tools (13) -- keep original tool names and argument names.
# ---------------------------------------------------------------------------

_WINDCODE_STR = {
    "type": "string",
    "description": "万得证券代码，单个（禁止多个），如 600519.SH / 00700.HK / AAPL.O。",
}

_WINDCLAW_MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "wechat_extract_article_content",
        "description": (
            "提取微信公众号文章（mp.weixin.qq.com）的正文和元信息，"
            "返回 Markdown 或 JSON；可开启 OCR 识别图片文字。"
            "仅用于文章链接解析，不用于搜索或公众号列表。"
        ),
        "required": ["url"],
        "props": {
            "url": {
                "type": "string",
                "description": "微信公众号文章 URL，如 https://mp.weixin.qq.com/s/xxx",
            },
            "contentFormat": {
                "type": "string",
                "enum": ["markdown", "json", "all"],
                "description": "返回格式：markdown / json / all，默认 markdown。",
            },
            "isOCRImage": {
                "type": "boolean",
                "description": "是否识别文章图片中的文字，默认 false。",
            },
        },
    },
    {
        "name": "wechat_search_articles_by_account",
        "description": (
            "按单个微信公众号 ID 或完整公众号名称查询文章列表，返回标题、链接、发布时间。"
            "必须逐字保留用户给出的账号 ID/名称，禁止用模糊描述或关键词替代。"
        ),
        "required": ["weixinIdOrName"],
        "props": {
            "weixinIdOrName": {
                "type": "string",
                "description": "公众号 ID 或完整公众号名称，如 rmrbwx / 人民日报。",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "返回条数，默认 20，最多 100。",
            },
        },
    },
    {
        "name": "stock_get_market_realtime_analysis",
        "description": (
            "查询当前交易日主要市场与跨资产实时表现（A股/港股/美股/全球指数/商品/汇率），"
            "用于判断市场强弱、区域分化、风险偏好和跨资产联动。"
        ),
        "required": [],
        "props": {
            "query": {
                "type": "string",
                "description": "市场类型：0=全球 1=A股（默认） 2=港股 7=美股 br=巴西。",
            },
        },
    },
    {
        "name": "stock_get_sector_realtime_analysis",
        "description": (
            "按板块/指数代码查询板块实时行情：涨跌分布、资金流、区间表现、"
            "重要成分股、领涨领跌、估值和板块分析。如半导体指数 886063.WI。"
        ),
        "required": ["query"],
        "props": {
            "query": {
                "type": "string",
                "description": "万得板块/指数代码，如 886063.WI。",
            },
        },
    },
    {
        "name": "stock_get_industry_research",
        "description": (
            "查询行业研究资料：产业链、市场空间、供需/竞争格局、核心公司、"
            "政策影响、趋势、机会与风险。用于行业/赛道/主题的长期逻辑研究。"
        ),
        "required": ["keyword"],
        "props": {
            "keyword": {
                "type": "string",
                "description": "行业关键词，如：半导体设备、创新药、低空经济。",
            },
        },
    },
    {
        "name": "stock_get_company_profile",
        "description": (
            "查询单只股票的公司画像全量信息：基本信息、财务快照、主营构成、"
            "经营数据、控制权治理、募投项目。用于快速建立公司研究框架。"
        ),
        "required": ["windCode"],
        "props": {"windCode": _WINDCODE_STR},
    },
    {
        "name": "stock_get_company_finance_analysis",
        "description": (
            "查询单只股票的财务研究与摘要：三张表、盈利质量、成本费用、"
            "杠杆水平、现金流质量和资产负债风险。"
        ),
        "required": ["windcode"],
        "props": {
            "windcode": _WINDCODE_STR,
            "currency": {
                "type": "string",
                "enum": ["原始币种", "CNY", "USD", "HKD", "EUR", "JPY", "GBP", "CAD", "AUD", "SGD", "TWD", "CHF"],
                "description": "币种，默认原始币种。",
            },
            "reportType": {
                "type": "string",
                "enum": ["CONSOLIDATED", "CONSOLIDATED_ADJUSTED"],
                "description": "报表类型：合并报表 / 合并报表调整，默认 CONSOLIDATED。",
            },
            "groupId": {
                "type": "string",
                "enum": ["CUMULATIVE", "ANNUAL_AND_QUARTERLY", "ANNUAL", "QUARTERLY", "CALENDAR_YEAR"],
                "description": "报告模板：累计报 / 年报&单季度 / 年报 / 单季报 / 日历年。",
            },
        },
    },
    {
        "name": "stock_get_company_earnings_estimate",
        "description": (
            "查询单只股票的券商盈利预测、机构评级、一致目标价、上涨空间，"
            "以及未来财年收入/利润/EPS/ROE/PE 预期。"
        ),
        "required": ["windCode"],
        "props": {"windCode": _WINDCODE_STR},
    },
    {
        "name": "stock_get_company_valuation",
        "description": (
            "查询单只股票当前估值、历史估值分位和同行可比估值，"
            "覆盖 PE/PB/PS/PCF/企业倍数/股息率，判断贵贱与安全边际。"
        ),
        "required": ["windCode"],
        "props": {"windCode": _WINDCODE_STR},
    },
    {
        "name": "stock_get_company_updates",
        "description": (
            "汇总单只股票近期事件、公告、新闻、研报观点和会议纪要，"
            "跟踪最新信息流、舆情、催化与后续跟踪重点。"
        ),
        "required": ["windCode"],
        "props": {"windCode": _WINDCODE_STR},
    },
    {
        "name": "stock_get_money_flow_analysis",
        "description": (
            "查询单只股票资金面：成交活跃度、主力资金、融资融券、龙虎榜、"
            "大宗交易、股东行为、陆股通、基金持仓、十大流通股东变化。"
        ),
        "required": ["windCode"],
        "props": {"windCode": _WINDCODE_STR},
    },
    {
        "name": "stock_get_technical_analysis",
        "description": (
            "查询单只股票技术面：趋势、均线、MACD、RSI、KDJ、BOLL、ATR、OBV、"
            "关键价位和回撤，研判短中期走势、动能与支撑压力。"
        ),
        "required": ["windCode"],
        "props": {"windCode": _WINDCODE_STR},
    },
    {
        "name": "stock_get_realtime_analysis",
        "description": (
            "查询单只股票实时行情与盘中表现：最新价、涨跌幅、成交量额、"
            "分时点位、资金流向、技术指标、短线提示和盘中强弱判断。"
        ),
        "required": ["query"],
        "props": {
            "query": {
                "type": "string",
                "description": "万得股票代码，如 600519.SH。",
            },
        },
    },
]

for _mcp_meta in _WINDCLAW_MCP_TOOLS:
    _TOOLS.append(
        {
            "name": _mcp_meta["name"],
            "description": _mcp_meta["description"],
            "schema": _with_session(_mcp_meta["props"], required=_mcp_meta["required"]),
            "handler": _make_windclaw_mcp_handler(
                _mcp_meta["name"],
                _mcp_meta["required"],
                _mcp_meta["name"],
            ),
        }
    )


def register(ctx) -> None:
    """Register all Wind tools. Called once by the Hermes plugin loader."""
    for tool in _TOOLS:
        ctx.register_tool(
            name=tool["name"],
            toolset="wind",
            schema=tool["schema"],
            handler=tool["handler"],
            description=tool["description"],
            is_async=True,
        )
    ctx.register_command(
        name="wind-points",
        handler=_cmd_wind_points,
        description="查询万得剩余积分（总/付费/赠送）",
    )
    ctx.register_command(
        name="wind-flow",
        handler=_cmd_wind_flow,
        description="查询万得积分流水（默认第 1 页，可带页码）",
        args_hint="[页码]",
    )
