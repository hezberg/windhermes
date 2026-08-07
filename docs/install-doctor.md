# WindAgent 安装测试方案 / doctor 检查

本文档既是**安装脚本新增内容的测试方案**，也是 `./install.sh doctor` 检查项的定义与结果说明。doctor 输出即本方案的执行结果：`✔` 通过、`✘` 失败（退出码非 0）、`⚠` 提示（不阻断）。

## 运行方式

```bash
./install.sh doctor          # 健康检查（只读，不修改安装）
./install.sh doctor --full   # 健康检查 + 20 个工具冒烟测试（需已登录 + 网络）
```

## 覆盖范围：本轮新增内容

| 新增内容 | 位置 | 说明 |
|---|---|---|
| 交易日判断脚本 | `scripts/is_business_day.py` | 抓取上交所官方休市安排，缓存 + 双例外（工作日休市 / 周末开市）判断 |
| cron 4 个日报任务 | `install.sh` 步骤 7.5 | 美股收盘简报、盘前机会挖掘、午间复盘、盘后市场解读 |
| 交易日门卫 | `install.sh` 步骤 7.5 | cron prompt 前置执行 `is_business_day.py`，非交易日跳过 |
| 交易日脚本复制 | `install.sh` 步骤 5 | 随安装复制到 profile `scripts/` |
| 收尾检查扩充 | `install.sh` 步骤 8 | 新增 `is_business_day.py` 存在性检查 |
| 插件 .env 读取修复 | `plugins/wind-bridge/__init__.py` | `_env_value` 显式优先读 windagent profile 的 `.env` |

## 检查矩阵（doctor 自动化）

| # | 检查项 | 方法 | 通过标准 | 不通过的影响 |
|---|---|---|---|---|
| 1 | Hermes 可执行 | `hermes version` | 退出码 0 | 无法使用 |
| 2 | profile `windagent` 存在 | `hermes profile list` | 包含 windagent | 未安装 |
| 3 | 技能注册 | `skills list --enabled-only` | hermes-agent 启用，wind 技能数 ≥ 源目录数 | 技能缺失 |
| 4 | 插件 `wind_tool` | `plugins list` | 包含 wind_tool | 20 个工具不可用 |
| 5 | 关键文件 | 逐个 `-f` 检查 | 6 个文件齐全（SOUL / MEMORY / smoke / login / 交易日脚本 / .env） | 对应功能缺失 |
| 6 | 鉴权配置 | `.env` grep | `WIND_SESSION_ID=` 存在；空值 = ⚠ 未登录 | 数据工具 401 |
| 7 | 插件 .env 读取修复 | grep `profiles" / "windagent"` | 特征存在 | 读到旧 session |
| 8 | cron 4 个任务 | `cron list` + `cron/jobs.json` | 名字、调度、enabled 全部匹配 | 日报不生成 |
| 9 | 交易日门卫 | `jobs.json` 的 prompt 字段 | 每个任务 prompt 含 `is_business_day.py` | 节假日也会跑日报 |
| 10 | gateway 状态 | `cron status` | 非阻断：未运行 = ⚠ 提示 | cron 不会自动触发 |
| 11 | 交易日脚本语法 | `ast.parse` | 无语法错误 | 脚本不可用 |
| 12 | 交易日脚本功能 | 运行「今日」并校验缓存 | 退出码与缓存推导一致；closed 只含工作日、open 只含周末；当年 closed ≥ 5 天 | 判定错误 |
| 13 | 冒烟测试（仅 `--full`） | `smoke_wind_tools.py` | 20 个工具连通 | session 过期或网络问题 |

## 需要手动 / 条件触发的事项（doctor 不自动覆盖）

| 事项 | 原因 | 触发方式 |
|---|---|---|
| cron 真实定时触发 | 需 gateway 服务运行 | `hermes gateway install` 后观察日志 |
| 跨年数据更新 | 官方每年 12 月发布次年安排 | 新年首个交易日自动拉取；若当年未发布，doctor 报 ⚠/✘ 并提示 |
| 真实行情连通性 | 需有效 session + 网络 | `./install.sh doctor --full` |
| 新机器首装 | 安装流程本身 | 由 `install.sh` 步骤 8 收尾检查覆盖，doctor 复查安装结果 |

## 测试记录

### 2026-08-07 本地实测（完整安装后 `./install.sh doctor`）

- Hermes 环境、profile、技能（105/105）、插件 wind_tool、关键文件（6/6）、鉴权配置、插件 .env 修复：✔ 全部通过
- cron 4 个日报任务：✔ 均存在、启用、调度正确、门卫已挂载（jobs.json 校验）
- 交易日脚本：✔ 语法 / 缓存 / 判定一致（2026: 19 个工作日休市, open=0）
- ⚠ 2 项（不阻断）：WIND_SESSION_ID 为空（未登录）；gateway 未运行（cron 不会自动触发）
- 退出码 0，全部通过

### doctor 开发过程修复的 2 个缺陷

1. 失败计数用 `DOCTOR_FAILED=1` 置位而非累加，汇总永远显示 1 项 → 改为 `$((DOCTOR_FAILED + 1))`
2. `hermes plugins list | grep -q` 直连管道：`grep -q` 命中即退出，SIGPIPE 掐断 hermes 输出，`pipefail` 下误判失败 → 改为先捕获再 grep

实测结论：doctor 能覆盖全部新增内容的静态与逻辑检查；「cron 真实触发」「跨年数据」「真实行情连通性」三类需运行时条件，见上方「需要手动 / 条件触发的事项」。
