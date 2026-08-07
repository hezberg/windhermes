---
name: 个股盘面透视
description: 用于分析A股、港股、美股个股实时盘面表现，基于实时行情、量价、资金与技术指标，判断个股短期强弱、资金行为与风险状态。
metadata:
  source: windclaw
---

# 个股盘面透视

仅分析 A 股、港股、美股股票。

## 何时使用

- 用户要看某只股票的实时盘面、量价、资金与技术指标表现。
- 平台没有配置对应 MCP 工具，但允许通过 HTTP 请求 Wind MCP 网关。

## 调用方式

优先调用当前 skill 自带脚本：

```bash
python scripts/run.py --security "<windcode>"
```

如果环境里只有 `python3`，可以改为：

```bash
python3 scripts/run.py --security "<windcode>"
```

示例：

- `python scripts/run.py --security 600519.SH`
- `python scripts/run.py --security 0700.HK`
- `python scripts/run.py --security AAPL.O`

## 输入要求

- 脚本优先要求标准 `windcode`。
- 也支持从混合文本中提取显式 `windcode`，例如 `请分析 600519.SH`。
- 当前版本不做中文证券简称到 `windcode` 的自动映射。
- 若用户只提供“贵州茅台”“腾讯控股”这类名称，应先要求用户补充标准代码，再继续调用脚本。

## 脚本行为

- 脚本会自动发现 `wind.sessionid`。
- 优先读取运行时 `.windclaw-aigw-session`。
- 若未找到，再尝试环境变量 `WIND_SESSION_ID`。
- 仍未找到时，再尝试读取本地 `openclaw.json` 中的 `wind.sessionid`。
- 脚本通过 HTTP POST 调用 Wind MCP 网关，不依赖平台内置 MCP 节点。
- 默认调用工具 `quote_get_stock_realtime_performance`。

## 输出如何使用

- 脚本返回 JSON。
- 核心业务数据位于 `data` 字段。
- `meta.windcode` 为最终实际请求的标准代码。
- 若需要排查原始返回，可加 `--raw` 输出完整网关响应。

## 失败处理

- 若无法从输入中提取标准 `windcode`，应直接提示用户补充代码，不要猜测。
- 若脚本返回 `401`、`Unauthorized`、`authentication failed` 或提示 `wind.sessionid` 缺失 / 过期，应明确告知用户需要提供最新的 `wind.sessionid` 后重试。

## 数据原则

- 严格基于实时结构化数据分析。
- 禁止编造、猜测、补全不存在的信息。
- 缺失字段直接跳过。
- 不得根据股票名称、历史印象或市场常识推断走势。

## System Prompt

基于实时结构化行情数据，对个股生成专业、客观、简洁的实时盘面点评。
应结合当前实时数据，自主判断哪些信息最值得关注，并围绕最有价值的盘面信息展开分析。
要求：
1. 严格依据输入数据，不得编造信息。
2. 输出为连续自然段，不使用标题、项目符号或表格。
3. 开篇直接使用“截至MM/DD HH:mm:ss，……”的表达方式，首句仅概述核心行情结果，其余内容后文展开；不要出现“数据更新至”“数据显示”等表述。
4. 根据当前市场状态自动调整措辞；交易中时禁止使用“收盘”等收盘态表述，且不要额外描述“正常交易中”等状态信息。
5. 内容中需对日内走势进行简要合理描述。
