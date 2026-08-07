#!/usr/bin/env bash
#
# WindAgent 安装：
#   - 交互终端下运行 ./install.sh → 自动进入 Hermes 风格交互向导
#   - 带参数运行 → 静默安装（适合脚本/CI）
# 用法:
#   ./install.sh                     # 交互式向导（推荐）
#   ./install.sh --session-id <tok>  # 直接给定 token
#   ./install.sh --force             # profile 已存在时重建
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE_NAME="windagent"
HERMES_BIN="${HERMES_BIN:-hermes}"
HERMES_ROOT="$HOME/.hermes"
PROFILE_DIR="$HERMES_ROOT/profiles/$PROFILE_NAME"
PLUGIN_SRC="$SCRIPT_DIR/plugins/wind-bridge"
SKILLS_SRC="$SCRIPT_DIR/skills/wind"
SOUL_SRC="$SCRIPT_DIR/SOUL.md"
MEMORY_SRC="$SCRIPT_DIR/MEMORY.md"
SMOKE_SRC="$SCRIPT_DIR/scripts/smoke_wind_tools.py"
LOGIN_SRC="$SCRIPT_DIR/scripts/wind_login.py"

RED=$'\033[31m'; GREEN=$'\033[32m'; NC=$'\033[0m'
step() { echo "${GREEN}==>${NC} $*"; }
ok()   { echo "  ${GREEN}✔${NC} $*"; }
err()  { echo "  ${RED}✘${NC} $*"; }

# ── 安装日志（tee 到文件，方便调试）──────────────────────────────────────
LOG_FILE="${LOG_FILE:-/tmp/windagent-install.log}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
exec > >(tee -a "$LOG_FILE") 2>&1
echo "===== WindAgent install $(date '+%F %T') ====="

FORCE=0
CLI_SESSION=""
HAS_FLAGS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; HAS_FLAGS=1; shift ;;
    --session-id) CLI_SESSION="${2:-}"; HAS_FLAGS=1; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

# 交互终端 + 无参数 → 转交 Hermes 风格向导
if [[ "$HAS_FLAGS" == "0" && -t 0 && -t 1 ]]; then
  exec python3 "$SCRIPT_DIR/scripts/windagent_setup.py"
fi

# ── 1. 检查 Hermes ───────────────────────────────────────────────────────
step "检查 Hermes"
command -v "$HERMES_BIN" >/dev/null 2>&1 || { err "未找到 hermes，请先安装 Hermes Agent"; exit 1; }
"$HERMES_BIN" version >/dev/null 2>&1 || { err "hermes version 运行失败"; exit 1; }
ok "Hermes 已安装"

HERMES_AGENT_REPO="$(echo "$("$HERMES_BIN" version 2>&1)" | grep -o 'Install directory: .*' | awk '{print $3}' || true)"
HERMES_AGENT_REPO="${HERMES_AGENT_REPO:-$HERMES_ROOT/hermes-agent}"
HERMES_AGENT_SKILL_SRC="$HERMES_AGENT_REPO/skills/autonomous-ai-agents/hermes-agent"
[[ -d "$HERMES_AGENT_SKILL_SRC" ]] || HERMES_AGENT_SKILL_SRC="$HERMES_ROOT/skills/autonomous-ai-agents/hermes-agent"

# 冒烟测试需要 httpx：优先用 Hermes 自己的 venv Python（必有该依赖）
HERMES_PYTHON=""
for candidate in "$HERMES_AGENT_REPO/venv/bin/python" "$HERMES_AGENT_REPO/.venv/bin/python"; do
  if [[ -x "$candidate" ]]; then HERMES_PYTHON="$candidate"; break; fi
done
HERMES_PYTHON="${HERMES_PYTHON:-python3}"

# ── 2. 创建 profile ──────────────────────────────────────────────────────
step "创建 profile: $PROFILE_NAME"
if [[ -d "$PROFILE_DIR" ]]; then
  if [[ "$FORCE" == "1" ]]; then
    "$HERMES_BIN" profile delete "$PROFILE_NAME" --yes >/dev/null 2>&1 || rm -rf "$PROFILE_DIR"
  else
    ok "profile 已存在，跳过创建（如需重建用 --force）"
  fi
fi
[[ -d "$PROFILE_DIR" ]] || "$HERMES_BIN" profile create "$PROFILE_NAME" --no-skills --description "Wind 金融投研终端" >/dev/null
PROFILE_LIST="$("$HERMES_BIN" profile list 2>&1 || true)"
echo "$PROFILE_LIST" | grep -qw "$PROFILE_NAME" || { err "profile 创建失败"; exit 1; }
ok "profile 就绪"

