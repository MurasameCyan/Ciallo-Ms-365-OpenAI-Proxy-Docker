# GitHub M365 Copilot 反代 / 2API 候选核对（临时）

> 调查日期：2026-08-20
> 用途：后续技术核对，非正式选型结论。
> 当前架构前提：一个 API Key 固定绑定一个用户自己的 M365/Consumer 账号；不需要跨账号轮询、负载均衡或故障转移。

## 评估重点

- 用户账号、凭据、会话和企业数据必须严格隔离。
- 优先考察单账号自助登录、长期凭据续期、ChatHub 协议稳定性。
- 优先补充工具调用可靠性、动态协议参数、图片生成和 usage 估算。
- 保持现有 OpenAI Chat/Responses、Anthropic Messages、SSE、会话和图片输入能力。
- 无标准开源许可证的项目只能黑盒测试或参考行为，不能复制代码。
- 无下游鉴权的项目只能绑定 loopback，不能原样暴露到公网。

## 候选项目

| 原始优先级 | 项目 | 许可证与状态 | 对当前项目有用的部分 | 主要限制或风险 | 建议 |
|---:|---|---|---|---|---|
| 1 | [cramt/m365-copilot-proxy](https://github.com/cramt/m365-copilot-proxy) | MIT；67 stars；2026-08-17 仍活跃 | 自动创建 Copilot Studio agent；把工具约束放进服务端指令；fenced/shell 工具格式；Disengaged 检测；账号级节流退避 | Node/Nitro；需要 Power Platform/BAP 权限；工具轮可能缓冲；服务无下游 API Key 校验且 CORS 为通配，只能本机测试 | **正式 12 case × 3 轮已完成；保留为账号级显式实验备选，Router 继续默认** |
| 2 | [microsoft/Agents-M365Copilot](https://github.com/microsoft/Agents-M365Copilot) | 微软官方；MIT；Python/C#/TypeScript SDK | 官方 Graph Copilot Chat API；原生流式；企业搜索及 SharePoint/OneDrive 等上下文 | Graph beta 仍是 Preview；需要 M365 Copilot 许可和 7 个委派权限；不支持个人账号；暂无模型选择、图片、工具或代码解释器 | 作为可选官方 Graph Provider 做第二个 PoC |
| 3 | [jairbj/m365-copilot-proxy](https://github.com/jairbj/m365-copilot-proxy) | MIT；2026-08-17 创建的新项目；持续提交 | 单用户设计；从真实 Web 请求捕获 tone、variants、optionsSets；区分 Work IQ 开关；PKCE/MSAL 静默刷新 | 项目很新；主要只有 Chat Completions；工具调用整段缓冲；API Key 被忽略且仅适合 loopback | 借鉴“动态协议 profile/capture”思路，先观察稳定性 |
| 4 | [HEXUXIU/M365-Copilot2API](https://github.com/HEXUXIU/M365-Copilot2API) | MIT；268 stars；2026-08-18 活跃 | ChatHub 事件处理；图片生成；usage 估算；断线重连；单账号健康状态；图片下载 SSRF 防护 | 当前 Issues 集中在工具调用、图片和长上下文；尚无稳定 Release；私有协议风险；下游鉴权存在“eyJ 前缀直接放行”问题，不能原样公网部署 | 忽略账号池部分，只做源码对照和隔离环境黑盒测试 |
| 5 | [KilimcininKorOglu/M365Bridge](https://github.com/KilimcininKorOglu/M365Bridge) | 无标准 OSS LICENSE；README 标注 Research Only；38 stars | Responses/Anthropic/MCP；工具解析、schema 校验和修复；图片生成/编辑；RT + SSO Cookie 续期 | 默认保留全部权利，不能直接复制或商业整合；工具仍是提示词模拟；鉴权可选，默认配置需审计 | 仅黑盒比较协议行为，不搬代码 |
| 6 | [sideefffect/m365_openai_proxy.py](https://github.com/sideefffect/m365_openai_proxy.py) | Apache-2.0；单文件 Python；带多项协议测试 | SignalR/ChatHub 逆向说明；token refresh race、会话连续性、限流、图片等测试思路 | 单账号、本机工具；无下游鉴权；工具调用是概率性模拟；无标准 Docker 服务架构 | 适合补协议回归测试，不适合直接部署 |
| 7 | [kuchris/m365-copilot-openai-proxy](https://github.com/kuchris/m365-copilot-openai-proxy) | Apache-2.0；61 stars；Python/FastAPI | 小而清晰的 Substrate SignalR、token store、协议翻译基线 | 无工具、图片、Docker和真实下游鉴权；短效浏览器 token；整体能力低于当前项目 | 保留为最小参考实现 |
| 8 | [shenping1200/m365-copilot-bridge](https://github.com/shenping1200/m365-copilot-bridge) | MIT；15 stars；2026-08-16 活跃 | PKCE、会话粘性、每账号代理、API Key 哈希和较完整的管理端鉴权 | 主要差异化能力是多账号轮询，当前架构不需要；usage 仍是占位；工具为模拟 | 只核对认证和协议实现，不列入优先试用 |
| 9 | [lamdt1/ms-copilot365-2api](https://github.com/lamdt1/ms-copilot365-2api) | 无许可证；新项目；活跃度和使用量低 | Camoufox + noVNC 自助登录；浏览器凭据轮换；容器化登录流程 | 无许可证；浏览器镜像重；成熟度不足；现有项目已经有 PKCE/CDP/Camoufox 链路 | 只参考登录 UX，不复制代码 |

## 不纳入当前选型

- GitHub Copilot 2API：上游是 GitHub Copilot，不是 Microsoft 365 Copilot。只能参考协议翻译，不能替代当前 M365 Provider。
- Bing/Consumer Video 2API：上游、接口和用途不同。
- EdgeGPT 等旧 Bing Chat 项目：已归档或协议过时。
- HEXUXIU 的直接 fork：不作为独立候选重复评估。

## 首个实验：Copilot Studio agent 工具调用 A/B（已完成）

### 为什么先做

1. 不改变 API Key 到用户账号的一对一绑定关系。
2. 不需要先改账户存储、租户隔离或会话模型。
3. 直接针对当前最有价值的不确定项：GPT tone 下工具调用的正确率和稳定性。
4. 可以在隔离测试账号、本机 loopback 环境完成，失败后容易清理。

### 实验范围

- 使用一个专用 M365 测试账号，不使用真实生产数据。
- A 组：当前项目现有 prompt/router 工具调用。
- B 组：cramt 的 Copilot Studio agent 服务端指令方案。
- 两组使用相同模型/tone、工具 schema、输入和 tool result。
- 准备约 30 个用例，覆盖：
  - 单工具选择；
  - 多个相似工具选择；
  - 必填和可选参数；
  - 枚举、数组、嵌套对象；
  - 连续两轮 tool result；
  - 不应调用工具的普通问答；
  - 错误参数后的纠正；
  - 长上下文和多个工具并存。

### 记录指标

- 正确选择工具的比例。
- 参数通过 JSON/schema 校验的比例。
- 完成完整 tool call → tool result → final answer 闭环的比例。
- Disengaged、429、空响应、超时和错误重试次数。
- 首字节时间、总耗时，以及工具轮是否必须整段缓冲。
- 是否产生错误工具调用、虚构结果或普通文本冒充工具调用。

### 建议验收线

- B 组完整成功率至少达到 90%，且比 A 组提高至少 15 个百分点。
- 普通问答误触发工具不超过 2%。
- P95 总耗时相对 A 组增长不超过 20%。
- 不新增明文密码、TOTP、refresh token 或会话正文日志。
- Power Platform agent 的创建、更新和删除过程可审计、可清理。

### 停损条件

- 租户不允许所需 Power Platform/BAP 权限。
- 必须保存用户密码或 TOTP 才能长期运行。
- 工具成功率提升不足 10 个百分点。
- Disengaged 或节流频率明显高于当前实现。
- 创建的 Copilot Studio agent 无法可靠清理或会造成额外许可成本。

### 2026-08-20 预备 smoke（仅作历史记录）

修正版现场运行时间为 2026-08-20 04:49:52（Asia/Shanghai；报告文件名使用 UTC）。A、B 两组使用同一个绑定账号、同一个模型和 tone，共运行 5 个 smoke case。

| 组别 | 完整成功 | 成功率 | 误调用 | 平均耗时 | 单 case 耗时（ms） |
|---|---:|---:|---:|---:|---|
| A：现有路由 | 5/5 | 100% | 0 | 9215 ms | 6214、5406、6821、8898、18735 |
| B：Studio agent | 5/5 | 100% | 0 | 6542 ms | 5873、5716、5660、4207、11256 |

这组数据只回答了“小样本下成功率是否明显提高”，不能回答 Studio 是否有稳定延迟价值。此前由“成功率未提高”扩大成“不值得集成”的结论不成立；正式实验已按下文重新执行。

B 的平均耗时在本次样本中约低 29%，但样本只有 5 个 case，且固定先跑 A、后跑 B，存在顺序和上游波动偏差，不能据此认定 Studio 有稳定延迟优势。若以后专门验证延迟，应改为至少 10 个 case × 3 次，并交替使用 AB/BA 顺序。

旧的 `A 4/5、B 5/5` 结果整体作废。旧 runner 在工具结果第二轮仍使用 `tool_choice=required`，并且没有让两组以等价方式复用会话；该失败来自探针偏差，不代表 Studio 优势。修正版已改为第二轮 `auto`，A 复用固定 `X-M365-Session-Id`，B 复用同一 `PersistentSession` 并启用增量翻译。

脱敏报告保存在 `.probe/studio_ab/results/studio-ab-20260819T204952Z.json`，SHA-256 为 `901f4f4cad8d671e4378646ecb91483d8f325887392ae5815b12d1ce64bea5cf`。容器内原报告和 agent cache 权限均为 `0600`；报告扫描未发现 API Key、JWT、Bearer、邮箱或敏感字段。已有 Studio agent 被复用，未重复创建或删除。

安全边界：普通实验在 agent cache miss 时直接失败，不会隐式 provision。只有显式 `--provision-only` 会创建或发布 Power Platform agent；该操作可能更新账号 refresh 状态，必须视为有状态操作并串行执行。

### 2026-08-20 正式 HTTP AB/BA 实验

正式实验让 Router 和 Studio 使用同一候选镜像、同一绑定账号、同一模型、同一工具请求和同一个 `/v1/chat/completions` HTTP 接口。共执行 12 个 case × 3 轮，即 36 个配对、72 个观测；运行前完成 2 次双向热身，正式顺序逐 case 交替 AB/BA。两组各有 18 次位于 pair 第一位、18 次位于第二位。

| 组别 | 完整成功 | 成功率 | 误调用 | 中位耗时 | P95 耗时 |
|---|---:|---:|---:|---:|---:|
| Router | 36/36 | 100% | 0 | 8304 ms | 17725 ms |
| Studio agent | 35/36 | 97.22% | 0 | 4642 ms | 11249 ms |

正式结果：

- 35 个有效配对中，Studio 27 次更快，Router 8 次更快。
- 配对中位延迟差为 `-3636 ms`，Studio/Router 配对中位比为 `0.580441`，即 Studio 典型耗时约低 42%。
- Studio 唯一失败是 `required_single` 类的 `C04` 第 3 轮：180074 ms 超时；Router 对应观测成功。
- Router first/second 中位耗时为 8045/8332 ms；Studio 为 4419/4642 ms，未发现超过预设 20% 门槛的顺序效应。
- 远端和本地独立 verifier 均通过，自动判定为 `do_not_promote`，原因是 `insufficient_reliability_gain`。

因此，Studio 不应默认替换 Router，也不应进入“自动模式”的首选路径；但它的稳定中位延迟优势足以支持保留为**账号级、用户显式选择的实验备选**。边界保持不变：

1. `API Key → 固定用户账号 → 该账号自己的 Studio agent`，不共享、不轮询。
2. Router 继续作为默认模式和可靠性基线。
3. Studio 在产生任何输出前失败时可以安全回退 Router。
4. Studio 已产生文本或工具调用后禁止自动重放，避免重复执行工具。
5. `tool_choice=required` 超时或漏调用时，由用户显式改用 Router 重试，不做隐式双写。

正式脱敏报告：`.probe/studio_ab/results/formal-20260820T031621Z/http-ab-20260820T031621.354728Z.json`，SHA-256 为 `f6e99c800d3f953728471fccb85ef06fc74e1ee66130062710fd7d69320aba30`。报告为 schema v2，包含 72 个白名单观测字段；扫描未发现 API Key、Token、账号/agent 标识、提示词、工具参数、响应正文、headers、会话 ID 或 Cookie。远端三个临时容器和唯一工作目录已删除；生产容器 ID、镜像、挂载、健康状态和 `RestartCount=0` 前后未变。

### 2026-08-20 复测：180 秒超时是否网络波动

同一套 12 case × 3 轮、AB/BA 交替的正式流程复跑了一次（报告 `.probe/studio_ab/results/studio-retest-20260820T122735Z/http-ab-20260820T125436.848336Z.json`，schema v2，70 个观测、34 个有效配对）。

| 组别 | 完整成功 | 中位耗时 | P95 耗时 | 误调用 |
|---|---:|---:|---:|---:|
| Router | 35/35 | 8710 ms | 24215 ms | 0 |
| Studio agent | 34/35 | 4699 ms | 9363 ms | 0 |

- 配对中位延迟差 `-4347 ms`，与正式实验的 `-3636 ms` 同向同量级，延迟优势可复现。
- 顺序效应仍不显著：Router first/second 中位 8710/8327 ms，Studio 4610/4882 ms。
- **那次 180074 ms 超时没有复现**，所以它确实是一次上游/网络波动，不是稳定缺陷。
- 但复测又出现一次 Studio 失败，且失败形态不同：`C05` 第 3 轮 HTTP 400、`error_category=protocol`、仅 5506 ms 就返回；Router 同一 case 三轮全成功。
- 结论修正：Studio 的失败不是单一超时原因，两次独立实验各出现 1 次失败（34/35、35/36 ≈ 97%），Router 两次都是 100%。因此“Router 默认、Studio 显式实验备选”的定位不变，不能因为超时未复现就把 Studio 提为默认。

### 2026-08-21 Studio 全协议实测（OpenAI / Anthropic / Responses）

> 结果边界：首轮全协议实测对应 `local/ciallo-m365:candidate-20260820-89f69b76070b`。之后补了三协议 SSE 限流语义，并将 Responses `response.failed.response.error.code` 修正为官方枚举 `rate_limit_exceeded`。2026-08-21 已用与最新工作树 102/102 个 Python 源文件 SHA-256 一致的隔离候选容器，再次完成严格流式工具闭环 smoke，所以下述结论已有最新代码的活体证明。

在与工作树逐字节一致的候选镜像里实测（`local/ciallo-m365:candidate-20260820-89f69b76070b`，101/101 个 `src` 文件 sha256 相同），账号 Key 的规划模式为 `studio`，响应头 `X-M365-Tool-Calling: studio`：

| 协议 | 非流式 | 流式 | 工具闭环 |
|---|---|---|---|
| `/v1/chat/completions` | 200，choices + usage | 200，`data: [DONE]`、usage 分片 `estimated=true` | tool_call → tool 结果续接 200 |
| `/v1/messages` | 200，`tool_use` + usage | 200，`tool_use` 事件 + `message_stop` | `tool_result` 续接 200 |
| `/v1/responses` | 200，`function_call` + usage | 200，`function_call` 事件 + `response.completed` | `previous_response_id` + `function_call_output` 续接 200 |

其余实测项：

- `/v1/images/generations`：200，`data[0].url` 是本地签名的 `/v1/m365-media?...sig=...`，没有回落 Designer 源 URL。
- 抓包/协议 profile：`capture-toggle` → `capture-payload` → `candidate` → `apply`（`source=captured`）→ `rollback`（`source=builtin`）全程 200，可回滚。
- `/admin/stats`：`calls_total>0`、`total_tokens>0`、`model_counts` 为字典、`estimated=true`。
- `/admin/` 首页：`dash-model-share`、`dash-donut`+`total_tokens`、`clearUsageStats` 三个挂载点都在。
- 调用日志脱敏：本次生成的 images 记录只留 `[generated image]`，无 `fileToken`，usage 记为 39 in / 7 out。

两个曾被记成失败、复核后确认是探针自身问题的项：

- `responses_stream` 400 是代理的正确行为。探针把 `tools` 清空却保留 `tool_choice=required`，代理按契约回 `Responses tool_choice=required requires at least one function tool.`；去掉 `tool_choice` 后流式 200、`response.completed`、usage 齐全。
- `validate_full_http.py` 里 `admin.login_status=401` 是它用 API Key 当管理员密码；改用容器内 `ADMIN_PASSWORD` 后全部 200。

#### 2026-08-21 最新工作树严格流式闭环复测

隔离候选容器只绑定一个专用 M365 测试账号；对应 Key 已启用、`tool_planning_mode=studio`，Studio agent 已绑定且 token 有效。生产容器和生产卷未参与请求。严格探针对 Chat、Messages、Responses 各执行首轮工具调用和二轮工具结果闭环，共 6 次真实 HTTP 请求：

| 协议 | 首轮 | 闭环 | Studio 路径 | 完成标志 |
|---|---:|---:|---:|---|
| Chat Completions | 200，1 个 tool event | 200 | 两轮均确认 | 两轮均 `[DONE]` |
| Anthropic Messages | 200，1 个 `tool_use` | 200 | 两轮均确认 | 两轮均 `message_stop` |
| OpenAI Responses | 200，1 个 `function_call` | 200 | 两轮均确认 | 两轮均 `response.completed`；使用 `previous_response_id` |

三协议均通过 JSON Schema 参数校验，`error_category` 全为空。真实 HTTP 返回的响应头是小写 `x-m365-tool-calling`；首版严格探针把大小写不敏感的 HTTP 头转为普通 `dict` 后又按标题大小写查找，曾误判为非 Studio。已用失败回归测试复现并改为大小写无关读取，整套 probe `208 passed`。

脱敏报告：`.probe/studio_ab/results/live-stream-20260821/stream-closure-20260821-164620.json`，SHA-256 为 `c1c7536802ebe78d128e6fa150e5b83ae89c66588a264927f3a9c60e6fdc43d1`；报告只有 HTTP 状态、事件计数、完成布尔值、延迟和错误类别，不含 Key、token、账号标识、提示词、参数值或响应正文。

一次真实缺陷（已修）：`_safe_image_record_text` 的兜底正则写成 `r"fileToken=[^&\\s)]+"`，字符类里 `\\s` 是「反斜杠或字母 s」，遇到含 `s` 的 token 会在 `s` 处截断，把后半段留在调用日志里。已改为 `[^&\s)]`，并加了一条含 `s` 的 token 回归测试。主路径（Designer URL 整段替换成 `[generated image]`）本来就没漏，所以只影响兜底分支。

另外调用日志里还有 1 条 `fileToken` 命中，来自 23:17 修复前写入的历史记录（ts 1787238236），不是当前构建产生的；容器 token 卷里的旧记录会随 100 条上限自然滚出。

### 2026-08-20 M365Bridge v1.4.0 复核

v1.4.0（2026-08-20 12:58Z 发布）确实有值得抄的东西。仓库仍无 LICENSE，因此只取思路、不取代码。按对本项目的价值排序：

1. **流式先提交响应头 + 上游静默期保活**（"Commit stream headers before the upstream turn and keep every SSE stream alive during upstream silence"）。已按 clean-room 方式补入 `_anthropic_stream_with_tools`：先发 `message_start`/`content_block_start`/`ping`，上游静默期间每 10 秒发 `ping`，并在生成器取消时关闭待处理迭代器；相关回归测试已通过。统一 write deadline/断连测试仍是后续工作。
2. **token 计数改用 `o200k_base` 并上报来源**。我们现在是估算 + `estimated=true`，可以升级成 `token_source` 字段；但精确计数要引入 tiktoken 依赖，值得先只加字段、把精确计数放在可选开关后面。
3. **工具调用卫生**：拒绝重复的 tool_call id、拒绝对不上任何已声明调用的 tool_result、按 JSON Schema 校验参数、限制一轮内的 tool 轮数。我们已有 schema 过滤和 `tool_choice` 校验，缺 id 唯一性与孤立 tool_result 的拒绝。
4. **错误分类**：把类别放 `type`、机器可读串放 `code`，并携带上游 HTTP 状态；上游 quota/限流单独上报。我们已把 `Throttled` 映射为 429，这两条是增量。
5. **Anthropic thinking 块补 `signature` 字段**，以及 Responses 的 `custom_tool_call` 输出形态。属于客户端兼容细节。
6. `/mcp` JSON-RPC MCP 服务端、evidence ledger、web_search 不下发客户端：功能较大，暂不排期。

已核对为「我们已经有」的项：`x-api-key` 认证（`auth_middleware.py:99`）、生成图下载限定主机（`media_proxy.py:57`）、会话映射路由、按 tone 选择推理模型。

## 后续顺序

1. Copilot Studio 账号级显式实验模式已实现，正式 A/B + 一次复测完成，三协议全链路实测通过；Router 继续默认，不自动推广 Studio。
2. 统一三协议的 write deadline/客户端断连释放测试，并覆盖 Studio fallback 的取消路径。
3. 下一候选：若租户具备所需权限，验证官方 Graph chatOverStream Provider。
4. usage 从 `estimated` 升级为带 `token_source`，精确计数放可选开关。
5. 工具调用卫生：tool_call id 唯一性、孤立 tool_result 拒绝、单轮工具轮数上限。
6. 需要补协议测试时，再从 sideefffect 和 kuchris 提取可验证的测试思路。

## 当前判断

- 当前项目不需要换仓，也不需要跨用户账号调度。
- Copilot Studio 两次独立实验各出现 1 次失败（97%），Router 两次 100%，因此不能默认替换 Router；但 180 秒超时未复现，说明那是波动而非固有缺陷。
- Studio 的延迟优势可复现：正式配对中位快 3636 ms、复测快 4347 ms，值得保留为单人单账号的显式低延迟实验备选，且已在 OpenAI / Anthropic / Responses 三协议（流式与非流式、含工具闭环）实测通过。
- jairbj 式动态协议 profile 已落地为 `protocol_profile.py` + 抓包捕获，可 apply/rollback；usage 与首页调用占比圆环已实测有数据。
- 最值得长期补充的是官方 Graph Provider；缓冲流的 SSE preamble/保活已落地，统一断连和写超时仍待补齐。
- 任何候选都不能原样公网部署；必须保留当前项目的下游鉴权、用户隔离、凭据加密和媒体 SSRF 防护。
