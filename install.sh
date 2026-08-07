#!/usr/bin/env bash
#
# WindAgent 安装：
#   - 交互终端下运行 ./install.sh → 自动进入 Hermes 风格交互向导
#   - 带参数运行 → 静默安装（适合脚本/CI）
# 用法:
#   ./install.sh                     # 交互式向导（推荐）
#   ./install.sh --session-id <tok>  # 直接给定 token
#   ./install.sh --force             # profile 已存在时重建
#   ./install.sh doctor              # 安装健康检查（测试方案即检查结果）
#   ./install.sh doctor --full       # 健康检查 + 20 个工具冒烟测试（需已登录）
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
BUSINESS_DAY_SRC="$SCRIPT_DIR/scripts/is_business_day.py"

RED=$'\033[31m'; GREEN=$'\033[32m'; NC=$'\033[0m'
YELLOW=$'\033[33m'
step() { echo "${GREEN}==>${NC} $*"; }
ok()   { echo "  ${GREEN}✔${NC} $*"; }
err()  { echo "  ${RED}✘${NC} $*"; }
warn() { echo "  ${YELLOW}⚠${NC} $*"; }

# ── 安装日志（tee 到文件，方便调试）──────────────────────────────────────
LOG_FILE="${LOG_FILE:-/tmp/windagent-install.log}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
exec > >(tee -a "$LOG_FILE") 2>&1
echo "===== WindAgent install $(date '+%F %T') ====="

FORCE=0
CLI_SESSION=""
HAS_FLAGS=0
DOCTOR=0
DOCTOR_FULL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; HAS_FLAGS=1; shift ;;
    --session-id) CLI_SESSION="${2:-}"; HAS_FLAGS=1; shift 2 ;;
    doctor|--doctor) DOCTOR=1; HAS_FLAGS=1; shift ;;
    --full) DOCTOR_FULL=1; HAS_FLAGS=1; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

# 交互终端 + 无参数 → 转交 Hermes 风格向导
if [[ "$HAS_FLAGS" == "0" && -t 0 && -t 1 ]]; then
  exec python3 "$SCRIPT_DIR/scripts/windagent_setup.py"
fi

