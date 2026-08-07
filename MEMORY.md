WIND_SESSION_ID 存储在 .env 中，用于 Wind 工具鉴权
§
Wind 工具鉴权失败（401/403 或"会话失效"）时必须立即停止当前任务并结束回复，不得基于任何 Wind 数据继续分析。告知用户 session 已过期，需运行 /wind-login <手机号> 重新登录
§
当用户更新了 WIND_SESSION_ID，都要运行一次 scripts/smoke_wind_tools.py
