---
name: 万得登录
description: 万得登录与 session 管理：手机号+验证码登录获取 session id、保存免登录凭证、静默续期。触发词：登录、获取 session、重新登录、验证码登录、session 过期、token 失效、更新 session。用于 Hermes 不依赖 WindClaw 桌面端自主登录 Wind 数据服务。
metadata:
  keywords: "登录，session，验证码，免登录，loginToken，静默续期，重新登录"
  source: windclaw
allowed-tools: terminal
---

# 万得登录（手机号 + 验证码 → session id）

## 何时使用

- 用户要求登录万得、获取/更新 Wind session id。
- 数据工具返回 401/403（session 失效）时需要重新登录或续期。
- 新机器部署后首次登录，或不依赖 WindClaw 桌面端独立登录。

## 核心工具

使用 `scripts/wind_login.py`（已随安装复制到 profile 的 `scripts/` 目录）：

```bash
# 发送验证码
python3 scripts/wind_login.py send <手机号>

# 手机号 + 验证码登录（保存 session 到 .env，并保存免登录凭证）
python3 scripts/wind_login.py login <手机号> <验证码> --save --save-login

# 查看/续期免登录凭证（session 过期时无需再收验证码）
python3 scripts/wind_login.py cred --profile windagent --refresh
```

如果脚本不在当前目录，用完整路径：`python3 ~/.hermes/profiles/windagent/scripts/wind_login.py ...`

## 执行流程

### 第一步：确认手机号

- 用户已给手机号 → 直接用。
- 用户没给 → **用 clarify 工具询问**："请提供要登录的万得手机号"。

### 第二步：发送验证码

```bash
python3 scripts/wind_login.py send <手机号>
```

成功提示"验证码已发送"后进入下一步。

### 第三步：向用户索要验证码（关键交互）

**必须用 clarify 工具**向用户提问，等待用户回复验证码，不要假设或编造：

```text
请回复刚刚收到的 6 位短信验证码
```

clarify 会阻塞等待用户输入，用户回复后 agent 继续。若用户表示没收到或验证码过期，重新执行第二步。

### 第四步：登录并保存

```bash
python3 scripts/wind_login.py login <手机号> <验证码> --save --save-login
```

- `--save`：把 session id 写入 `~/.hermes/profiles/windagent/.env` 的 `WIND_SESSION_ID`。
- `--save-login`：把 loginToken 存入 `.wind-login.json`（免登录凭证）。

### 第五步：验证 session

登录成功后建议快速验证（可选）：

```bash
python3 scripts/smoke_wind_tools.py --session-id <新session> --quiet
```

或直接提示用户尝试用 Wind 工具取数。

## 边界情况

- **验证码错误/过期**：脚本返回对应错误（1001=错误、1002=过期、1003=频繁），提示用户重新发码或重试。
- **手机号未注册**：retvalue 1004，告知用户该号码未开通万得账号。
- **session 过期后续期**：若 `.wind-login.json` 已有 loginToken，运行 `cred --refresh` 即可免验证码换新 session，无需走完整登录。
- **脚本不在路径**：先 `ls ~/.hermes/profiles/windagent/scripts/wind_login.py` 确认；若缺失，用项目内 `scripts/wind_login.py` 或重新运行 install.sh。

## 安全说明

- session id 与 loginToken 都是敏感凭证，只写入 `~/.hermes/profiles/windagent/.env` 和 `.wind-login.json`（权限 600），不要输出完整 token 到对话。
- 展示时只显示前几位（如 `dc1a****`）。