# ── doctor：安装健康检查（测试方案即检查结果）────────────────────────────
doctor_main() {
  echo "===== WindAgent doctor $(date '+%F %T') ====="
  step "doctor: WindAgent 安装健康检查"
  DOCTOR_FAILED=0

  # 冒烟测试需要 httpx：优先用 Hermes 自己的 venv Python（必有该依赖）
  HERMES_AGENT_REPO="$(echo "$("$HERMES_BIN" version 2>&1)" | grep -o 'Install directory: .*' | awk '{print $3}' || true)"
  HERMES_AGENT_REPO="${HERMES_AGENT_REPO:-$HERMES_ROOT/hermes-agent}"
  HERMES_PYTHON=""
  for candidate in "$HERMES_AGENT_REPO/venv/bin/python" "$HERMES_AGENT_REPO/.venv/bin/python"; do
    if [[ -x "$candidate" ]]; then HERMES_PYTHON="$candidate"; break; fi
  done
  HERMES_PYTHON="${HERMES_PYTHON:-python3}"

  step "1. Hermes 环境"
  if command -v "$HERMES_BIN" >/dev/null 2>&1 && "$HERMES_BIN" version >/dev/null 2>&1; then
    ok "hermes 可执行"
  else
    err "hermes 不可用（$HERMES_BIN）"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi

  step "2. profile: $PROFILE_NAME"
  PROFILE_LIST="$("$HERMES_BIN" profile list 2>&1 || true)"
  if echo "$PROFILE_LIST" | grep -qw "$PROFILE_NAME"; then
    ok "profile 存在"
  else
    err "profile 缺失（先运行 ./install.sh）"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi

  step "3. 技能（hermes-agent + wind）"
  SKILL_OUT="$("$HERMES_BIN" -p "$PROFILE_NAME" skills list --enabled-only 2>&1 || true)"
  if echo "$SKILL_OUT" | grep -q "hermes-agent"; then
    ok "hermes-agent 已启用"
  else
    err "hermes-agent skill 未启用"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi
  WIND_COUNT="$(echo "$SKILL_OUT" | grep -c "│ wind " || true)"
  WIND_EXPECT="$(ls "$SKILLS_SRC" 2>/dev/null | wc -l | tr -d ' ')"
  if [[ -n "$WIND_EXPECT" && "$WIND_COUNT" -ge "$WIND_EXPECT" ]]; then
    ok "wind 技能 $WIND_COUNT/$WIND_EXPECT 已注册"
  else
    err "wind 技能数量异常（$WIND_COUNT/$WIND_EXPECT）"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi

  step "4. 插件 wind_tool"
  PLUGIN_LIST="$("$HERMES_BIN" -p "$PROFILE_NAME" plugins list 2>&1 || true)"
  if echo "$PLUGIN_LIST" | grep -q "wind_tool"; then
    ok "插件已注册"
  else
    err "插件 wind_tool 未注册"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi

  step "5. 关键文件"
  for f in "$PROFILE_DIR/SOUL.md" "$PROFILE_DIR/memories/MEMORY.md" \
      "$PROFILE_DIR/scripts/smoke_wind_tools.py" "$PROFILE_DIR/scripts/wind_login.py" \
      "$PROFILE_DIR/scripts/is_business_day.py" "$PROFILE_DIR/.env"; do
    if [[ -f "$f" ]]; then
      ok "$(basename "$f")"
    else
      err "$(basename "$f") 缺失"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
    fi
  done

  step "6. 鉴权配置"
  PROFILE_ENV="$PROFILE_DIR/.env"
  if grep -q "^WIND_SESSION_ID=" "$PROFILE_ENV" 2>/dev/null; then
    SESSION_VAL="$(grep "^WIND_SESSION_ID=" "$PROFILE_ENV" | head -1 | cut -d= -f2-)"
    if [[ -n "$SESSION_VAL" ]]; then
      ok "WIND_SESSION_ID 已配置"
    else
      warn "WIND_SESSION_ID 为空（未登录，可在对话中运行 /wind-login）"
    fi
  else
    err "WIND_SESSION_ID 未配置"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi
  if grep -q 'profiles" / "windagent"' "$PROFILE_DIR/plugins/wind_tool/__init__.py" 2>/dev/null; then
    ok "插件 .env 优先读 windagent profile"
  else
    err "插件 .env 读取修复缺失"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi

  step "7. cron 日报（4 个 + 交易日门卫）"
  declare -a CRON_EXPECT=(
    "美股收盘市场简报|0 7 * * 1-5"
    "盘前机会挖掘|30 8 * * 1-5"
    "午间复盘|15 12 * * 1-5"
    "盘后市场解读|0 16 * * 1-5"
  )
  CRON_LIST="$("$HERMES_BIN" -p "$PROFILE_NAME" cron list 2>&1 || true)"
  for entry in "${CRON_EXPECT[@]}"; do
    IFS='|' read -r job_name sched <<< "$entry"
    if echo "$CRON_LIST" | grep -q "Name:.*$job_name"; then
      if echo "$CRON_LIST" | grep -qF "Schedule:  $sched"; then
        ok "$job_name ($sched)"
      else
        warn "$job_name 存在但调度不符"
      fi
    else
      err "$job_name 缺失"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
    fi
  done
  GATE_CHECK="$(python3 - "$PROFILE_DIR" <<'PY'
import json, sys
prof = sys.argv[1]
expected = {
    "美股收盘市场简报": "0 7 * * 1-5",
    "盘前机会挖掘": "30 8 * * 1-5",
    "午间复盘": "15 12 * * 1-5",
    "盘后市场解读": "0 16 * * 1-5",
}
try:
    data = json.load(open(prof + "/cron/jobs.json", encoding="utf-8"))
except Exception:
    print("FAIL jobs.json 不可读（cron 未注册）")
    sys.exit(0)
jobs = {j.get("name"): j for j in data.get("jobs", [])}
missing = [n for n in expected if n not in jobs]
nogate = [n for n in expected if n in jobs and "is_business_day" not in (jobs[n].get("prompt") or "")]
wrong = [n for n in expected if n in jobs and jobs[n].get("schedule_display") != expected[n]]
disabled = [n for n in expected if n in jobs and not jobs[n].get("enabled", True)]
if missing or nogate or wrong or disabled:
    print("FAIL " + json.dumps({"缺失": missing, "门卫缺失": nogate, "调度不符": wrong, "被禁用": disabled}, ensure_ascii=False))
else:
    print("OK 4 个任务均存在、启用、调度正确、门卫已挂载")
PY
)"
  if [[ "$GATE_CHECK" == OK* ]]; then
    ok "${GATE_CHECK#OK }"
  else
    err "${GATE_CHECK#FAIL }"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi
  GATEWAY_OUT="$("$HERMES_BIN" -p "$PROFILE_NAME" cron status 2>&1 || true)"
  if echo "$GATEWAY_OUT" | grep -q "not running"; then
    warn "gateway 未运行，cron 不会自动触发（hermes gateway install）"
  else
    ok "gateway 运行中"
  fi

  step "8. 交易日脚本 is_business_day.py"
  BD_CHECK="$(python3 - "$PROFILE_DIR/scripts" <<'PY'
