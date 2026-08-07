#!/usr/bin/env bash
#
# 从 WindClaw 机器拉取最新 sessionid（异机部署场景）。
#
# 依赖 profile .env 中的两个变量：
#   WIND_SCP_SOURCE  = scp 源路径，如 user@192.168.1.10:/Users/x/.openclaw-windclaw/users/<id>/openclaw/.windclaw-aigw-session
#   WIND_SESSION_FILE = 本地保存路径（默认 $HERMES_HOME/wind-session.token）
#
# 用法：HERMES_HOME=~/.hermes/profiles/windagent ./scripts/update_wind_session.sh
#
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ENV_FILE="$HERMES_HOME/.env"

get_env() {
  local key="$1" line value
  [[ -f "$ENV_FILE" ]] || return 0
  while IFS= read -r line; do
    line="${line#export }"
    [[ "$line" == "$key="* ]] || continue
    value="${line#*=}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    printf '%s' "$value"
    return 0
  done < "$ENV_FILE"
}

SCP_SOURCE="$(get_env WIND_SCP_SOURCE)"
SESSION_FILE="$(get_env WIND_SESSION_FILE)"
SESSION_FILE="${SESSION_FILE:-$HERMES_HOME/wind-session.token}"

if [[ -z "$SCP_SOURCE" ]]; then
  echo "错误：.env 中没有 WIND_SCP_SOURCE，请先运行 install.sh 或手动配置。" >&2
  exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if [[ "$SCP_SOURCE" == /* || "$SCP_SOURCE" == ~/* ]]; then
  echo "==> 本地路径，直接复制：${SCP_SOURCE}"
  cp "$SCP_SOURCE" "$TMP"
else
  echo "==> scp 拉取：${SCP_SOURCE}"
  scp -q "$SCP_SOURCE" "$TMP"
fi

TOKEN="$(tr -d '\r\n' < "$TMP")"
if [[ -z "$TOKEN" ]]; then
  echo "错误：拉取到的会话文件为空（源路径是否正确？SSH 免密是否配置？）。" >&2
  exit 1
fi

mkdir -p "$(dirname "$SESSION_FILE")"
printf '%s' "$TOKEN" > "$SESSION_FILE"
chmod 600 "$SESSION_FILE"
echo "OK：Wind session 已更新 -> ${SESSION_FILE}（长度 ${#TOKEN}）"
