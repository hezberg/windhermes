---
name: 万得积分流水查询
description: 万得积分流水查询：按分页查看积分消费/赠送记录，含每条流水的时间、点数、类型与备注。触发词：积分流水、积分明细、积分记录、扣了多少积分。用于核对 Wind 额度消耗明细。
metadata:
  keywords: "积分流水，积分明细，积分记录，点数消费，wind points log"
  source: windclaw
---

# 万得积分流水查询

## 何时使用

- 用户询问“积分花哪了”“查一下积分流水/明细/记录”。
- 需要核对某段时间的 Wind 额度消耗（如心跳轮询、工具调用扣分）。
- 需要判断扣分异常或统计每日消耗。

## 执行方式

默认查询第 1 页（每页 20 条）：

```bash
python3 scripts/query_flow.py
```

常用参数：

```bash
python3 scripts/query_flow.py --page 2 --page-size 10   # 翻页
python3 scripts/query_flow.py --session-id <token>      # 显式 token
python3 scripts/query_flow.py --raw                     # 原始 JSON
```

鉴权优先级与余额脚本一致：`--session-id` > `WIND_SESSION_FILE` > `WIND_SESSION_ID`。

## 输出解读

非 raw 模式输出简洁表格，每条记录包含：

```text
时间 / 点数（-2） / 类型 / 备注
```

`--raw` 返回完整 JSON，字段包括：

- `total` / `totalPage`：总条数与总页数
- `data[].point`：该条增减点数（负数为消费）
- `data[].type` / `assetType`：积分类型
- `data[].remark`：消费场景备注（如 `[OpenClaw heartbeat poll]`）
- `data[].summary`：请求级摘要（token 数、请求数、模型名等）

## 边界情况

- 缺 session：提示设置 `--session-id` 或 `WIND_SESSION_ID`。
- 页数超出范围：接口返回空列表，属正常现象。
- 会话失效：提示用户重新获取 Wind session id。