import ast, json, subprocess, sys
from datetime import date
from pathlib import Path
scripts = Path(sys.argv[1])
script = scripts / "is_business_day.py"
cache_file = scripts / "wind-business-days.json"
try:
    ast.parse(script.read_text(encoding="utf-8"))
except Exception as e:
    print("FAIL 语法错误: %s" % e); sys.exit(0)
today = date.today()
year = str(today.year)
try:
    rc = subprocess.run([sys.executable, str(script), "--date", today.isoformat()], timeout=60).returncode
except Exception as e:
    print("FAIL 运行失败: %s" % e); sys.exit(0)
if rc == 2:
    print("FAIL 无法获取 %s 年休市表（检查网络或官方是否已发布当年安排）" % year); sys.exit(0)
try:
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    cal = cache.get(year, {})
    closed, opened = cal.get("closed", []), cal.get("open", [])
except Exception as e:
    print("FAIL 缓存读取失败: %s" % e); sys.exit(0)
if len(closed) < 5:
    print("FAIL 当年工作日休市表异常（仅 %d 天）" % len(closed)); sys.exit(0)
bad_closed = [d for d in closed if date.fromisoformat(d).weekday() >= 5]
bad_open = [d for d in opened if date.fromisoformat(d).weekday() < 5]
if bad_closed or bad_open:
    print("FAIL 数据异常: closed 含周末 %s / open 含工作日 %s" % (bad_closed[:3], bad_open[:3])); sys.exit(0)
expected = 0 if (today.isoformat() in opened or (today.weekday() < 5 and today.isoformat() not in closed)) else 1
if rc != expected:
    print("FAIL 判定不一致: 脚本=%d 期望=%d" % (rc, expected)); sys.exit(0)
print("OK 语法/缓存/判定一致（%s: %d 个工作日休市, open=%d）" % (year, len(closed), len(opened)))
PY
)"
  if [[ "$BD_CHECK" == OK* ]]; then
    ok "${BD_CHECK#OK }"
  else
    err "${BD_CHECK#FAIL }"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
  fi

  if [[ "$DOCTOR_FULL" == "1" ]]; then
    step "9. 冒烟测试（20 个工具，需已登录 + 网络）"
    if [[ -z "${SESSION_VAL:-}" ]]; then
      warn "WIND_SESSION_ID 为空，跳过冒烟（先运行 /wind-login）"
    elif "$HERMES_PYTHON" "$PROFILE_DIR/scripts/smoke_wind_tools.py" --session-id "$SESSION_VAL" --quiet; then
      ok "20 个工具连通"
    else
      err "冒烟测试失败（检查 session 是否过期）"; DOCTOR_FAILED=$((DOCTOR_FAILED + 1))
    fi
  fi

  echo
  if [[ "$DOCTOR_FAILED" == "0" ]]; then
    echo "${GREEN}✔ doctor 全部通过。${NC} 详见 docs/install-doctor.md"
  else
    echo "${RED}✘ doctor 发现 $DOCTOR_FAILED 项问题，请按上方提示处理。${NC}"
  fi
  return "$DOCTOR_FAILED"
}

if [[ "$DOCTOR" == "1" ]]; then
  doctor_main
  exit $?
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
if [[ -f "$BUSINESS_DAY_SRC" ]]; then
  cp "$BUSINESS_DAY_SRC" "$PROFILE_DIR/scripts/is_business_day.py"
fi
ok "SOUL.md / MEMORY.md / smoke / login / 交易日脚本已就位"

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
# 交易日判断：BUSINESS_DAY_SCRIPT 为非空时，cron 任务先执行该脚本，
# 非交易日（非零退出）则跳过本次运行。默认用 is_business_day.py（上交所官网休市安排）。
BUSINESS_DAY_SCRIPT="${BUSINESS_DAY_SCRIPT:-$PROFILE_DIR/scripts/is_business_day.py}"

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
  ok "新增 $CRON_OK 个 cron 任务（交易日判断: is_business_day.py）"
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
for f in "$PROFILE_DIR/SOUL.md" "$PROFILE_DIR/scripts/smoke_wind_tools.py" "$PROFILE_DIR/scripts/wind_login.py" "$PROFILE_DIR/scripts/is_business_day.py" "$PROFILE_DIR/.env" "$PROFILE_DIR/memories/MEMORY.md"; do
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
