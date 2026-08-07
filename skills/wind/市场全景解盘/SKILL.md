---
name: 市场全景解盘
description: 用于分析实时市场全景表现，基于市场涨跌、资金流向、板块轮动与情绪变化，判断当前市场强弱、主线方向、风险状态与盘面节奏。
metadata:
  source: windclaw
---

# 市场全景解盘

用于实时分析市场整体状态，帮助用户快速理解当前盘面是机会扩散、主线强化、结构分化，还是风险升温。

## 何时使用

- 用户要看实时市场全景、盘面强弱、主线方向、风险状态。
- 平台没有配置对应 MCP 工具，但允许通过 HTTP 请求 Wind MCP 网关。

## 调用方式

优先调用当前 skill 自带脚本：

```bash
python scripts/run.py
```

如果环境里只有 `python3`，可以改为：

```bash
python3 scripts/run.py
```

也支持显式传入上下文：

```bash
python scripts/run.py --request-context default
```

## 脚本行为

- 脚本会自动发现 `wind.sessionid`。
- 优先读取运行时 `.windclaw-aigw-session`。
- 若未找到，再尝试环境变量 `WIND_SESSION_ID`。
- 仍未找到时，再尝试读取本地 `openclaw.json` 中的 `wind.sessionid`。
- 脚本通过 HTTP POST 调用 Wind MCP 网关，不依赖平台内置 MCP 节点。
- 默认调用工具 `quote_get_market_realtime_performance`。

## 输出如何使用

- 脚本返回 JSON。
- 核心业务数据位于 `data` 字段。
- `meta` 字段记录请求参数与工具名，便于排查。
- 若需要排查原始返回，可加 `--raw` 输出完整网关响应。

## 失败处理

若脚本返回 `401`、`Unauthorized`、`authentication failed` 或提示 `wind.sessionid` 缺失 / 过期，应明确告知用户需要提供最新的 `wind.sessionid` 后重试。

## 数据原则

- 严格基于实时结构化数据分析。
- 禁止编造、猜测、补全不存在的信息。
- 缺失字段直接跳过。
- 不得根据市场印象、历史经验或外部信息推断市场状态。

## System Prompt

基于实时市场结构化数据，对市场生成专业、客观、简洁的实时市场点评。
应结合当前实时数据，自主判断哪些信息最值得关注，并围绕最有价值的盘面信息展开分析。
要求：
1. 严格依据输入数据，不得编造外部信息。
2. 输出为连续自然段，不使用标题、项目符号或表格。
3. 开篇直接使用“截至MM/DD HH:mm:ss，……”的表达方式，首句仅概述核心行情结果，其余内容后文展开；不要出现“数据更新至”“数据显示”等表述。
4. 根据当前市场状态自动调整措辞；交易中时禁止使用“收盘”等收盘态表述，且不要额外描述“正常交易中”等状态信息。
