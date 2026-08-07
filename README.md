# windclaw_hermes

把 WindClaw 的金融数据工具和投研技能迁移到 Hermes，可部署在任意一台装了 Hermes 的机器上（无需安装 WindClaw）。

## 包含什么

- `plugins/wind-bridge/`：Hermes 插件（安装时注册为 `wind_tool`），提供 20 个 Wind 工具
  - 数据/资讯/研究 4 个：`get_wind_data` / `document_search` / `wind_financial_reference_content` / `wind_web_search`
  - 实时行情 3 个：`quote_get_stock/sector/market_realtime_performance`
  - WindClaw MCP 13 个：个股实时/公司画像/财务/估值/盈利预测/资金流/技术面/公司动态/行业研究/市场板块分析/公众号文章等
- `skills/wind/`：104 个投研技能（中文名，按 agentskills.io 规范），另有积分查询、积分流水、4 个 cron 日报技能
- `SOUL.md`：WindClaw 金融投研人格（安装时覆盖到 profile）
- `MEMORY.md`：会话记忆引导（安装时覆盖到 profile，§ 分隔条目格式）
- `install.sh` + `scripts/windagent_setup.py`：一键安装（静默 / 交互向导）
- `scripts/smoke_wind_tools.py`：20 个工具的连通性冒烟测试
- `scripts/wind_login.py`：手机号+验证码登录 → session id，支持免登录静默续期
- `scripts/update_wind_session.sh`：异机场景下用 scp 拉取最新 token

## 前置条件

- 目标机器已安装并启动过 Hermes（`hermes version` 可运行）
- 一个有效的万得 sessionid（见下文「获取 sessionid」）

## 安装

把整个 `windclaw_hermes` 目录拷到目标机器，然后运行：

### 交互式安装（推荐）

终端直接运行，进入 Hermes 风格的交互向导（自动检测 WindClaw 会话文件、确认 profile、引导 sessionid）：

```bash
./install.sh
```

也可以直接调用向导：

```bash
python3 scripts/windagent_setup.py
```

常用参数：

```bash
./install.sh --session-id <token>        # 静默安装，直接给定 token
./install.sh --force                     # profile 已存在时重建
python3 scripts/windagent_setup.py --yes # 向导全默认（不重建 profile）
```

安装过程会：创建 `windagent` profile（`--no-skills` 空 profile）、补回 hermes-agent skill、复制 104 个 wind 技能、注册插件 `wind_tool`、覆盖 SOUL.md / MEMORY.md、复制冒烟脚本、配置 `.env`，最后跑 20 个工具的冒烟测试。

### 场景 A：WindClaw 和 Hermes 在同一台机器（自动同步）

安装脚本会自动发现 WindClaw 的会话文件并写入 `~/.hermes/profiles/windagent/.env` 的 `WIND_SESSION_FILE`，每次调用实时读取，token 轮换自动生效。

如果本机有多个 WindClaw 用户目录，可在安装时手动指定：

```bash
ls ~/.openclaw-windclaw/users/*/openclaw/.windclaw-aigw-session
```

### 场景 B：WindClaw 和 Hermes 在不同机器（scp 同步）

先在 **WindClaw 机器** 上确认会话文件路径：

```bash
ls ~/.openclaw-windclaw/users/*/openclaw/.windclaw-aigw-session
```

在 **Hermes 机器** 上配置 scp 源路径到 profile 的 `.env`：

```bash
WIND_SCP_SOURCE=user@WindClaw机器IP:/绝对路径/.windclaw-aigw-session
```

**要求**：两台机器之间配好 SSH 免密，让 Hermes 机器能直接 `scp`：

```bash
ssh-keygen -t ed25519            # Hermes 机器上生成
ssh-copy-id user@WindClaw机器IP  # 把公钥装到 WindClaw 机器
```

**换 token**（sessionid 过期时）：

```bash
./scripts/update_wind_session.sh
```

也可以加入 cron 定期同步（比如每小时）。

## 获取 sessionid

- 在 WindClaw 机器上：`cat ~/.openclaw-windclaw/users/*/openclaw/.windclaw-aigw-session`
- 或从万得 App / WindClaw 客户端登录态获取（具体入口以万得官方为准）
- 或直接用手机号+验证码登录获取（不依赖 WindClaw）：

```bash
python3 scripts/wind_login.py send 你的手机号
python3 scripts/wind_login.py login 你的手机号 验证码 --save --save-login
```

## 免登录（静默续期）

`wind_login.py` 登录成功后会把 `loginToken` 存入 `~/.hermes/profiles/windagent/.wind-login.json`
（权限 600）。之后 session 过期时无需再收验证码，一条命令静默续期：

```bash
python3 scripts/wind_login.py cred --profile windagent --refresh
```

该机制逆向自 WindClaw 的 Visa 认证（verifyMode=3 + loginToken），与 WindClaw
桌面端"每天打开不用登录"是同一套链路，可跨设备使用。

## 验证

重启 Hermes 后：

```bash
hermes profile list                 # windagent 应存在
hermes -p windagent plugins list    # wind_tool 应 enabled (0.2.0)
hermes -p windagent skills list --enabled-only   # 104 个 wind 技能 + hermes-agent
```

对话里测试：

- `用 quote_get_stock_realtime_performance 查一下 600519.SH 的实时行情`
- `用 stock_get_company_finance_analysis 分析东山精密的财务`
- `查一下万得积分余额`
- `用盘后市场解读生成今天的收盘总结`

## 积分与 cron 技能

积分脚本可直接运行：

```bash
cd skills/wind/万得积分余额查询 && python3 scripts/check_balance.py
cd skills/wind/万得积分流水查询 && python3 scripts/query_flow.py --page 1 --page-size 20
```

4 个日报技能（美股收盘市场简报、盘前机会挖掘、午间复盘、盘后市场解读）保留了 WindClaw 的原始 prompt 框架，并在 `metadata.cron_schedule` / `cron_tz` 中记录建议调度时间（周一至周五，北京时间），可在 Hermes 里配置 cron 定时调用对应技能。

## 敏感信息

- `WIND_SESSION_ID` 存在 `~/.hermes/profiles/windagent/.env`（安装脚本自动创建，权限 600）
- 异机部署的 `WIND_SCP_SOURCE` / `WIND_SESSION_FILE` 也存于该 profile 的 `.env`
- 不要把 token 提交到任何仓库或聊天记录
