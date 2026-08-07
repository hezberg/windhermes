WIND_SESSION_ID 存储在 .env 中，用于 Wind 工具鉴权
§
If auth fails (401/403), tell user to re-login WindClaw desktop app and copy from /Users/$USER/.openclaw-windclaw/users/USER_ID/openclaw/.windclaw-aigw-session
§
当用户更新了 WIND_SESSION_ID，都要运行一次 scripts/smoke_wind_tools.py
