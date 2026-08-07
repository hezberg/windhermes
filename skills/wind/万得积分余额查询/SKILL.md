---
name: 万得积分余额查询
description: 万得积分查询：查看剩余积分、付费积分、赠送积分与积分提示。触发词：查积分、积分余额、还剩多少积分、剩余点数。用于确认 Wind 额度余量，建议在调用 Wind 数据工具前快速核验。
metadata:
  keywords: "积分查询，积分余额，点数查询，wind balance，额度"
  source: windclaw
---

# 万得积分余额查询

## 何时使用

- 用户询问“还剩多少积分”“查一下积分余额”“积分够不够用”。
- 在批量调用 Wind 数据工具之前，需要确认额度余量。
- Wind 工具返回额度/鉴权相关错误时，用于排查是否为积分不足。

## 执行方式

直接运行脚本（无需写代码）：

```bash
python3 scripts/check_balance.py
```

脚本会自动按以下顺序解析会话：
1. `--session-id <token>` 显式传入（用户给了新 token 时使用）
2. `WIND_SESSION_FILE`（同机部署时实时读取 WindClaw session 文件）
3. `WIND_SESSION_ID`（`~/.hermes/.env` 环境变量）

需要显式 token 时：

```bash
python3 scripts/check_balance.py --session-id <token>
```

## 输出解读

默认输出三行：

```text
总积分：6559
付费积分：6559
赠送/临时积分：0
提示：每日免费赠送100积分，00:00自动重置
```

如需原始 JSON（含 extendInfo 等完整字段）：

```bash
python3 scripts/check_balance.py --raw
```

## 边界情况

- 缺少 session：脚本提示设置 `--session-id` 或 `WIND_SESSION_ID`，此时告诉用户需要更新 token。
- 接口返回 code != 200：一般是会话失效，提示用户重新获取 Wind session id。
- 网络失败：提示用户稍后重试，并确认机器能访问 `m.wind.com.cn`。
