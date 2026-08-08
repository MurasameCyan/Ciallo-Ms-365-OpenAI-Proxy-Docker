# Ciallo Ms-365 OpenAI Proxy Docker · 多租户版（Multi-Account）

来都来了 不点个⭐再走吗~?

将 Microsoft 365 Copilot 暴露为 **OpenAI / Anthropic 兼容 API** 的 Docker 代理服务。**多租户版**：可管理多个 M365 账户与多个 API Key，给多人共用；每个 Key 绑定一个账户，并拥有独立的对话模式与提示词。

> 这是主项目的 `multi` 分支，镜像标签为 `:multi`。单租户（单账户单 Key）请用 `main` 分支 / `:latest` 镜像。

## 目录

- [功能概览](#功能概览)
- [可调用模型目录](#可调用模型目录)
- [快速部署](#快速部署)
- [API 端点](#api-端点)
- [按需刷新机制](#按需刷新机制)
- [环境变量](#环境变量)
- [客户端配置](#客户端配置)
- [认证](#认证)
- [多租户使用](#多租户使用)
- [速率限制](#速率限制)
- [出站代理](#出站代理)
- [媒体 / Designer 授权抓取](#媒体--designer-授权抓取)
- [持久会话与上下文优化](#持久会话与上下文优化)
- [提示词增强与兜底重试](#提示词增强与兜底重试)
- [个人版（消费者版 Copilot）账户](#个人版消费者版-copilot账户)
- [企业版与个人版的差异](#企业版与个人版的差异)
- [架构](#架构)
- [License](#license)
- [致谢](#致谢)

## 功能概览

- **多账户池** — 每个账户拥有独立 M365 Token 与 Chromium 刷新配置
- **多 API Key** — 每个 Key 绑定一个账户，可单独设置对话模式 / 提示词，随时启用停用
- **模型即模式** — 每个对话模式通过 `GET /v1/models` 暴露为独立模型（含「-持续」持久会话变体）
- **按需串行刷新** — RT 优先纯 HTTP 换 Token；失败再拉起单个 Chromium，用完即关，峰值内存接近单租户
- **分层界面** — `/admin` 运营总控台（账户池 + Key 管理），`/` 用户自助页（用自己的 Key 管理对话模式、提示词、账户 Token）
- **按需刷新** — 空闲自动暂停，有 `/v1/` 请求时自动唤醒，降低账号风险
- **油猴脚本** — Tampermonkey 一键推送 Token + Cookie（及 media / designer 凭据）
- **增量上下文** — 复用会话时只发送新增内容，不重发完整历史
- **会话持久化** — 容器重启后旧对话仍可正确续接
- **提示词增强** — Web 可调 tool_call 行为与系统提示词，持久保存；服务端兜底重试 + 散文兜底救援（半成品）
- **速率限制** — 令牌桶按 Key 限流，防止单个客户端跑飞拖垮共用账户；全局默认值 + 单 Key 覆盖
- **出站代理** — Web 可配 http/socks5 代理，覆盖 WebSocket 与 Chromium；本地 CDP 始终直连
- **API Key 认证** + **Web 管理页面**

## 可调用模型目录

`GET /v1/models` 会按当前全局「对话模式列表」生成模型清单。每个模式产出 **2 个模型 ID**：

| 变体 | 模型 ID 形态 | 会话行为 |
| ---- | ------------ | -------- |
| 普通 | `<显示名>` | 默认按首条用户消息哈希自动分组会话；首轮无 assistant 时开新线程 |
| 持续 | `<显示名>-持续` | 同一 API Key 下固定复用该模型会话（也兼容底层后缀 `:persist`） |

显示名中的空格会自动转为下划线，便于客户端当作 model id 使用。也可直接用 **底层 tone 值**（如 `Magic`、`Gpt_5_5_Chat`、`Claude_Sonnet`）请求；未匹配到任何模式时，回退到该 Key / 全局默认对话模式。

### 默认内置模式（开箱即用）

与代码中 `TONE_OPTIONS`（经规范化后）一致。可用 `curl -H "Authorization: Bearer <KEY>" http://localhost:8000/v1/models` 核对当前实例实际列表。

| 底层 tone（发给 M365） | 显示名 / 普通模型 ID | 持续模型 ID | 说明 |
| ---------------------- | -------------------- | ----------- | ---- |
| `Magic` | `Copilot_自动` | `Copilot_自动-持续` | Copilot 自动选模 |
| `Chat` | `Copilot_快速答复` | `Copilot_快速答复-持续` | Copilot 快速答复 |
| `Reasoning` | `Copilot_深度思考` | `Copilot_深度思考-持续` | Copilot 深度思考 |
| `Claude_Sonnet` | `claude-sonnet-4-6` | `claude-sonnet-4-6-持续` | Claude Sonnet |
| `Claude_Sonnet_Reasoning` | `claude-sonnet-4-5_Reasoning` | `claude-sonnet-4-5_Reasoning-持续` | Claude Sonnet 思考 |
| `Claude_Fable` | `claude-fable-5` | `claude-fable-5-持续` | Claude Fable |
| `Claude_Opus` | `claude-opus` | `claude-opus-持续` | Claude Opus |
| `Gpt_5_6_Reasoning` | `gpt-5.6_Reasoning` | `gpt-5.6_Reasoning-持续` | GPT 5.6 思考 |
| `Gpt_5_5_Chat` | `gpt-5.5_Chat` | `gpt-5.5_Chat-持续` | GPT 5.5 快速 |
| `Gpt_5_5_Reasoning` | `gpt-5.5_Reasoning` | `gpt-5.5_Reasoning-持续` | GPT 5.5 思考 |
| `Gpt_5_4_Chat` | `gpt-5.4_Chat` | `gpt-5.4_Chat-持续` | GPT 5.4 快速 |
| `Gpt_5_4_Reasoning` | `gpt-5.4_Reasoning` | `gpt-5.4_Reasoning-持续` | GPT 5.4 思考 |
| `Gpt_5_3_Chat` | `gpt-5.3_Chat` | `gpt-5.3_Chat-持续` | GPT 5.3 快速 |
| `Gpt_5_2_Chat` | `gpt-5.2_Chat` | `gpt-5.2_Chat-持续` | GPT 5.2 快速 |
| `Gpt_5_2_Reasoning` | `gpt-5.2_Reasoning` | `gpt-5.2_Reasoning-持续` | GPT 5.2 思考 |

共 **30** 个默认可选模型 ID（15 模式 × 2 变体）。

某个模式能不能用由 M365 侧的 rollout 决定，与本项目无关：M365 拒绝服务的模式会返回 **400** 并在错误里点名该模式，不会静默回一句「Sorry, I wasn't able to respond to that.」当成模型回复。用 400 而非 502，是因为重试改变不了上游的拒绝——502 会让客户端把它当成网关故障反复重试。传输层故障（空闲超时、断流）与凭据问题仍然是 502。想知道当前账号实际能用哪些，跑仓库根目录的 `scan_tones.py`。

### 请求示例

```bash
# 列出模型
curl -s -H "Authorization: Bearer YOUR_API_KEY" http://localhost:8000/v1/models | jq '.data[].id'

# Chat Completions：选 GPT 5.5 Chat + 自动分组会话
curl -s http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.5_Chat","messages":[{"role":"user","content":"你好"}]}'

# 同一模式的持续会话（也可用 Gpt_5_5_Chat:persist）
curl -s http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.5_Chat-持续","messages":[{"role":"user","content":"继续上面的话题"}]}'
```

### 能力说明

- **多模态输入**：列表中每个模型都声明 `vision` / `input_modalities: text+image`（底层均为 M365 多模态后端）。部分客户端（如 CherryStudio）可能仍依赖内置模型名正则，需在客户端手动开启图片。
- **响应中的 `model` 字段**：返回体里的 `model` 使用运行时别名（默认 `m365-copilot`，可由 `M365_MODEL_ALIAS` 或 Key 级 `model_alias` 覆盖），**不等于**请求时选用的对话模式 ID。
- **可自定义模式列表**：在 `/admin` → 运行设置中编辑「对话模式列表」，格式每行：`底层tone值 | 显示名`。保存后立即反映到 `/v1/models` 与解析逻辑；显示名会作为模型 ID，空格转下划线，每个模式仍生成普通 + `-持续` 两个模型。

### 与「Key 默认对话模式」的关系

- 请求 **`model` 命中** 某显示名 / 底层 tone → 使用该模式。
- 请求 **未命中**（任意字符串、旧别名等）→ 使用该 API Key 在 Web 上配置的默认 tone，否则用全局默认（通常为 `Magic`）。
- 因此客户端既可「按模型选模式」，也可继续用固定模型名 + Web 侧默认模式。

## 快速部署

### 1. 创建 .env 文件

```bash
cp .env.example .env
```

按需填写 `ADMIN_PASSWORD`、`API_KEY`（见 [环境变量](#环境变量)）。

### 2. 启动服务

```bash
docker compose up -d
```

服务在 `http://localhost:8000` 启动。打开浏览器：

- `/` — 用户自助页（用自己的 API Key 登录）
- `/admin` — 运营总控台（管理密码：`ADMIN_PASSWORD`，未设则回退 `API_KEY`）

### 3. 推送 Token

#### 方式一：油猴脚本（推荐）

1. 安装 [Tampermonkey BETA](https://www.tampermonkey.net/) 浏览器扩展
2. 点击 [一键脚本](https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/main/get_token.user.js) 安装油猴脚本
3. 打开 [M365 Copilot](https://m365.cloud.microsoft/chat) 并登录你的 M365 账号
4. 在 Copilot 对话框中**输入任意字符**触发 WebSocket 连接
5. 页面右上角弹出推送面板
6. 点击 **One-Click Setup** — 自动推送 Cookie + Token 到代理服务

> **首次需要先推送 Cookie** 让 Chromium 登录 M365，之后 Auto Capture 即可自动刷新 Token。

#### 方式二：手动粘贴

1. 在浏览器中打开 M365 Copilot
2. F12 → Network → WS → 找到 `wss://substrate.office.com/...` 连接
3. 复制 URL 中的 `access_token` 参数值
4. 粘贴到 Web 页面的 **Update Token** 输入框，点击更新

> **注意：手动导入无法自动刷新 Token，也无法启用按需刷新。**

#### 查看状态

Web 页面显示 Token 有效性与刷新相关状态。

> **Check Login / Auto Capture / Cookie 注入依赖共享 admin Chromium（9222），仅在 `ENABLE_ADMIN_CDP=true` 时可用**。默认多租户部署下这些按钮对应的端点未注册；请改用 `/` 用户自助页推送账户 Token / Cookie，刷新由每账户独立 Chromium 或 RT 承担。

## API 端点

<details>
<summary>展开查看全部 API 端点</summary>

### OpenAI / Anthropic 兼容 API

| 端点 | 说明 |
| ---- | ---- |
| `GET /v1/models` | 模型列表（对话模式 × 普通/持续） |
| `POST /v1/chat/completions` | OpenAI Chat Completions（支持流式） |
| `POST /v1/responses` | OpenAI Responses API（支持流式） |
| `POST /v1/messages` | Anthropic Messages API（支持流式） |

### 会话与页面

| 端点 | 说明 |
| ---- | ---- |
| `GET /healthz` | 健康检查 |
| `GET /` | 用户自助页面（API Key 登录） |
| `GET /admin` | 运营总控台页面（管理密码登录） |
| `POST /admin/login` | 运营总控台登录 |
| `POST /admin/logout` | 运营总控台登出 |

### 管理端点 — 账户池与 API Key

| 端点 | 说明 |
| ---- | ---- |
| `GET POST /admin/accounts` | 列出 / 添加账户 |
| `POST /admin/accounts/{id}/token` | 更新账户 Token |
| `POST /admin/accounts/{id}/token/clear` | 清除账户 Token |
| `POST /admin/accounts/{id}/rename` | 重命名账户 |
| `POST /admin/accounts/{id}/refresh` | 立即刷新账户 Token（CDP） |
| `POST /admin/accounts/{id}/cookie-refresh` | 用 Cookie 拉起 Chromium 刷新 |
| `DELETE /admin/accounts/{id}` | 删除账户（解绑其 Key） |
| `GET POST /admin/keys` | 列出 / 新建 API Key |
| `POST /admin/keys/{id}` | 更新 Key（绑定/模式/启停等） |
| `POST /admin/keys/{id}/regenerate` | 重置 Key 明文 |
| `DELETE /admin/keys/{id}` | 删除 API Key |

### 管理端点 — 设置与可观测性

| 端点 | 说明 |
| ---- | ---- |
| `GET /admin/token/status` | Token 有效性与自动刷新状态 |
| `POST /admin/token/update` | 手动推送 Token |
| `POST /admin/token/auto-refresh-toggle` | 切换自动刷新开关 |
| `GET POST /admin/tone` | 查询 / 设置默认对话模式 |
| `GET POST /admin/tool-prompt` | 查询 / 设置提示词增强 |
| `GET POST /admin/system-prompt` | 查询 / 设置系统提示词 |
| `GET POST /admin/runtime-settings` | 查询 / 设置运行设置（含对话模式列表、日志开关等） |
| `GET /admin/call-log` | API 调用记录 |
| `POST /admin/call-log/clear` | 清空调用记录 |
| `GET /admin/summary` | 总览统计 |
| `GET /admin/stats` | 明细统计 |
| `GET /admin/metrics-history` | 指标历史 |
| `POST /admin/metrics-history/clear` | 清空指标历史 |
| `GET /admin/media-proxy/events` | 媒体代理事件 |
| `POST /admin/media-proxy/events/clear` | 清空媒体代理事件 |
| `GET POST /admin/capture-payload` | 查询 / 接收模式抓包数据 |
| `POST /admin/capture-payload/clear` | 清空抓包数据 |
| `GET POST /admin/capture-toggle` | 查询 / 切换抓包开关 |

### 管理端点 — 共享 CDP（仅 `ENABLE_ADMIN_CDP=true` 时注册）

> 默认多租户部署下 `ENABLE_ADMIN_CDP=false`，以下端点**不注册**（调用返回 404），刷新由每账户独立 Chromium 承担。设为 `true` 才启用 9222 共享浏览器及这些端点。

| 端点 | 说明 |
| ---- | ---- |
| `POST /admin/token/auto-capture` | 触发共享 Chromium 捕获 Token |
| `POST /admin/cookie/inject` | 注入 Cookie 到共享 Chromium |
| `GET /admin/chromium/login-status` | 共享 Chromium 登录状态 |
| `POST /admin/chromium/logout` | 共享 Chromium 登出 |

### 用户自助端点（用自己的 API Key 认证）

| 端点 | 说明 |
| ---- | ---- |
| `POST /user/login` | 用户页登录 |
| `POST /user/repassword` | 修改自己的登录密码 |
| `GET /user/me` | 查询自己的 Key 信息与绑定账户状态 |
| `POST /user/tone` | 设置自己的对话模式 |
| `POST /user/tool-prompt` | 设置自己的提示词增强 |
| `POST /user/system-prompt` | 设置自己的系统提示词 |
| `POST /user/account/token` | 推送/更新绑定账户的 Token（无则自动创建） |
| `POST /user/account/cookies` | 推送绑定账户的 Cookie（供 CDP 刷新） |
| `POST /user/account/consumer` | 推送个人版（消费者版 Copilot）凭据，把账户切到 consumer provider |
| `POST /user/account/refresh-token` | 立即刷新绑定账户的 Token |
| `POST /user/account/media-auth` | 推送媒体（图片）访问凭据 |
| `POST /user/account/designer-auth` | 推送 Designer 访问凭据 |
| `POST /user/account/logout` | 登出绑定账户（清凭据） |
| `POST /user/account/unbind` | 解绑当前账户 |
| `POST /user/regenerate-key` | 重置自己的 API Key |

</details>

## 按需刷新机制

默认采用按需刷新模式，降低长时间保持连接的账号风控：

1. **容器启动不自动刷新** — `auto_refresh` 初始为关闭状态，无后台 token 刷新活动
2. **`/v1/` 请求触发按需刷新** — 当有 `/v1/` API 请求且 Token 过期或不存在时，中间件**同步刷新** Token（先 RT 后 CDP，见下），请求等待刷新完成后继续
3. **空闲自动暂停** — 超过 `IDLE_TIMEOUT_MINUTES`（默认 30 分钟）无 `/v1/` 请求时，自动暂停刷新循环
4. **再次请求自动唤醒** — 下一个 `/v1/` 请求到来时，自动唤醒刷新
5. **Web 按钮控制** — 可通过 Web 页面手动启用/暂停自动刷新

### 两级刷新链路：RT 优先 → CDP 回退

刷新到期（或强制刷新）时，按以下顺序取新 Token：

1. **RT 快速刷新（首选，无浏览器）** — 账户若持有 OAuth2 `refresh_token`，直接向 AAD `oauth2/v2.0/token` 端点做纯 HTTP 交换，换回新的 substrate access token。**不拉起 Chromium、不消耗 Copilot 配额**，速度快、开销低。交换同时会轮换 `refresh_token` 并持久化，使刷新链持续续期；并带身份守卫（换回的身份与账户 email 不符则拒绝）。RT 由油猴脚本从 M365 token 响应中捕获后推送（`/user/account/token`、`/user/account/cookies`）。
2. **CDP 刷新（回退）** — 当账户没有 RT、RT 链已失效（AAD 返回 `invalid_grant` 等）或 HTTP 交换出错时，才回退到拉起该账户专属 Chromium profile（独立 CDP 端口 9322+）抓取新 Token。

> media / designer（图片、Designer）Token 不经 RT 产生，由 CDP 媒体捕获路径按需懒保活。

> **注意：按需刷新唤醒需要先刷新 Token，首轮回复等待时间会增加**；RT 路径通常只需一次 HTTP 往返，明显快于 CDP 拉起浏览器。

```
/v1/ 请求 → 记录 last_request_time → 检查 token 有效性
                                        ├─ 有效 → 正常处理
                                        └─ 过期/缺失 →
                                            ├─ 有 RT → HTTP 交换 substrate token（无浏览器）
                                            │           ├─ 成功 → 轮换并持久化 RT → 正常处理
                                            │           └─ 失败 → 回退 CDP
                                            ├─ CDP：拉起账户专属 Chromium 抓 token
                                            │           ├─ 成功 → 用新 token 正常处理
                                            │           └─ 失败 → 返回 503
                                            └─ 手动账户且已过期 → 返回 503

_auto_refresh_loop → 检查 auto_refresh_enabled → 检查空闲时间
                        ├─ 启用 + 有请求 → 正常刷新（同样 RT 优先）
                        └─ 暂停或无请求 → 休眠等待唤醒
```

## 环境变量

### 服务配置（`.env` / pydantic Settings）

| 变量 | 必需 | 默认值 | 说明 |
| ---- | ---- | ------ | ---- |
| `API_KEY` | **是*** | — | 全局/快速启动 API Key；若一个 Key 都没注册且此项留空，`/v1/` 端点无认证开放 |
| `ADMIN_PASSWORD` | 否 | — | `/admin` 总控台密码，未设置时回退使用 `API_KEY` |
| `M365_ACCESS_TOKEN` | 否 | — | 单账户 Substrate Token，留空则由脚本推送或自动捕获（多租户按账户管理，一般不用） |
| `M365_TIME_ZONE` | 否 | `Asia/Shanghai` | 发送给 Copilot 的时区 |
| `M365_MODEL_ALIAS` | 否 | `m365-copilot` | 响应 JSON 中的 `model` 别名（**不是** `/v1/models` 列表里的对话模式 ID） |
| `TOKEN_DIR` | 否 | `/home/app/token` | 令牌/账户/Key/会话等持久化目录（挂载卷） |
| `IDLE_TIMEOUT_MINUTES` | 否 | `30` | 空闲多少分钟无 `/v1/` 请求后暂停自动刷新 |
| `LOG_LEVEL` | 否 | `INFO` | 日志输出等级（DEBUG/INFO/WARNING/ERROR/CRITICAL），Web 轮询与 `/healthz` 始终过滤 |

\* 多租户推荐在 `/admin` 创建 per-user Key，全局 `API_KEY` 仍建议设置以保护未绑定时的接口。

### 日志与安全开关

| 变量 | 必需 | 默认值 | 说明 |
| ---- | ---- | ------ | ---- |
| `LOG_USER_VERBOSE` | 否 | `true` | 账户/刷新的普通进度日志（可在 `/admin` 运行设置里改） |
| `LOG_USER_ERRORS` | 否 | `true` | 账户/刷新的失败/异常日志（可在 `/admin` 运行设置里改） |
| `SUPPRESS_ACCESS_LOG` | 否 | `true` | 屏蔽高频 uvicorn 访问日志（轮询/健康检查/favicon 等） |
| `ALLOWED_ORIGINS` | 否 | — | CORS 允许来源（逗号分隔），留空按内置策略处理 |
| `ADMIN_COOKIE_SECURE` | 否 | `0` | 管理会话 Cookie 是否加 `Secure`（HTTPS 部署置 `1`） |

### 浏览器刷新层（Dockerfile / entrypoint.sh 消费，非 pydantic Settings）

> 以下变量在容器入口脚本读取并转成 serve 的 CLI 参数。**除 `ENABLE_ADMIN_CDP` 外，其余仅在 `ENABLE_ADMIN_CDP=true` 时才生效**——默认多租户部署下共享 9222 浏览器不启动，刷新由每账户独立 Chromium（9322+）承担。

| 变量 | 必需 | 默认值 | 说明 |
| ---- | ---- | ------ | ---- |
| `ENABLE_ADMIN_CDP` | 否 | `false` | 是否启动共享 admin Chromium（9222）并注册其依赖端点 |
| `AUTO_REFRESH` | 否 | `true` | 共享 CDP 开启时，是否自动刷新 Token |
| `REFRESH_BEFORE_SECONDS` | 否 | `300` | 共享 CDP 开启时，Token 过期前多少秒开始刷新 |
| `CHROME_CDP_PORT` | 否 | `9222` | 共享 Chromium CDP 端口 |
| `CHROME_BIN` | 否 | 自动探测 | Chromium 可执行名（chromium/chrome 系列） |

## 客户端配置

| 设置 | 值 |
| ---- | -- |
| Base URL | `http://your-server:8000/v1` |
| API Key | `/admin` 下发的 Key，或全局 `API_KEY` |
| Model | 见 [可调用模型目录](#可调用模型目录)，推荐直接选列表中的 ID |

### Claude Code

```bash
export ANTHROPIC_BASE_URL=http://your-server:8000
export ANTHROPIC_API_KEY=YOUR_API_KEY
claude
```

> Anthropic 兼容走 `POST /v1/messages`；`model` 同样按对话模式解析。

### Cherry Studio / OpenWebUI / 其他 OpenAI 兼容客户端

```text
Base URL: http://your-server:8000/v1
API Key:  YOUR_API_KEY
Model:    Copilot_自动
          或 gpt-5.5_Chat / claude-sonnet-4-6 / gpt-5.5_Reasoning-持续 等
```

也可在客户端「刷新模型列表」拉取 `GET /v1/models` 后点选。若客户端忽略 vision 能力字段，请在客户端手动开启图片上传。

## 认证

### API Key

`/v1/` API 请求需携带 API Key，两种头都接受（`Authorization` 优先）：

| 请求头 | 用途 |
| ------ | ---- |
| `Authorization: Bearer your-key` | OpenAI 兼容客户端的标准形式 |
| `x-api-key: your-key` | Anthropic 官方 SDK / Claude Code 的标准形式 |

**仅当 `API_KEY` 为空且 `/admin` 里一个 API Key 都没注册时，`/v1/` 端点才无认证开放**（此时启动会打印警告）。两种方式任选其一即可保护接口：设置全局 `API_KEY`，或在 `/admin` 创建 per-user Key。多租户推荐后者。

```bash
curl -H "Authorization: Bearer YOUR_SECRET_KEY" http://localhost:8000/v1/models

# Anthropic SDK 形式
curl -H "x-api-key: YOUR_SECRET_KEY" -H "anthropic-version: 2023-06-01" \
  http://localhost:8000/v1/models
```

### Web 管理页面

访问 `/admin` 运营总控台时需输入管理密码。密码通过 `ADMIN_PASSWORD` 环境变量设置；未设置则使用 `API_KEY` 作为密码。登录后 Cookie 有效期 7 天。

## 多租户使用

分层界面：

- **`/admin` 运营总控台**（管理密码登录）：管理账户池与所有 API Key。可添加账户、推送/刷新账户 Token、新建 Key 并绑定账户、设置各 Key 的默认对话模式、随时启用/停用或删除 Key；运行设置里可编辑全局对话模式列表。
- **`/` 用户自助页**（用自己的 API Key 登录）：普通使用者用分到的 Key 登录，管理自己的默认对话模式、提示词增强、系统提示词，并可自助推送/更新绑定账户的 Token（未绑定账户时自动创建并绑定）。

典型流程（每 Key 绑定一个账户）：

1. 运营方在 `/admin` 添加账户（可当场粘贴该账户 Token，或留空稍后由用户/CDP 推送）
2. 新建 API Key 并绑定到某账户，把 Key 发给对应使用者
3. 使用者在 `/` 用自己的 Key 登录，按需自助推送账户 Token、调整默认对话模式与提示词
4. 在 OpenAI 兼容客户端里填入 Base URL（`http://<host>:8000/v1`）、自己的 API Key，以及 [模型目录](#可调用模型目录) 中的模型 ID

数据持久化：账户池 `accounts.json`、Key 表 `keys.json`、会话 `sessions.json` 等均写入 `TOKEN_DIR`（挂载卷），容器重启不丢。各账户会话按 Key 维度隔离，不同 Key 即使开场白相同也不会串会话。

### 内存与刷新

采用**按需 + 串行**策略：平时账户只在磁盘/内存存 Token，无浏览器进程。某账户 Token 临近过期且有请求时才刷新——**优先走 RT 纯 HTTP 交换（无浏览器、零内存开销）**；仅当 RT 缺失或失效时，才回退拉起该账户专属的 Chromium profile（独立 CDP 端口）抓取新 Token 后随即关闭。串行队列保证同一时刻最多一个 Chromium 存活，因此多账户下峰值内存仍接近单租户（约数百 MB，而非账户数 × 300MB）；持有 RT 的账户刷新时通常不会启动浏览器。

## 速率限制

微软不返回任何速率限制响应头，所以这是**自己给自己设的闸门**：拦住跑飞的自动化客户端，别让一个 Key 把大家共用的账户打到上游限流。

采用令牌桶：桶最多装 `突发容量` 个令牌，按 `速率限制 ÷ 60` 每秒回填，每个 `/v1/` 请求花掉一个。所以短时连发可以用满突发容量，长期均值被压在每分钟上限。超限返回 `429`，并带上 `Retry-After` 头（秒）。

- **全局默认** — `/admin` → 端口与日志 → 「速率限制（次/分）」与「突发容量」，默认 `60` 次/分、突发 `15`。填 `0` 表示**全局关闭限流**。
- **单 Key 覆盖** — `/admin` 用户管理里点「设置登录」展开行内编辑，填「速率继承」框。留空＝继承全局；填正数＝该 Key 用自己的上限；填 `-1` ＝该 Key 完全不限速。
- 限流按 **Key 独立计算**，一个人跑满不影响别人；未配置 Key 表时按全局身份统一计。
- 检查发生在按需 Token 刷新**之前**，被限流的请求不会白白拉起一次 Chromium。
- `/admin`、`/user`、`/healthz` 与 `/v1/m365-media` 不限流——前者会把运营者自己锁在门外，后者由签名 URL 鉴权、没有可计量的身份，且客户端加载历史图片时天然是批量请求。

> 桶状态存在进程内存里，容器重启即清零；改动上限会立刻重建对应的桶，无需等旧桶排空。

## 出站代理

给**服务器直连不到 M365 的部署**用（例如放在中国大陆的机器）。在 `/admin` → 运行设置 → 「出站代理」填一个地址，留空即直连。

支持 `http://`、`https://`、`socks5://`、`socks5h://`、`socks4://`、`socks4a://`，**必须写明端口**（`socks5h://127.0.0.1:1080`）。填错格式保存时会返回 400 并在按钮旁提示，不会静默存成直连。

覆盖范围是**所有出站流量**，包括对话主干道那条 `wss://substrate.office.com` 的 WebSocket、媒体/Token 的 HTTP 调用，以及刷新用的 Chromium（`--proxy-server`）。实现方式是把地址写进标准的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 环境变量——`httpx` 与 `websockets`（≥15）默认就读这些，因此不必逐个改调用点。

- **本地 CDP 永不走代理**。`localhost` / `127.0.0.1` / `::1` 始终被钉进 `NO_PROXY`，**即使没配代理也照样钉**：`websockets` 15 默认会读环境变量代理，若部署自己设了 `HTTPS_PROXY`，浏览器控制通道会被代理吞掉，Cookie 刷新与 Token 抓取全线失败。
- 保存后**下一次**上游调用即生效，不用重启；已经跑着的 Chromium 要等下次刷新拉起才换代理。
- 清空该设置会**还原**部署自带的 `HTTPS_PROXY`（如果 `docker-compose` 里设过），而不是抹掉它。
- socks5 支持来自 `python-socks`（WebSocket）与 `httpx[socks]`（HTTP），已在依赖里，无需额外安装。

> 这是**全局**设置，不是按账户设置。所有账户共用同一个代理出口。

## 媒体 / Designer 授权抓取

图片、语音等媒体内容与 Designer（PPT/图像生成）走的是**独立于 substrate 的授权**，这两个 token **不在 MSAL 缓存里**，也不由 RT / CDP 的 substrate 刷新产生——它们只在页面打开含媒体的对话时，作为 `teams.microsoft.com` / `officeapps.live.com` 等域请求的 `Authorization` 头短暂出现。因此需要油猴脚本在浏览器侧嗅探并推送。

**抓取方式**：油猴脚本 hook 页面的 fetch/XHR，当检测到发往下列域的带 `Authorization` 头请求时，捕获并**自动静默推送**到代理（也可用面板按钮手动推）：

| 类型 | 触发域 | Token 形态 | 推送端点 |
| ---- | ------ | ---------- | -------- |
| media-auth | `*.teams.microsoft.com` | `Bearer <JWT>`（存储时剥离 `Bearer` 前缀） | `POST /user/account/media-auth` |
| designer-auth | `*.officeapps.live.com` | 裸 JWE（**无 `Bearer` 前缀**） | `POST /user/account/designer-auth` |

**使用步骤**：

1. 在 M365 Copilot 中**打开一个新会话，在当前会话发送生成图片然后发送生成音频的消息**，必须是同一条会话记录里包含两种。
2. 油猴脚本面板点击一键推送。
3. 之后经代理请求媒体时，服务端用存储的凭据回放；由 `/v1/m365-media` 媒体代理（HMAC 签名 + 主机白名单）对外提供。
4. 推送 Cookie 时脚本会附带 `media_seed_url`（当前对话 URL），刷新流程可回访该对话**重新触发媒体请求以保活**这两个 token。

> 这两个 token 有效期短、且只能在浏览器打开相应内容时抓到，属于**尽力而为**的懒保活；若媒体链接失效，重新打开一次含媒体的对话再推送即可。media / designer 授权与 substrate token 相互独立，缺失时**不影响**普通文本对话。

## 持久会话与上下文优化

会话键的解析**按以下优先级**（高到低）取第一个命中的：

1. **Header 模式（固定会话 ID，最高优先级）**：请求头 `X-M365-Session-Id: my-session`。客户端自定义任意字符串，同一字符串即同一 M365 会话，最稳定可控——推荐需要精确控制会话边界的场景（如多智能体、并行会话）。
2. **模型后缀 / 持续模型**：使用模型名带 `-持续`（或底层 `:persist`），例如 `Copilot_深度思考-持续`、`Reasoning:persist`。同一 Key 下按该模型键复用固定会话。
3. **自动检测（默认）**：普通模型 ID（如 `Copilot_自动`、`gpt-5.5_Chat`）按首条用户消息的哈希自动分组；同一对话的连续轮次复用同一个 M365 会话，在客户端新建对话则自动开启新会话。

> **租户隔离**：所有会话键都会自动加上 `tenant` 前缀（该请求 API Key 的 id，未绑定则用账户 id / `global`）。因此**不同 Key 即使推送相同的 `X-M365-Session-Id` 值或相同开场白，也不会串会话**。
>
> Responses API（`/v1/responses`）另有一条通道：会话键会被编码进返回的 `resp_...` id，客户端把它作为 `previous_response_id` 回传即可续接，无需显式 Header。

### 增量上下文优化

当复用一个已有历史的持久会话时，M365 服务端已经记住了之前的轮次，代理只发送**最新一轮的新增内容**（最新用户消息 + 本地工具结果），不再每次重发完整对话历史。

这能节省上下文窗口、加快响应、避免 M365 聊天记录里堆积冗余历史文本。普通模型与 `-持续` 模型在复用会话时均启用此优化。

> M365 Copilot 按账号许可证授权、非按 token 计费，此优化不影响费用，但能提升长对话质量与速度。

### 会话持久化

会话映射（会话键 → 对话 ID、客户端会话 ID、轮次计数）会落盘到令牌存储目录，并在启动时恢复。

因此**容器重启后继续旧对话也能正确续接**：恢复同一个对话 ID、轮次计数大于 0，增量优化照常生效，不会把旧对话当成新会话、不再在 M365 侧产生多条重复记录。

> 持久化主要解决**容器/进程重启**导致的内存会话丢失问题。

### 新对话检测

自动检测按首条用户消息的哈希分组会话。为避免**相同开场白反复新开对话**时哈希碰撞到同一会话（导致复用旧 M365 线程、模型拿到错乱上下文而幻觉），代理会判断请求是否为对话首轮：**首轮（消息中没有任何 assistant 回复）会重置会话、开启全新的 M365 线程**，续接轮次才复用。`-持续` / `:persist` 与 Header 模式靠显式会话键，不受影响。

## 提示词增强与兜底重试

「强制调用 Tool」依赖系统提示词引导模型输出 `tool_call` 块。Web 管理页面提供两级可编辑、持久化的提示词，以及针对 M365 原生行为的服务端兜底：

- **提示词增强**：追加在工具调用提示词之后的自定义指令，用于微调 tool_call 行为，留空则不追加。
- **系统提示词（高级）**：覆盖工具调用的基础系统提示词（定义 tool_call 格式与规则）。默认折叠，需解锁并确认警告后才能编辑；动态工具列表始终自动追加、不可编辑；留空则用内置默认。两者都带「恢复默认」。
- **服务端兜底重试**：M365 Copilot 有原生「生成文件」功能，会把文件托管到自己的对象存储并返回下载链接，而不走 `tool_call`。当代理检测到响应「声称生成了文件（含托管附件链接或"已生成"等措辞）却没有任何 tool_call」时，会用纠正指令对同一会话自动重试一次，逼模型交出真正的 `tool_call`。命中兜底的调用在 Web「API 调用记录」中标记为 `retried`。
- **散文兜底（内联输出救援）**：当模型不输出 ```` ```tool_call ```` fence、但正文里包含「反引号绝对路径（如 `` `C:/temp/file.bat` ``）+ 语言标签匹配的代码块（如 ````bat）」时，代理会自动合成 Write `tool_call`。服务端内建的提示词引导会推动模型往这个形态输出（明确禁止生成托管附件、指定内联输出的格式），以提高在 M365 拒绝 fence 时的救援率。此机制保持解析器的严格性（避免把示例代码块误识别为写文件指令），测试中 `.bat`/`.html` 等文件类型的成功率约 60%；`.py` 等部分类型因 M365 倾向用 markdown 链接展示文件名（而非反引号路径）仍可能失败。

> 提示词只能降低模型幻觉概率，无法根除（底层模型指令遵循问题）。若工具调用仍不稳定，可尝试切换到深度思考（`Copilot_深度思考` / `Reasoning`）模式，或新开会话。

### tool_choice

两种 API 的 `tool_choice` 都会被解析并生效（此前该字段被接收后静默忽略）：

| 客户端传入 | 行为 |
|---|---|
| 不传 / `"auto"` / `{"type":"auto"}` | 默认。注入全部工具，模型自行决定 |
| `"none"` / `{"type":"none"}` | **完全不注入工具契约**，且响应侧不解析 tool_call |
| `"required"` / `{"type":"any"}` | 追加指令要求本轮必须调用某个工具 |
| `{"type":"function","function":{"name":"X"}}`（OpenAI）<br>`{"type":"tool","name":"X"}`（Anthropic） | 只把 `X` 一个工具告诉模型，并要求调用它 |
| `parallel_tool_calls: false`（OpenAI）<br>`disable_parallel_tool_use: true`（Anthropic） | 追加指令要求本轮最多一个 tool_call |

只有 `none` 是**完全可靠**的——它靠「不发送工具契约」实现，是本地决策，同时关掉提示词注入、响应解析、散文兜底和纠正重试，所以即使模型自发吐出 fence 也不会有 `tool_use` 漏给客户端。其余模式是提示词层面的引导，受与上文同样的依从性限制。

指定工具名时会把工具列表**收窄到那一个**，因此模型即使照做也无法挑错工具。名字不存在时保留完整列表而非清空——客户端要的东西我们看不到，清空会让请求看起来像压根没带工具。

## 个人版（消费者版 Copilot）账户

除 M365 企业版外，本项目也支持把 **个人微软账号的 `copilot.microsoft.com`** 接进同一套 `/v1` 接口。不需要 M365 订阅，代价是能力受限（见下方[限制](#限制)）。凭据可以自动续（需 `-camoufox` 镜像，见[凭据自动续期](#4-凭据自动续期可选)），也可以手动重推。

一个账户要么是 M365，要么是个人版，由账户的 `provider` 字段决定：推送个人版凭据会把它**永久切到 `consumer`**，同时把它**移出 M365 的刷新链路**（RT 换取、Cookie 回放、CDP 抓取对它都没有意义）。它仍在调度里，只是走另一条续期路径。`/admin` 账户表会给这类账户打上标记。

### 1. 配置出站代理（仅在服务器直连不到 Copilot 时）

`copilot.microsoft.com` 在部分网络下会被 SNI 阻断。按[出站代理](#出站代理)一节在 `/admin` → 运行设置里填一个能连通的地址即可，个人版链路和其它出站流量共用同一出口。

> **写 `socks5h://` 而不是 `socks5://`。** 两者的差别是 DNS 在哪解析：`socks5` 在本地解析域名，解析结果又会撞回被阻断的路径；`socks5h` 把域名交给代理远端解析。实测同一个代理端口，`socks5://` 失败、`socks5h://` 成功。`http://` 同样可用。

### 2. 推送凭据

1. 安装同一个[油猴脚本](#方式一油猴脚本推荐)（`@match` 已覆盖 `copilot.microsoft.com`，无需另装）
2. 在 `/` 用户自助页拿到自己的 **API Key**，填进油猴面板的「用户 API Key」框；「代理地址」填**本代理服务**的地址（如 `http://localhost:8000`）
3. 打开 [copilot.microsoft.com](https://copilot.microsoft.com) 并登录个人微软账号
4. **发送一条消息** —— ChatAI token 只出现在聊天 WebSocket 的 URL 里，不发消息就抓不到
5. 面板「个人版 Copilot」一栏变绿显示 `✓ ChatAI Token 可用` 后，点 **推送个人版 Copilot**

> 面板里的 `Token` / `Media Bearer` 两栏是**企业版**用的，个人版账户不需要它们，显示「尚未捕获」属正常。

### 3. 凭据过期后重推

个人版的 ChatAI token 对本服务是**不透明**的（不是可解码的 JWT），因此管理页只能显示「有没有存」，无法显示剩余有效期。过期的表现是 `/v1/` 请求返回 **502**，消息体里带上游的失败原因。

**手动恢复方式就是重复上面第 2 步**：回到 copilot.microsoft.com 发一条消息，再点一次推送按钮。若用了下面的 `-camoufox` 镜像，多数情况不需要走到这一步。

### 4. 凭据自动续期（可选）

用 `ghcr.io/<repo>:fox-camoufox` 这类带 `-camoufox` 后缀的镜像，服务端就能自己续个人版凭据，不需要人再去点推送按钮。默认镜像不含这个能力。

原理是让 **MSAL 的静默 SSO 重新铸一个 token**：容器里起一个持久 profile 的 Firefox（Camoufox），加载 copilot.microsoft.com，等页内 MSAL 用 profile 里的微软账号会话换出新的 ChatAI token，导出 Cookie，然后关掉浏览器。全程不点任何东西、不发聊天消息，所以**没有任何 Turnstile 环节**。实测冷启动到拿到 token 约 **6.7 秒**，之后进程即退出——不是常驻浏览器。

这是真「铸新的」而不是「读缓存」：把 localStorage 里的 MSAL 缓存清空再刷新，拿到的是一个**不同**的 token 且没有跳转登录页，所以缓存里的 token 过期后它照样能用。

三个触发点：

- **保活** —— 凭据存下来超过 1 小时就重铸一次。个人版 token 不透明、读不到 `exp`，只能按「距上次捕获多久」调度；这一次次的重铸同时也在保持 profile 里的微软账号会话不失效
- **请求内自救** —— `/v1` 请求因凭据过期失败（且还没吐出任何内容）时，自动重铸一次并重试当轮。没失败的请求不会付这 7 秒
- **管理页刷新按钮** —— 手点即重铸

前提是 profile 里那个**微软账号会话本身还活着**。每次续期都会顺带把它焐热，但它真失效了（换密码、被撤销、长期没动），就还需要一次人工登录。

profile 落在 `TOKEN_DIR/profiles/<account-id>-consumer`（默认即 `token-data` 卷内的 `/home/app/token/profiles/...`）。**这个挂载必须是持久卷，不能是 tmpfs** —— 丢了它就等于丢了那个微软账号会话，代价是一次人工登录。要从干净状态重来：

```bash
docker compose exec ciallo-proxy-multi \
  rm -rf /home/app/token/profiles/<account-id>-consumer
```

> 续期时会拉起浏览器，峰值内存约 417 MB。调度用同一把全局锁把它和 M365 的 Chromium 刷新**串行化**，不会两个浏览器同时在跑；`docker-compose.yml` 默认的 2G 内存上限够用。

> 为什么是 Firefox 而不是镜像里已有的 Chromium：consumer 端点会**按 TLS 指纹判决**，Chromium 指纹拿到的是 `method: null` 的 `challenge`（只能由页内 JS 现场解），Firefox 指纹则根本不触发 challenge。这也是 HTTP 客户端那一侧必须用 curl_cffi 的 `firefox147` 的同一个原因。
>
> 代价：镜像大约 **+936 MB**，每个账户的 profile 再占约 97 MB（落在 `token-data` 卷上，与上面的 profile 路径同一处）。这也是它没进默认镜像的原因。本地自建：`docker build --build-arg WITH_CAMOUFOX=true ...`

### 限制

个人版走的是另一套上游协议，以下能力**不生效**，且都是协议/实现层面的硬限制，不是配置问题：

| 能力 | 个人版 | 说明 |
|---|---|---|
| 对话模式（tone） | ❌ | 上游无模式选择器，`/v1/models` 里的模式 ID 对个人版账户无意义 |
| 提示词增强 | ❌ | 该文本在 M365 客户端内部注入（`substrate_client.py`），个人版客户端不经过那条路径 |
| 系统提示词 | ✅ | 在路由层拼进对话正文，两种 provider 都生效 |
| 工具调用（提示词模拟） | ✅ | 客户端声明的 tools 随对话正文下发，与企业版同源 |
| 图片输入 | ❌ | 适配器丢弃图片，带图请求会得到**纯文本回复**而不是报错 |
| 图片生成 | ✅ | 让它画图会返回 Markdown 图片链接。个人版不需要企业版那套「媒体授权」——链接是匿名可取的（实测无 Cookie、无 token 直接 200） |
| 持续会话 | ⚠️ | 每轮开新对话，完整历史每轮重发，因此上下文不丢；但上游侧不存在长期会话 |
| Token 自动刷新 | ⚠️ | RT / CDP 两条链路都不适用。`-camoufox` 镜像用 MSAL 静默 SSO 自动重铸（见[凭据自动续期](#4-凭据自动续期可选)）；默认镜像只能手动重推 |

> **TLS 指纹是硬约束。** 个人版上游按 TLS 指纹判客户端：curl_cffi 的 chrome / edge / safari 全系会被拒（表现为收到 `challenge` 帧后连接被掐断），当前固定使用 `firefox147`。这是实测得到的经验事实，微软调整策略后可能失效。

## 企业版与个人版的差异

社区里另有一类项目桥接的是 **`copilot.microsoft.com`（个人微软账号）**，本项目桥接的是 **`substrate.office.com`（M365 企业版）**。两者上游协议不同，因此约束差别很大——下表中「个人版」一列的数字来自那类项目的源码与文档，「本项目」一列是在本部署上实测的：

| | 本项目（M365 企业版） | 个人版（消费者版 Copilot） |
|---|---|---|
| 上游 | `wss://substrate.office.com/m365Copilot/Chathub`（SignalR） | `wss://copilot.microsoft.com/c/api/chat` |
| 账号模型 | **多租户**：账号池 + 每个 API Key 绑定账号 | 单个已登录账号 |
| 鉴权 | substrate JWT（RT 纯 HTTP 交换，或 CDP 抓取） | 登录 Cookie + ChatAI access token（WebSocket query 参数） |
| Cloudflare | 上游无 Turnstile | 该站**不签发 `cf_clearance`**（实测：全新 profile 加载后只有 `__cf_bm` / `__cflb`，无 Turnstile iframe）。验证发生在**应用层**——`challenge` 帧的 `method` 为 `null` 时要的是页内 JS 现场铸的 Turnstile token，不在任何 Cookie 里，因此「浏览器过验证、HTTP 客户端重放 Cookie」这条路不存在；能否通过只取决于 TLS/HTTP 指纹与出口信誉 |
| 提示词长度 | 实测 147k 字符仍完整（在首轮埋标记、末轮追问，标记可复述） | 默认截断到 8000 字符，需要压缩历史 |
| 并发 | **支持**。每轮开独立 WebSocket（各自 conv/session id），实测 4 路并发同账号答案互不干扰 | 取决于具体代理实现；复用单 socket 的实现必须串行化 |
| 模型/模式 | 多模式（可在管理页编辑列表），每个模式另有「-持续」变体 | 单一模型，无选择器 |
| 浏览器依赖 | Chromium + 裸 CDP（仅刷新时按需拉起） | 聊天走 curl_cffi（TLS 指纹）；凭据续期需 Firefox 内核，本项目用 Camoufox，同样只在续期时按需拉起（约 6.7 秒后退出）。镜像里的 Chromium 顶不了这个班——consumer 端点拒 Chromium 指纹 |
| 速率限制 | 令牌桶，默认 60 次/分 | 默认 12 次/分（其文档称单账号约 15 rpm 起开始限流） |

**共同的短板**：两边都没有原生 tool-calling 通道，都靠提示词约定 + 解析文本实现，因此都受模型依从性限制。这不是实现选择，而是两个上游协议都没提供该能力。

**对使用者的实际影响**：个人版不需要 M365 订阅，但需要维护一份浏览器登录态。本项目里这份登录态由 Camoufox 的持久 profile 承载、并由每次续期自动焐热，只有它真失效时才需要人工介入一次；普通 HTTP/WebSocket 重放同一组 Cookie 仍可能被拒。个人版代理常见的 8000 字符历史上限和串行限制属于具体实现约束，不是消费者协议本身的保证。本项目需要 M365 账号，换来已经验证的多租户、长上下文和真并发。

## 架构

```
容器启动 (entrypoint.sh)
  ├─ [可选] 共享 admin Chromium headless → CDP 9222
  │     仅当 ENABLE_ADMIN_CDP=true 时启动（默认 false，多租户不启动）
  │     用于单账户启动捕获 + /admin/token/auto-capture、/admin/cookie/inject、/admin/chromium/*
  │
  └─ copilot-openai-proxy serve (端口 8000)
      ├─ /v1/* — OpenAI/Anthropic 兼容 API
      │         · model 名 → 对话 tone（+ 可选 -持续 / :persist）
      │         · 按 API Key 解析账户 → per-key 默认 tone / 提示词
      ├─ /admin/* — 运营总控台端点（账户池 + Key 管理 + 设置/可观测性）
      ├─ /user/* — 用户自助端点（用自己的 Key 管理模式/提示词/账户 Token/Cookie）
      ├─ /admin — 运营总控台页面（管理密码登录）
      ├─ / — 用户自助页面（API Key 登录）
      └─ 按需串行刷新：RT 优先 → 失败再拉起账户专属 Chromium（CDP 9322+）
          串行队列保证同一时刻最多一个 Chromium，峰值内存接近单租户
```

## License

Apache License 2.0

## 致谢

- [kuchris/m365-copilot-openai-proxy](https://github.com/kuchris/m365-copilot-openai-proxy)
- [KilimcininKorOglu/M365Bridge](https://github.com/KilimcininKorOglu/M365Bridge)
- [LINUX DO](https://linux.do/)
