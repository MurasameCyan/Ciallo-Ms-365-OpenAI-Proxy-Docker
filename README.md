# Ciallo Ms-365 OpenAI Proxy Docker

将 Microsoft 365 Copilot 暴露为 OpenAI 兼容 API 的 Docker 代理服务。

基于 [m365-copilot-openai-proxy](https://github.com/kuchris/m365-copilot-openai-proxy)，封装为 Docker 镜像，支持：

- 按需刷新 Token 降低账号风险（空闲自动暂停，有请求时自动唤醒）
- Tampermonkey 油猴脚本一键推送 Token + Cookie
- 对话模式切换（自动 / 快速答复 / 深度思考 / GPT 5.5 / GPT 5.2）
- 增量上下文优化（复用会话时只发送新增内容，不重发完整历史）
- 会话持久化（容器重启后旧对话仍可正确续接）
- 提示词增强 + 系统提示词编辑（Web 页面可调教 tool_call 行为，持久保存）
- 强制调用Tool  (半成品，出现无法调用请新开会话，已加服务端兜底重试)
- API Key 认证保护
- Web 管理页面

## 快速部署

### 1. 创建 .env 文件

```bash
cp .env.example .env
```

### 2. 启动服务

```bash
docker-compose up -d
```

服务在 `http://localhost:8000` 启动，打开浏览器访问即为 Web 管理页面。首次访问需输入管理密码（`ADMIN_PASSWORD` 或 `API_KEY` 的值）。

### 3. 推送 Token

#### 方式一：油猴脚本（推荐）

1. 安装 [Tampermonkey BETA](https://www.tampermonkey.net/) 浏览器扩展
2. 点击 [一键脚本](https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/main/get_token.user.js) 安装油猴脚本
3. 打开 [M365 Copilot](https://m365.cloud.microsoft/chat) 并登录你的 M365 账号
4. 在 Copilot 对话框中**输入任意字符**触发 WebSocket 连接
5. 页面右上角弹出 推送面板
6. 点击 **One-Click Setup** — 自动推送 Cookie + Token 到代理服务

> **首次需要先推送 Cookie** 让 Chromium 登录 M365，之后 Auto Capture 即可自动刷新 Token。

#### 方式二：手动粘贴

1. 在浏览器中打开 M365 Copilot
2. F12 → Network → WS → 找到 `wss://substrate.office.com/...` 连接
3. 复制 URL 中的 `access_token` 参数值
4. 粘贴到 Web 管理页面的 **Update Token** 输入框，点击 **Update Token**

> **注意手动导入无法自动刷新 Token， 也无法启用按需刷新。**

#### 查看状态

Web 管理页面显示 Token 有效性和 Chromium 登录状态。点击 **Check Login** 检查 Chromium 是否已登录，点击 **Auto Capture** 让 Chromium 自动捕获新 Token。

## API 端点

### OpenAI 兼容 API

| 端点                          | 说明                                |
| ----------------------------- | ----------------------------------- |
| `GET /v1/models`            | 模型列表                            |
| `POST /v1/chat/completions` | OpenAI Chat Completions（支持流式） |
| `POST /v1/responses`        | OpenAI Responses API（支持流式）    |
| `POST /v1/messages`         | Anthropic Messages API（支持流式）  |

### 管理端点

| 端点                                      | 说明                         |
| ----------------------------------------- | ---------------------------- |
| `GET /healthz`                          | 健康检查                     |
| `GET /admin/token/status`               | Token 有效性与自动刷新状态   |
| `POST /admin/token/update`              | 手动推送 Token               |
| `POST /admin/token/auto-capture`        | 触发 Chromium 自动捕获 Token |
| `POST /admin/token/auto-refresh-toggle` | 切换自动刷新开关             |
| `POST /admin/cookie/inject`             | 注入 Cookie 到 Chromium      |
| `GET /admin/chromium/login-status`      | Chromium 登录状态            |
| `POST /admin/chromium/logout`           | Chromium 登出                |
| `GET /admin/call-log`                   | API 调用记录                 |
| `GET POST /admin/tone`                  | 查询 / 设置对话模式          |
| `GET POST /admin/tool-prompt`           | 查询 / 设置提示词增强        |
| `GET POST /admin/system-prompt`         | 查询 / 设置系统提示词        |
| `GET POST /admin/capture-payload`       | 查询 / 接收模式抓包数据      |
| `POST /admin/login`                     | Web 管理页面登录             |

## 按需刷新机制

默认采用按需刷新模式，降低长时间保持连接的账号风控：

1. **容器启动不自动刷新** — `auto_refresh` 初始为关闭状态，无后台 token 刷新活动
2. **`/v1/` 请求触发同步刷新** — 当有 `/v1/` API 请求且 Token 过期或不存在时，中间件**同步调用 CDP 刷新** Token，请求等待刷新完成后继续
3. **空闲自动暂停** — 超过 `IDLE_TIMEOUT_MINUTES`（默认 30 分钟）无 `/v1/` 请求时，自动暂停刷新循环
4. **再次请求自动唤醒** — 下一个 `/v1/` 请求到来时，自动唤醒刷新
5. **Web 按钮控制** — 可通过 Web 页面手动启用/暂停自动刷新

> **注意按需刷新机制唤醒需要先刷新 Token 所以首轮回复等待时间会增加。**

```
/v1/ 请求 → 记录 last_request_time → 检查 token 有效性
                                        ├─ 有效 → 正常处理
                                        └─ 过期 + auto_refresh 关闭 →
                                            ├─ 同步调用 CDP 刷新 token
                                            ├─ 刷新成功 → 用新 token 正常处理
                                            └─ 刷新失败 → 返回 503

_auto_refresh_loop → 检查 auto_refresh_enabled → 检查空闲时间
                        ├─ 启用 + 有请求 → 正常刷新
                        └─ 暂停或无请求 → 休眠等待唤醒
```

## 环境变量

| 变量                       | 必需         | 默认值            | 说明                                        |
| -------------------------- | ------------ | ----------------- | ------------------------------------------- |
| `M365_ACCESS_TOKEN`      | 否           | —                | Substrate Token，留空则由脚本推送或自动捕获 |
| `M365_TIME_ZONE`         | 否           | `Asia/Shanghai` | 发送给 Copilot 的时区                       |
| `M365_MODEL_ALIAS`       | 否           | `m365-copilot`  | 自定义模型名称                              |
| `API_KEY`                | **是** | —                | API Key 认证密钥                            |
| `ADMIN_PASSWORD`         | 否           | —                | Web 管理页面密码，未设置时为 `API_KEY 值` |
| `AUTO_REFRESH`           | 否           | `true`          | 是否自动刷新 Token                          |
| `REFRESH_BEFORE_SECONDS` | 否           | `300`           | Token 过期前多少秒开始刷新                  |
| `IDLE_TIMEOUT_MINUTES`   | 否           | `30`            | 空闲多少分钟无请求后暂停自动刷新            |
| `CHROME_CDP_PORT`        | 否           | `9222`          | Chromium CDP 端口                           |

## 客户端配置

| 设置     | 值                                      |
| -------- | --------------------------------------- |
| Base URL | `http://your-server:8000/v1`          |
| API Key  | 你设置的 `API_KEY` 值                 |
| Model    | `m365-copilot / m365-copilot:persist` |

### Claude Code

```bash
export ANTHROPIC_BASE_URL=http://your-server:8000
export ANTHROPIC_API_KEY=YOUR_API_KEY
claude
```

### Cherry Studio / OpenCode

```bash
Base URL: http://your-server:8000/v1
API Key: YOUR_API_KEY
Model: m365-copilot
```

## 认证

### API Key

**必须在 `.env` 中设置 `API_KEY`**，否则所有 `/v1/` API 端点无认证开放。启动时未设置会打印警告。所有 `/v1/` API 请求需携带 `Authorization: Bearer your-key` 头。

```bash
curl -H "Authorization: Bearer YOUR_SECRET_KEY" http://localhost:8000/v1/models
```

### Web 管理页面

访问 Web 管理页面时需输入管理密码。密码通过 `ADMIN_PASSWORD` 环境变量设置，如果未设置则使用 `API_KEY` 作为密码，登录后 Cookie 有效期 7 天。

## 持久会话与上下文优化

### 持久会话

- **Header 模式**：请求头 `X-M365-Session-Id: my-session`
- **模型后缀模式**：使用模型名 `m365-copilot:persist`
- **自动检测**：默认模型 `m365-copilot` 会按首条用户消息的哈希自动分组，同一对话的连续轮次复用同一个 M365 会话，在客户端新建对话则自动开启新会话

### 增量上下文优化

当复用一个已有历史的持久会话时，M365 服务端已经记住了之前的轮次，代理只发送**最新一轮的新增内容**（最新用户消息 + 本地工具结果），不再每次重发完整对话历史。

这能节省上下文窗口、加快响应、避免 M365 聊天记录里堆积冗余历史文本。`m365-copilot`（自动模式）与 `m365-copilot:persist` 均启用此优化。

> M365 Copilot 按账号许可证授权、非按 token 计费，此优化不影响费用，但能提升长对话质量与速度。

### 会话持久化

会话映射（会话键 → 对话 ID、客户端会话 ID、轮次计数）会落盘到令牌存储目录，并在启动时恢复。

因此**容器重启后继续旧对话也能正确续接**：恢复同一个对话 ID、轮次计数大于 0，增量优化照常生效不会把旧对话当成新会话、不再在 M365 侧产生多条重复记录。

> 持久化主要解决**容器/进程重启**导致的内存会话丢失问题。

### 新对话检测

自动检测按首条用户消息的哈希分组会话。为避免**相同开场白反复新开对话**时哈希碰撞到同一会话（导致复用旧 M365 线程、模型拿到错乱上下文而幻觉），代理会判断请求是否为对话首轮：**首轮（消息中没有任何 assistant 回复）会重置会话、开启全新的 M365 线程**，续接轮次才复用。`:persist` 与 Header 模式靠显式会话键，不受影响。

## 提示词增强与兜底重试

「强制调用 Tool」依赖系统提示词引导模型输出 `tool_call` 块。Web 管理页面提供两级可编辑、持久化的提示词，以及针对 M365 原生行为的服务端兜底：

- **提示词增强**：追加在工具调用提示词之后的自定义指令，用于微调 tool_call 行为，留空则不追加。
- **系统提示词（高级）**：覆盖工具调用的基础系统提示词（定义 tool_call 格式与规则）。默认折叠，需解锁并确认警告后才能编辑；动态工具列表始终自动追加、不可编辑；留空则用内置默认。两者都带「恢复默认」。
- **服务端兜底重试**：M365 Copilot 有原生「生成文件」功能，会把文件托管到自己的对象存储并返回下载链接，而不走 `tool_call`。当代理检测到响应「声称生成了文件（含托管附件链接或"已生成"等措辞）却没有任何 tool_call」时，会用纠正指令对同一会话自动重试一次，逼模型交出真正的 `tool_call`。命中兜底的调用在 Web「API 调用记录」中标记为 `retried`。

> 提示词只能降低模型幻觉概率，无法根除（底层模型指令遵循问题）。若工具调用仍不稳定，可尝试切换到深度思考（Reasoning）模式，或新开会话。

## 对话模式

M365 Copilot 支持多种模型 / 思考模式，由 Substrate 请求中的 `tone` 字段控制。可在 Web 管理页面「对话模式」下拉选择，选择后立即生效并持久保存。

| 模式             | 说明                       |
| ---------------- | -------------------------- |
| 自动             | 由 Copilot 决定思考时长    |
| 快速答复         | 立即回答                   |
| 深度思考         | 思考更长时间以获得更好回答 |
| GPT 5.5 快速响应 | GPT 5.5 + 快速             |
| GPT 5.5 深度思考 | GPT 5.5 + 推理             |
| GPT 5.2 快速响应 | GPT 5.2 + 快速             |
| GPT 5.2 深度思考 | GPT 5.2 + 推理             |

## 架构

```
容器启动
  ├─ Chromium headless → m365.cloud.microsoft/chat (CDP 端口 9222)
  │   ├─ 登录状态持久化于 /chrome-profile volume
  │   └─ 通过 CDP 自动捕获 Substrate WebSocket Token
  │
  └─ ciallo-ms365-proxy serve (端口 8000)
      ├─ /v1/* — OpenAI 兼容 API（按需刷新 + 同步 CDP 刷新）
      ├─ /admin/* — 管理端点（Token/Cookie/Login 管理）
      ├─ Web 管理页面 (/)
      └─ 按需刷新：启动暂停 → /v1/ 请求同步刷新 → 空闲暂停
```

## 预览

![1782869646324](image/README/1782869646324.png)

![1782854190802](image/README/1782854190802.png)

## License

Apache License 2.0