# ── 3. 注册技能 ──────────────────────────────────────────────────────────
step "注册技能（hermes-agent + wind）"
PROFILE_SKILLS="$PROFILE_DIR/skills"
mkdir -p "$PROFILE_SKILLS"
if [[ -d "$HERMES_AGENT_SKILL_SRC" ]]; then
  mkdir -p "$PROFILE_SKILLS/autonomous-ai-agents"
  cp -R "$HERMES_AGENT_SKILL_SRC" "$PROFILE_SKILLS/autonomous-ai-agents/hermes-agent"
fi
cp -R "$SKILLS_SRC" "$PROFILE_SKILLS/wind"

verify_skills() {
  local out
  out="$("$HERMES_BIN" -p "$PROFILE_NAME" skills list --enabled-only 2>&1 || true)"
  local wind_count hermes_ok
  wind_count="$(echo "$out" | grep -c "│ wind " || true)"
  hermes_ok=0
  echo "$out" | grep -q "hermes-agent" && hermes_ok=1
  [[ "$wind_count" -ge "$(ls "$SKILLS_SRC" | wc -l | tr -d ' ')" && "$hermes_ok" == "1" ]] \
    && echo OK || echo FAIL
}

SKILL_VERIFY="$(verify_skills)"
[[ "$SKILL_VERIFY" == OK ]] || { step "技能验证未通过，重试…"; SKILL_VERIFY="$(verify_skills)"; }
[[ "$SKILL_VERIFY" == OK ]] && ok "技能验证通过" || err "技能验证失败（最后检查阶段会再次提示）"

# ── 4. 注册插件 ──────────────────────────────────────────────────────────
step "注册插件 wind_tool"
PLUGIN_DEST="$PROFILE_DIR/plugins/wind_tool"
mkdir -p "$PROFILE_DIR/plugins"
rm -rf "$PLUGIN_DEST"
cp -R "$PLUGIN_SRC" "$PLUGIN_DEST"
rm -rf "$PLUGIN_DEST/__pycache__"
sed -i '' 's/^name: wind-bridge$/name: wind_tool/' "$PLUGIN_DEST/plugin.yaml" 2>/dev/null \
  || sed -i 's/^name: wind-bridge$/name: wind_tool/' "$PLUGIN_DEST/plugin.yaml"

PROFILE_CONFIG="$PROFILE_DIR/config.yaml"
python3 - "$PROFILE_CONFIG" <<'PY'
import os, sys, yaml
path = sys.argv[1]
cfg = {}
if os.path.exists(path):
    try:
        cfg = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception:
        cfg = {}
cfg.setdefault("plugins", {})
enabled = cfg["plugins"].setdefault("enabled", [])
if "wind_tool" not in enabled:
    enabled.append("wind_tool")
with open(path, "w", encoding="utf-8") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
PY

PLUGIN_VERIFY=""
for _ in 1 2; do
  PLUGIN_OUT="$("$HERMES_BIN" -p "$PROFILE_NAME" plugins list 2>&1 || true)"
  echo "$PLUGIN_OUT" | grep -q "wind_tool" && { PLUGIN_VERIFY=OK; break; }
done
[[ "$PLUGIN_VERIFY" == OK ]] && ok "插件已注册" || err "插件注册失败"

# ── 5. SOUL.md ───────────────────────────────────────────────────────────
step "配置 SOUL.md / MEMORY.md / 脚本"
cp "$SOUL_SRC" "$PROFILE_DIR/SOUL.md"
mkdir -p "$PROFILE_DIR/memories"
cp "$MEMORY_SRC" "$PROFILE_DIR/memories/MEMORY.md"
mkdir -p "$PROFILE_DIR/scripts"
cp "$SMOKE_SRC" "$PROFILE_DIR/scripts/smoke_wind_tools.py"
if [[ -f "$LOGIN_SRC" ]]; then
  cp "$LOGIN_SRC" "$PROFILE_DIR/scripts/wind_login.py"
fi
ok "SOUL.md / MEMORY.md / smoke / login 脚本已就位"

# ── 6. 配置 .env ─────────────────────────────────────────────────────────
step "配置 .env"
PROFILE_ENV="$PROFILE_DIR/.env"
[[ -f "$PROFILE_ENV" ]] || printf '# Per-profile secrets.\n' > "$PROFILE_ENV"
set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  grep -v "^${key}=" "$PROFILE_ENV" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$PROFILE_ENV"
  chmod 600 "$PROFILE_ENV"
}
set_env "WIND_SESSION_ID" "${CLI_SESSION:-}"
ok "WIND_SESSION_ID 已写入"

# ── 7. 引导 sessionid + 冒烟测试 ────────────────────────────────────────
step "引导 sessionid"
PROMPT_SESSION="$CLI_SESSION"
if [[ -z "$PROMPT_SESSION" && -t 0 ]]; then
  read -r -p "  粘贴 WIND_SESSION_ID（回车跳过）: " PROMPT_SESSION
fi
if [[ -n "$PROMPT_SESSION" ]]; then
  set_env "WIND_SESSION_ID" "$PROMPT_SESSION"
  step "运行冒烟测试（20 个工具）…"
  HERMES_HOME="$PROFILE_DIR" "$HERMES_PYTHON" "$PROFILE_DIR/scripts/smoke_wind_tools.py" --session-id "$PROMPT_SESSION" \
    --quiet || true
else
  ok "跳过冒烟测试"
fi

# ── 7.5 注册 4 个 cron 日报任务 ─────────────────────────────────────────
# 工作日判断口子：BUSINESS_DAY_SCRIPT 为非空时，cron 任务先执行该脚本，
# 输出非工作日（非零退出）则跳过本次运行。当前默认不启用，等待工作日方案。
BUSINESS_DAY_SCRIPT="${BUSINESS_DAY_SCRIPT:-}"

step "注册 cron 日报任务"
declare -a CRON_JOBS=(
  "美股收盘市场简报|0 7 * * 1-5|us-market-close-briefing"
  "盘前机会挖掘|30 8 * * 1-5|premarket-opportunity-mining"
  "午间复盘|15 12 * * 1-5|midday-market-review"
  "盘后市场解读|0 16 * * 1-5|after-close-market-review"
)

CRON_OK=0
for entry in "${CRON_JOBS[@]}"; do
  IFS='|' read -r job_name schedule skill_name <<< "$entry"
  if "$HERMES_BIN" -p "$PROFILE_NAME" cron list 2>&1 | grep -q "$job_name"; then
    ok "cron 已存在: $job_name"
    continue
  fi
  prompt_text="使用 ${skill_name} 技能，生成${job_name}。"
  if [[ -n "$BUSINESS_DAY_SCRIPT" ]]; then
    prompt_text="先执行 $BUSINESS_DAY_SCRIPT 判断今日是否为工作日；若非工作日则直接回复跳过。${prompt_text}"
  fi
  if "$HERMES_BIN" -p "$PROFILE_NAME" cron create "$schedule" "$prompt_text" \
      --name "$job_name" --skill "$skill_name" --deliver local >/dev/null 2>&1; then
    ok "cron 已注册: $job_name ($schedule)"
    CRON_OK=$((CRON_OK + 1))
  else
    err "cron 注册失败: $job_name"
  fi
done
if [[ "$CRON_OK" -gt 0 ]]; then
  ok "新增 $CRON_OK 个 cron 任务（工作日判断待启用: BUSINESS_DAY_SCRIPT 为空）"
else
  ok "cron 均已存在或无新增"
fi

# ── 8. 收尾检查 ─────────────────────────────────────────────────────────
step "收尾检查"
FAILED=0
FINAL_PROFILE_LIST="$("$HERMES_BIN" profile list 2>&1 || true)"
echo "$FINAL_PROFILE_LIST" | grep -qw "$PROFILE_NAME" || { err "profile 缺失"; FAILED=1; }
SKILL_OUT="$("$HERMES_BIN" -p "$PROFILE_NAME" skills list --enabled-only 2>&1 || true)"
echo "$SKILL_OUT" | grep -q "hermes-agent" || { err "hermes-agent skill 缺失"; FAILED=1; }
WIND_COUNT="$(echo "$SKILL_OUT" | grep -c "│ wind " || true)"
[[ "$WIND_COUNT" -ge "$(ls "$SKILLS_SRC" | wc -l | tr -d ' ')" ]] || { err "wind 技能数量异常（$WIND_COUNT）"; FAILED=1; }
FINAL_PLUGIN_OUT="$("$HERMES_BIN" -p "$PROFILE_NAME" plugins list 2>&1 || true)"
echo "$FINAL_PLUGIN_OUT" | grep -q "wind_tool" || { err "插件 wind_tool 未注册"; FAILED=1; }
for f in "$PROFILE_DIR/SOUL.md" "$PROFILE_DIR/scripts/smoke_wind_tools.py" "$PROFILE_DIR/scripts/wind_login.py" "$PROFILE_DIR/.env" "$PROFILE_DIR/memories/MEMORY.md"; do
  [[ -f "$f" ]] || { err "$(basename "$f") 缺失"; FAILED=1; }
done
grep -q "^WIND_SESSION_ID=" "$PROFILE_ENV" || { err "WIND_SESSION_ID 未配置"; FAILED=1; }

echo
if [[ "$FAILED" == "0" ]]; then
  cp "$LOG_FILE" "$PROFILE_DIR/install.log" 2>/dev/null || true
  echo "${GREEN}✔ 安装完成。${NC} 使用: hermes -p $PROFILE_NAME chat"
  echo "  安装日志: $PROFILE_DIR/install.log"
else
  cp "$LOG_FILE" "$PROFILE_DIR/install.log" 2>/dev/null || true
  echo "${RED}✘ 安装完成，但 $FAILED 项未通过，请检查上方提示。${NC}"
  echo "  安装日志: $PROFILE_DIR/install.log"
  exit 1
fi
