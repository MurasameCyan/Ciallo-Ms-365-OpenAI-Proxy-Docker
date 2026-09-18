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
| 6 | [sideeffffect/m365_openai_proxy.py](https://github.com/sideeffffect/m365_openai_proxy.py) | Apache-2.0；单文件 Python；带多项协议测试 | SignalR/ChatHub 逆向说明；token refresh race、会话连续性、限流、图片等测试思路 | 单账号、本机工具；无下游鉴权；工具调用是概率性模拟；无标准 Docker 服务架构 | 适合补协议回归测试，不适合直接部署 |
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

## 2026-08-25 实测：cramt/m365-copilot-proxy 扫描出的两条声明

两条都来自 GitHub 扫描的「可能可用」清单，各跑真实上游轮验证（探针 `.probe/ci_ab.py`、`.probe/agentless_tools.py`，账户 `acct_2eed3918214f`，容器内 `/app/.venv`）。

### 声明一：`cwc_code_interpreter*` optionsSets 解锁服务端 Python —— 一半成立

服务端执行确实是真的，但**不是这些 flag 开出来的**。判据用「不执行就答不出」的 oracle：探针启动时现铸的 nonce 的 SHA-256、以及两个 12 位随机数的精确乘积。

| 组 | optionsSets | SHA-256 | 乘积 | 帧 |
| --- | --- | --- | --- | --- |
| WITH | 生产原样 | 正确 | 正确 | `GeneratedCode` |
| WITHOUT | 抽掉全部 6 个 `code_interpreter` flag | 正确 | 正确 | `GeneratedCode` |

抽掉 `cwc_code_interpreter`、`cwc_code_interpreter_amsfix`、`cwc_code_interpreter_citation_fix`、`code_interpreter_interactive_charts`、`code_interpreter_interactive_charts_inline_image`、`code_interpreter_matplotlib_patching` 之后，答案与线上帧序都没变，所以在本租户上它们不承重（`_ALLOWED_MESSAGE_TYPES` 里的 `GeneratedCode` 才是我们能收到结果的原因）。保留是因为它们与浏览器流量一致；oracle 没有覆盖图表形状的那三个，所以没有删。

`tone=Claude_Sonnet` 同一 oracle **无 `GeneratedCode` 帧**，并且编了一个假摘要。当天最初据此写成「会算的 tone 不听工具契约，听契约的 tone 不会算」，**同日第二轮把这个推广否掉了**（见下面「一句话补上不带工具的那半」）：解释器是按 tone 分的，不是按家族分的，`Claude_Sonnet_Reasoning` 两个 oracle 全对且帧里有 `GeneratedCode`。成立的是窄版本：`Claude_Sonnet` 听契约但不会算。

### 声明二：Claude tone agent-less 工具调用 —— 成立，且我们本来就是这条路

本仓库从来不创建 Studio agent（`studio_agent_discovery.py` 只绑定用户自己建好的），`studio_agent_id` 全程是可选 kwarg，所以「省掉创建/维护开销」对我们已经实现。实测用生产形状（`translate_openai_request` 出的真契约 + `_extract_tool_calls` 解析），客户端不带 agent：

| tone | 需要工具的提问 | 不需要工具的提问 |
| --- | --- | --- |
| Claude_Sonnet | `Read` 调用正确 | 正常回答 + `NO_TOOL_NEEDED` |
| Claude_Sonnet_Reasoning | `Read` 调用正确 | 未测 |
| Magic（对照） | 0 调用，回「读不了你的文件」 | 未测 |

与 2026-08-18 的 tone×tool 矩阵一致，账户上虽然绑着 agent 也不需要它。**「绕过 Disengaged」这半没有验证**：两个探针的提问都是良性的，不带 agent 也不会触发 jailbreak 分类器，要证伪或证实得用会被判 Disengaged 的提问对照，本轮没做。

### 2026-08-25 决定不验证「绕过 Disengaged」

不做，理由按重要性排：

1. **两种结果都不改代码**。我们已经在 agent-less 这条路上（不创建 agent），Studio 是用户显式选的备选。「agent-less 不被扫」成立 → 现状不变；不成立 → 现状也不变。
2. **不是活着的问题**。生产 `call_log.json` 满 100 条里 `disengaged` / `refused this turn` / `empty response twice` / `offense` / `jailbreak` 命中数全为 0；8 条 error 全是个人版 `partialImageGenerated` 断连那一族。（`docker logs` 在重启后只剩 17 行，问不出比例，别再用它当分母。）
3. **验证代价是拿唯一的 M365 工作账号去踩微软的 jailbreak 分类器**——要证实必须构造会被判 Disengaged 的提问，反复触发的账号级后果不可回滚，换来的信息按第 1 条又不驱动任何改动。

要是哪天真出现成批 Disengaged，再验证就有意义：那时对照组是「同一提问 × 带/不带 agent」，判据用 `Disengaged` 帧本身（`_ALLOWED_MESSAGE_TYPES` 已经收它）。

### 2026-08-25 缓解「会算的 tone 不听契约」：契约里加一条

上面那条取舍里，只有一半能在代码层兜住，而且能兜的这半原来漏得比想象的严重：**声明了工具但没有一个能执行代码时，Claude tone 会先把编造的 64 位 hex 吐进流里，再在同一轮里自己撤回**。撤回对人有用，对按第一个 hex 块取值的客户端没用。

于是给 `_DEFAULT_TOOL_SYSTEM_PROMPT` 的 Rules 加了一条：需要精确计算而列表里没有能执行代码的工具时，明说算不了，不要凭记忆给值。实测（`tone=Claude_Sonnet`，每格一轮真实上游，现铸 nonce 的 SHA-256）：

| 形状 | 基线 | 加规则后 |
| --- | --- | --- |
| 声明了 `bash` | `tool:bash` 4/4（**本来就对，所以没写「去调工具」那半**） | `tool:bash` 1/1 |
| 只声明 `Read`（不能执行） | 编造 64 位 hex 2/2，随后同轮撤回 | 0 编造 5/5，开口就说算不了并给出自己算的命令 |
| 完全不带 tools | 编造且不撤回 | 这条轮次没有契约，规则进不去 —— 见下一节，已另外兜住 |
| `2 + 2` 对照 | — | 仍 `NO_TOOL_NEEDED`，没有因为这条规则去调 shell |

两个边界写进了探针和测试，别在改措辞时丢掉：**条件**（只有「没有工具能执行」时才适用，去掉条件会连 `bash` 都不调）和**位置**（规则在 Rules 末尾、Examples 之前；`.probe/compute_rule_shipped.py` 校验拼出来的提示词 sha256 等于工作树的 `default_tool_system_prompt()`，`3f67b933…` —— 措辞一改 sha 就变，改完得重测而不是沿用这张表）。规则在管理端可覆盖的那段里，管理员自定义系统提示词就自己负责这条（回归测试 `tests/test_exact_computation_rule.py` 把这个天花板也断言了）。

`/user` 的「默认配置」卡片加了一句 `user_no_interpreter_hint`（中英），措辞见下一节（最初写的是「claude 系模式」，被同日的第二轮测量改成只点 `claude-sonnet-4-6`）。之所以是卡片级提示而不是 tone 下拉项的 tooltip：`/user` 的 `#tone` 一直是 `display:none`（模式跟着模型名走），tooltip 挂上去没人看得见。

评估过但没做的「更底层」办法：按提问判断「需要精确计算」再把这一轮偷偷换到 `Magic` 之类会算的 tone。否决理由是它要一个自然语言分类器（每轮多花上游往返、且误判会静默换掉用户选的模型），还会打断持久会话的连续性 —— 代价和爆炸半径都远超它修的问题。

### 2026-08-25 一句话补上不带工具的那半（并否掉「Claude 系不会算」）

上表最后一行原来记成「代码层无解」。实际有解，而且顺手挖出一个更要紧的更正。

先是解释器的归属：**它按 tone 分，不按家族分**（`.probe/reasoning_interpreter_frames.py`，同一 session 三格，nonce 现铸）。

| tone | SHA-256 | 12×12 位乘积 | 帧 |
| --- | --- | --- | --- |
| Claude_Sonnet_Reasoning | 正确 | 正确 | `GeneratedCode` + `python` |
| Claude_Sonnet（同 session 对照） | 错，且自称「我直接用 SHA-256 算法算」 | 未测 | 无 `GeneratedCode` |

所以 `claude-sonnet-4-5`（= `Claude_Sonnet_Reasoning`）是**唯一两半都实测通过**的选项：工具契约 verified（2026-08-18 矩阵）＋ 服务端执行 verified。要指一条出路就指它，而不是指不会调工具的 Copilot 系 —— `/user` 那句提示因此重写成「`claude-sonnet-4-6` 没有服务端代码执行……要精确结果就声明一个能执行命令的工具，或改用 `claude-sonnet-4-5`」，并且改口说这类提问现在会直接答「算不了」（上线后就是这个行为，不再是给错值）。

投递路径：不带工具的轮次里客户端 `system` 消息**能**到上游（落成 `System instructions:` 块），但真正上线的位置是 `substrate_parse._combine_text` 把一句话接在 prompt 之后 —— 与 `[FORMAT]` 同一格，因为**位置是提示词的一部分**。按上线位置实测（`.probe/compute_no_tools_shipped.py`，容器跑的是旧镜像，所以每格自己拼出上线文本、以空 context 发出去，旧 `_combine_text` 原样透传；探针里钉了这句话的 sha256 `9540cfb2…`）：

| 格 | tone | 加句子 | 结果 |
| --- | --- | --- | --- |
| S1 | Claude_Sonnet_Reasoning | 否 | **答对**（这格本来是要给它坐实 `absent` 的，反而推翻了它） |
| S2 | Claude_Sonnet | 是 | 「I cannot compute this exactly here」，无 64 位 hex |
| S3 | Claude_Sonnet_Reasoning | 是 | 仍答对 —— 它无视这句话照样执行，等于反证了这句话不能乱发 |
| S4 | Claude_Sonnet + 常识题 | 是 | 「Paris.」，没被带成拒答 |

落地就是 `TONE_SERVER_INTERPRETER`（`Magic` / `Claude_Sonnet_Reasoning` = verified，`Claude_Sonnet` = absent，其余 unknown）＋ `_combine_text(prompt, context, tone)`：**只有** `absent` 且本轮没有工具契约时才追加。三条约束和工具那半同理，都有测试盯着：unknown 必须等于「什么都不说」（没测过不等于没有，微软的 rollout 一直在动）；带 tools 的轮次不追加（那半的规则是有条件的，一轮里两套说法会互相打脸）；`tone=None` 的个人版链路不受影响（它自己那份契约有字符预算，且从没测过这个题目）。差点上线的 bug 就是 `Claude_Sonnet_Reasoning` 我按家族猜了个 `absent` —— S1 那格把它拦下来了，测试里也钉住了。

天花板：这一整套都还是提示词级的。代理无法校验任何一个声称的哈希（错的和对的形状完全一样），所以「tone 无视这句话」在下游探测不到；能做的只是别对着有解释器的 tone 撒谎。

### 2026-08-25 补齐 `TONE_SERVER_INTERPRETER`：会编哈希的只有一个 tone

上面这套是测量驱动的，`unknown` 一律不说话 —— 所以**没测过的 tone 就是没兜住的 tone**，map 的覆盖面等于修复的覆盖面。把剩下 11 个 tone 各跑一格 oracle 扫完（`.probe/interpreter_scan.py`，nonce 现铸，不带工具，同时录帧）：

| 结果 | tone | 帧 |
| --- | --- | --- |
| 答对（= 有执行） | Chat、Gpt_5_5_Chat、Gpt_5_5_Reasoning、Gpt_5_4_Chat、Gpt_5_4_Reasoning、Gpt_5_3_Chat、Gpt_5_2_Chat | 有 `GeneratedCode` |
| 答对，但没抓到帧 | Reasoning、Gpt_5_6_Reasoning | 无 |
| 上游拒答（可用性问题，不是能力问题） | Gpt_5_3_Reasoning（`InternalError`） | — |
| 既没算也没编：120 秒后把自己的工具调用当正文吐出来 `{"code":"import hashlib\n..."}` | Gpt_5_2_Reasoning | 无 |

所以**全 16 个 tone 里，实测会编造哈希的只有 `Claude_Sonnet`**（`claude-sonnet-4-6`）。这不是抽样缺口而是问题的全部人口，那一句话覆盖的一格就是全部。判据说明：现铸 nonce 的 64 位 hex 无法凭记忆命中，所以**「答对」本身就是执行的证据**，帧只是旁证 —— `Reasoning` / `Gpt_5_6_Reasoning` 没抓到 `GeneratedCode` 仍记 verified，就是这个道理。后两格故意不进 map：拒答的那格是可用性，吐 JSON 的那格既不编也不算，写成 `absent` 只会给它加一句它不需要的话，而且两种失败都不是提示词能修的。

九条 verified 进 map 不改变行为（verified 与 unknown 都不追加），值在于把「没测过」变成「测过了」，并且挡住下一次按家族猜 `absent` —— 回归测试直接断言 `absent` 列表**只有** `Claude_Sonnet`。

顺带把这张取舍表填满了：`Magic` / `Reasoning` / `Gpt_5_6_Reasoning` / `Gpt_5_5_*` 会算但不听工具契约（2026-08-18 矩阵）；`claude-sonnet-4-6` 听契约但不会算；`claude-sonnet-4-5` 两半都行。

### 2026-08-25 复查上线路径：router 的分类轮必须排除

`_combine_text` 判「本轮有没有工具契约」看的是 context 里有没有 `tool_call`，所以把每个**空 context** 的调用点都数了一遍，一共三个（第一遍只数出两个，漏了管理端探针）：

1. **router 的分类轮**（`tool_router._router_decision` → `client.chat(router_prompt, [], None)`）—— 契约在 **prompt** 里而不是 context 里，`has_tools` 看不见它。这一格必须排除：那段提示词里列着能执行的工具（可能就是 shell）、还要求「EXACTLY ONE line」，追一句「你没有代码执行能力」等于自相矛盾，会把本该 `CALL_TOOL: bash(...)` 的哈希请求变成拒答。判据用 `NO_TOOL_NEEDED`（`tool_call_parser._NO_TOOL_MARKER`）—— 它是 router 契约在 prompt 通道里的指纹，回归测试直接拿真的 `build_router_prompt()` 拼，措辞改到丢掉这个 marker 就会红。触发条件不是理论上的：`auto` 模式下 `Claude_Sonnet` 是 verified 所以不走 router，但管理端把 planning 模式钉成 `router` / `studio` 就会走。
2. **`/v1/images/generations`**（`routes_api_images:151` 发 `Generate exactly one image...`，空 context）—— 不排除，而且这次拿真上游量了，不再只靠类比。
3. **`/admin/model-test`**（`routes_admin_modeltest:116` 发 `Reply with one word: pong`，空 context）—— 第一遍漏掉的一格。它走 `apply_request_model`，所以 `_tone` 照样是 `Claude_Sonnet`，这句话确实会追上去；判据 `classify_probe` 只看回复非空，量了也不排除。

**后两格的实测**（`tone=Claude_Sonnet`，每格 baseline / patched 各一轮真上游，patched 用现网措辞、脚本先校验 `_NO_INTERPRETER_NOTE` 的 sha256 = `9540cfb2…` 再花 token）：

| 格 | baseline | patched（追了那句话） |
| --- | --- | --- |
| `/v1/images/generations` | 出图，1 个 `document.ashx` url，590 字符 | **仍出图**，1 个 `document.ashx` url，618 字符 |
| `/admin/model-test` | `ok`，回 `Ping! 🏓` | `ok`，回 `Ping` |

出图那格是真正值得花这轮 token 的一格：那句话是「算不出来就说算不出来」，理论上完全可能把模型劝退成只描述不画。实测没有。两格都成立的原因同一个——那句话本身带条件，只在被要求精确计算时适用。

**这份枚举现在是机器校验的**：`test_the_empty_context_callers_are_the_three_that_were_audited` 扫 `src/` 里 `.chat(x, [])` / `.chat_stream(x, [])` 的形状（跨行匹配、跳过注释行），断言按文件计数正好是这三处。加第四个空 context 调用点就会红，逼着加的人回答 router 那个问题（这段 prompt 自己带不带冲突契约），而不是等线上发现。

同时补了三条端到端管线测试，盯住「map 的 key 在生产轮次里真的取得到」：`claude-sonnet-4-6` → `resolve_tone` → `Claude_Sonnet`（也断言 `/user` 指的出路 `claude-sonnet-4-5` 解析得到），以及真的建一个 `SubstrateCopilotClient`、按 `apply_request_model` 的方式赋 `_tone`、截获 `_stream_turn_with_retry` 收到的 `text` 断言那句话在里面。少了这层，改个 label 或者 tone 解析回落到默认，都会让这句话在生产里静默不发，而只测 `_combine_text` 的单测一个都不会红。

## 2026-08-30 GitHub 复扫：找可以直接用的代码（不是找可以换的仓）

这轮的问法和 08-20 那批不同：不问「有没有更好的反代」，问「有没有**许可证允许我们拿进来**的代码能补我们已知的缺口」。本项目是 Apache-2.0，所以 MIT / Apache-2.0 / BSD / ISC 可以采纳，AGPL / 无许可证只能读不能抄。

### 方法上的一个坑（别重复踩）

GitHub 仓库搜索只对 **name + description** 做 AND 匹配，不做全文。所以 `tiktoken o200k tokenizer language:python stars:>50` 这种多词查询必然 0 结果 —— 第一轮六条 gap 查询全空，不是「没有项目」而是查询写法错了。改成单词级 loose query（`copilot2api`）+ 已知仓库直查 + `gh search code` 三条腿才拿到信号。另外未认证的 search 配额只有 10 次/分钟，`gh` 已登录（scopes `repo` / `read:org`）能用 code search，走本机就行；只有 `api.github.com` 不通时才需要绕到 m365-server。

### 许可证警报：两处不能抄

- **HEXUXIU/M365-Copilot2API 又收紧了。** 我们记的是「v0.5.1 起转 AGPL」，现在实际是 **AGPL-3.0 + 依 Section 7 追加的非商业 API 中继限制**（明文禁止把它或其修改版作为付费/商业 API 中继运营），GitHub 因此把 spdx 标成 `NOASSERTION`。它已经不是 OSS，`docs/protocol-options-diff.md` 那种「只抄协议字段与端点」的边界要继续严守，代码一行都不能进来。
- **`jerbehe/m365-copilot2api`（3★，Go）看着可采纳，实际不能碰。** GitHub API 报 `fork:false`、仓库自带一份 MIT LICENSE（署名 "m365-copilot2api contributors"），但它的 README 第一行写着「分叉自 HEXUXIU/M365-Copilot2API」，README 里的 license badge 还指向 **HEXUXIU 的**仓库。也就是手工复制后重新许可为 MIT —— AGPL 洗不成 MIT，从它这里抄等于抄 HEXUXIU。**把它当 AGPL 对待。**

### 真正可采纳的三样

| 项目 | 许可证 | 补的缺口 | 状态 |
|---|---|---|---|
| [protella/chatgpt-bots](https://github.com/protella/chatgpt-bots) | MIT，6★，2026-08-28 活跃 | 引用标记清理的**关键字无关**写法 + 残留 PUA 兜底扫；另有 prefix-stable 流式 hold-back | 见下面实测，按需 |
| [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) | MIT，853★ | 我们 CI 完全不跑测试 | 直接可用 |
| [openai/tiktoken](https://github.com/openai/tiktoken) | MIT，19117★ | usage 仍是 estimate | 容器能到 `openaipublic`（200），但当前未安装 |

### protella 的清理器：形状差异是真的，但生产 0 样本

它清同一套 substrate PUA 引用体系，写法比我们宽：`.*?` 吃任意 opener→closer 跨段（**不要求出现 `cite` 这个词**），再加一条 `[-]` 残留扫。我们的 `_BARE_PUA_CITE_RE` 要求字面量 `cite`。实测（`.probe/cite_keyword_gap.py`）差异后果比「漏一个 id」更难看：

| 输入 | 我们的输出 | 用户看到 |
|---|---|---|
| `citeturn3search5` | 干净 | 正常（这是 `2ad5b6a` 修好的那半） |
| `navlistturn0search1` | `navlist` | `参考这些来源。navlist继续正文` + 2 个裸 PUA |
| `fileciteturn0search1` | 同上 | `filecite` 也漏 —— 我们的规则要求 PUA **紧邻** `cite` |

孤儿尾规则把 **id** 吃掉了，却把**关键字和两个裸 PUA 码点**留给客户端（裸 PUA 在下游会渲染成任意字形/emoji）。

**但生产没有这个形状。** 扫 100 条 call_log（`.probe/prod_pua_keywords.py`）：含 PUA 的 4 条，码点库存只有 `U+E201`×7 和 `U+E202`×2，**`U+E200` opener 0 个、非 `cite` 关键字 0 个**。按我们否决 HEXUXIU 内容策略分类和卡死工具循环时的同一条标准（0 生产样本不排期），这条也不排期。要做的话理由只能是纵深防御，而不是「有新形状出现」。

顺带用同一批数据确认了两件事：

- **`2ad5b6a` 的引用修复在生产是干净的。** 4 条泄漏最晚 2026-08-25 22:44，修复上线是 08-28 05:37，**上线后 0 泄漏**；把这 4 条喂回当前 cleaner，正好 4 条会被改变（147 条无变化），即它确实盖住了这些形状。
- **我们 docstring 自认没盖住的「id 内部被切开」，生产 0 样本**（`.probe/mid_id_split_leak.py`；唯一命中是我的正则在一段随机 token 里匹配到 `Turn6`，假阳性）。protella 的 `stream_safe_text` 正是那条路的解（遇到未闭合 opener 就截断并 hold back，保证 append-only 流的 prefix 稳定），值得记着，但同样没有活样本。

如果哪天要做，安全边界已经量过：**narrow 扫 `E200-E20F` 是安全的，broad 扫 `E000-F8FF` 不安全** —— Powerline `U+E0A0`、Devicons `U+E73C`、Seti-UI `U+E5FA`、Font Awesome `U+F09B` 都落在 broad 区间内、都不在 narrow 区间内，而一个编码代理完全可能在讨论 shell 提示符或字体时正常携带这些字形。

### 一处对我自己先前结论的更正：Anthropic 静默期保活**已经在**

我此前两次报告「`_anthropic_stream_with_tools` 在 `async for` 缓冲期间什么都不发，只有开头一个 ping」，并据此说本文件第 195 行「上游静默期间每 10 秒发 ping」与代码不符。**第 195 行是对的，我错了。** 缓冲循环体内确实不 yield，但 `routes_api_messages.py:423` 把整个生成器包在 `keepalive_stream(stream, heartbeat=ANTHROPIC_PING)` 里，`DEFAULT_KEEPALIVE_SECONDS=10.0`；`keepalive_stream` 用 `asyncio.wait({pending}, timeout=interval)`，内层 `__anext__` 未 resolve 就 yield 心跳 —— 所以「整轮缓冲」和「周期 ping」不冲突。实测（`.probe/anthropic_silence_keepalive.py`，interval=0.25s 驱动 stall 1.1s 的生成器）：**4 个 ping，等于预期**，真实帧在 stall 后到达；`aclose()` 后内层生成器 `finally` 执行，断连释放也在。教训：判断流式行为不能只读生成器函数体，得看它在 `StreamingResponse` 里被什么包着。

### 其余核对

- **CI 确实只有一个 job**（`.github/workflows/docker.yml` 里的 `build-and-push`，全仓库仅此一个 workflow，`pytest` 一次都没出现），所以那 1725 条测试是纯本地门禁 —— 谁忘了跑，CI 不会拦。`astral-sh/setup-uv` 是现成解法。
- **`microsoft/Agents-M365Copilot` 状态未变**：MIT、104★、2026-08-24 活跃，但最新 release 仍是 `preview.19`（2026-08-05，`prerelease=true`），5 个 open issue。仍是「下一个候选」，不是「已可用」。
- **`sideeffffect` 是四个 f**（本文件原先写成三个 f，已改）。仓库活着，2026-08-04 有推送，不是消失。
- **GitHub Copilot 系不算候选**（`StarryKira/copilot2api-go` 138★、`whtsky/copilot2api` 29★ MIT）：上游是 GitHub Copilot 不是 M365，与本文件开头的排除项一致。
- 其余新面孔都不构成候选：`Bosco1262/…-on-Cloudflare-Worker`（2★ NOASSERTION）、`6Kmfi6HP/copilot-openai-proxy`（1★ NOASSERTION）、`avryhof/m365-copilot-bridge`（1★ MIT）、`NicolaiLassen/m365-copilot-openai-proxy`（0★ Apache-2.0）。

## 2026-09-01 复扫：25 个新仓，唯一收获是别人的协议知识挖出了我们自己的缺陷

延续 08-30 的问法（找**许可证允许拿进来**的代码），这轮新克隆 25 个仓。**没有一行代码可搬**，但其中一份文档指出的协议事实让我们查出一个真实缺陷并修掉。

### 许可证与派生判决

可采纳许可证（MIT/Apache-2.0）的：`mahmoudsallem/m365-copilot-proxy-claude`(MIT,1★,TS)、`uefi2333/m365-native`(MIT,47★,Go)、`winnstorm/m365-copilot-api`(MIT,4★,Py)、`lezi-fun/m365-copilot-client`(MIT,11★,Py)、`renepajta/m365-copilot-mcp`(MIT,10★,Py)、`imxiaorong/M365-Copilot-API`(MIT,2★,Py)、`Scluzlep/E5-M365Copilot-API`(MIT,3★,Py)、`renefichtmueller/adaptive-llm-gateway`(Apache-2.0,11★,TS)。

不可采纳（NONE/NOASSERTION，只能读）：`clabrado/mcopilot`、`ryc2077/m365plus`、`ryc2077/M365-Copilot2API-simulated-tools`、`miau/ms-copilot-gateway`、`notBlubbll/g365-headless-relay`、`BufferingForever`/`JARVIS-no1`/`wade019599`/`xinyc11260`/`Yang-iyu`/`s12ryt`/`zyads`/`ElSrJuez` 各自的仓。

两条派生判决：

- **`xiaocongyu66/m365-copilot2xapi`（MIT,0★,Go）按不可采纳对待。** 三个信号叠加：LICENSE 署名 **Chenyme**（不是仓库主），`backend/cmd/grok2api` 说明骨架来自别人的 grok2api，仓库名 `M365Copilot2ApiX` + `go.mod` 的 `M365Copilot2ApiX/backend` 指向 HEXUXIU 的 `M365-Copilot2API`，且 README 对两者都无致谢。逐文件哈希比对 hexuxiu(131 个 go) × xiaocong(329 个 go) = **0 个字节相同**，所以不是复制粘贴，但同 `jerbehe` 那次一样，署名链断了就按 AGPL 处理。
- **`uefi2333/m365-native`（MIT,47★）是独立实现。** README 把 HEXUXIU 列在「Reference repositories」而非声明分叉，`addToChainOfThought` 在它代码里 0 命中（HEXUXIU 有 3 处），只有 `ChatHub` 这类协议名重合。可采纳。

### 真正的收获：`mahmoud` 的 F17.10 指出了 ChatHub 会发推理旁白

`mahmoudsallem/m365-copilot-proxy-claude` 的 `docs/hypotheses.md` F17.10 记着（并致谢 HEXUXIU 的解析器）：bot 消息带 `contentOrigin:"ChainOfThoughtSummary"` 或 `addToChainOfThought:true` 时载有多步推理转录。我们代码里 `contentOrigin` 只在一句注释里出现过，`ChainOfThought` 零命中。

实测（`.probe/cot_frames2.py` / `fallback_shapes.py`，tone=Reasoning，搜索型提问）确认帧是真的，并测出比上游两家更准的判据：

| 赢下 `fallback_text` 反向扫描的条目 | 次数 | 是答案吗 |
|---|---:|---|
| `messageType` 缺失 + `contentOrigin:DeepLeo` | 24 | 是 |
| `Progress` + `ChainOfThoughtSummary` + cot=true | 6 | 否，推理转录 |
| `Progress` + cot=true（`Searching...`） | 5 | 否 |
| `Progress` + `EarlyProgress` + cot=false（`Gathering details…`） | 3 | 否 |
| `ReferencesListComplete`（空文本） | 3 | 否 |
| `Progress` + cot=false（`Searching...`） | 1 | 否 |

**判据是 `messageType`，不是 CoT 标记。** HEXUXIU 和 mahmoud 都只认那两个 CoT 标记，那样会漏掉最后两行（`EarlyProgress` 与无标记的 `Searching...`）——它们同样能赢下扫描。

### 缺陷与修复

`substrate_client` 的反向扫描取「最后一条非 user 消息」，不问是什么，所以旁白能成为本轮的权威全文。回放一次抓下来的生产轮（`.probe/cot_capture_frames.py` + `cot_replay.py`，277 帧，同一输入跑两版）：

- 未修：t==3 拿到的 `fallback_text` 是 **996 字的推理转录**（`fallback_is_cot=True`）
- 已修：是 **9326 字的真答案**（开头 `# Recommendation: SSE with explicit heartbeats`）

那一轮两版交付文本**完全相同**——它把整个答案都流出去了，下游 `_fallback_tail_after_delivered` 的锚点逻辑把追加抑制住了。所以这是**潜在缺陷**：只在「一个 delta 都没流出」或「只流出一部分」的轮次外显，那正是 `fallback_text` 存在的理由。修前/修后各三轮线上验证，`remainder_fallback_was_cot` 从 true 全变 false。

一处对我自己的更正：`.probe/cot_leak.py` 第一轮报过「P2 轮泄漏 1 条」，那是用 `cot_text in delivered` 判的，**无法归因**且后续三轮 + 回放都未复现。改用直接埋点（`cot_source.py` 记 `_final_fallback_remainder` 的入参与返回）后，真正站得住的证据是上面的 `fallback_text` 被替换，而不是「旁白出现在答案里」。别再用子串测试判这类泄漏。

修法：`substrate_parse._is_answer_entry`，两个独立信号（`messageType` 拒绝表 + CoT 标记），两处扫描点改为**跳过旁白继续找答案**而不是停在第一条非 user 消息（跳过后不赋值，好快照因此不再被旁白冲掉）。用拒绝表而非答案白名单：答案自身的形状是「根本没有 messageType」，白名单猜错会**丢答案**，比漏一行旁白严重得多；拒绝表也让固定文案拒绝（`BotConnection`，无 messageType）继续赢下扫描，tone 拒绝检测不受影响。

`tests/test_substrate_cot_narration.py` 19 条，帧形状照抄实测。变异测试跑了两个变异体（分别废掉 CoT 分支与 messageType 分支）确认无假绿：第一版有一条测试在变异下仍绿（短文本被锚点逻辑抑制），已换成「流一半靠兜底补尾」的场景；`ReferencesListComplete` 那条原先也不承重（完成帧把它修好了），已改成完成帧同样以它结尾。全量 1752 passed, 2 skipped。

### 顺带确认与否决

- **F17.11（sol/terra/luna → `Gpt_5_6_Reasoning`）我们已有**，`tone_options.py:32` 就是它，且我们 08-02 扫过那十二种拼法全空。无事可做。
- **上游把推理转录渲染成 Anthropic `thinking` 块 / OpenAI `reasoning_content`**：现在已知帧真实存在，这条从「不可行」变成「可做」，但要动三个协议渲染器，未做。
- `uefi2333`(3 文件) 与 `shenping1200`(5 文件) 用 tiktoken 做精确计数，只是印证 08-30 已定的方向（直接用 MIT 的 `openai/tiktoken`，不必移植 Go）。
- `xiaocong` 有 8 个文件涉及 write deadline（我们的待办 2），但按上面的判决只能读不能抄，且是 Go。
- `diegosouzapw/OmniRoute`（MIT,59385★）是个 352-provider 聚合器，含一个 `copilot-m365-connection.ts`；量级和目标与本项目不同，不构成候选。

## 2026-09-11 复扫：一个新的可采纳仓、一个全新上游、两个我们自己的缺口

延续 08-30 / 09-01 的问法（找**许可证允许拿进来**的代码补已知缺口）。窗口 2026-09-01..09-11。搜到 144 个仓，其中 138 个不在已知清单里；绝大多数是 **GitHub** Copilot 反代或 M365 管理/报表/readiness 工具，按本文件开头的排除项一句话否决。真正触到 substrate/ChatHub 或同族上游的只有下面几个。

方法提醒（与 08-30 那条并列）：仓库搜索仍只匹配 name+description，所以本轮用「单词级 loose query + 已知仓直查 + `gh search code`」三条腿。另外本轮 `gh api .../commits?since=` 有一次对 `protella/chatgpt-bots` 返回空、随后同一 endpoint 又正常返回 5 条 —— 空结果不能当「没有提交」，必须用第二次调用或换 `sha=<branch>` 复核。

### 唯一新的可采纳仓：`MasayukiTa/m365-copilot-companion-mcp`

MIT，6★，Python，973 文件，`fork=false`、`parent=none`、LICENSE 署名 "m365-copilot-companion-mcp contributors"，创建于 2026-05-27。派生核查：全树 `HEXUXIU` / `Copilot2API` / `addToChainOfThought` **各 0 命中**，是独立实现，可采纳。

它的 `relay/chathub.py` + `relay/chathub_capture.py` 打的是同一个 `wss://substrate.office.com/m365Copilot/Chathub`，而且整套是「先抓包再发」的：每个字段都注明是观测到的还是被服务端拒绝过的。逐条对照我们的代码：

| 它测到的事 | 我们的状态 |
|---|---|
| Researcher 的模型选择走请求而不是页面状态：同一 session 把 picker 分别停在 Default 和 Claude 各抓一次，只有一个非易变字段动了 —— `gpts[0].clientOverrides.deepResearchModels[0]: "Default" -> "Claude"` | **我们有缺口**，见下面「缺口二」 |
| `conversationId` 属于 URL 参数，写进 chat 帧是服务端回 `InvalidRequest` 的原因之一 | 已符合：`_chat_invoke` 的 payload 里没有 `conversationId`（`substrate_client.py:305-355`） |
| type 4 的 StreamInvocation 是用 SignalR **stream item**（type 2、载荷在 `item`）回的，只读 type 1 `update` 会拿到空答案 | 已有：`substrate_client.py:596-600` 读 type 1，`656-657` 读 type 2 |
| `messages` 快照不是增量，当成增量会把一个 `166` 变成 `166166166` | 已有：锚点抑制逻辑（`substrate_parse` + `_fallback_tail_after_delivered`） |
| `Progress` / `ChainOfThoughtSummary` 是旁白，不能进答案，但值得单独留下 | 09-01 已修并有 19 条测试 |
| 一个 session key 同时进 `chatsessionid` / `clientrequestid` / `XRoutingParameterSessionKey`；发三个不同的 per-turn id 是它测出的失败形态之一 | **差异但未验证后果**：我们只发 `ClientRequestId`（`substrate_client.py:268`），另两个键根本不发，而我们的请求是成功的。所以这条只记为差异，不记为缺陷 |
| 每次 capture 的 idle 等待：200 次里 min 8s / 中位 8s / p90 9s / max 16s；token 生命期 15-79 分钟 | 仅作参考量级 |

值得单独记一笔的是它的**取证边界**，因为它点到了我们：它明确拒绝「拿微软自家 first-party client id + family refresh token（FOCI）行为去 mint token」，理由是那是 2022 年起就有文档的滥用手法、绕过租户的 app-consent 治理，并且用测试断言这个文件里不出现任何 IdP 主机名。

我们必须诚实地对照：我们确实在 `refresh_via_rt.py:50` 和 `pkce_login.py:69` 用了 `c0ab8ce9-e9a0-42e7-b064-33d422df41f1`（Office web Copilot 的 native public client）。但**我们不是 FOCI 那个形态**：`_stored_binding` 把 client_id 钉在**签发这个 RT 的那个 client** 上（`M365_REFRESH_CLIENT_IDS`，`refresh_via_rt.py:46/50/99-118`），换不成另一个 client 去兑换，且 RT 本身来自用户自己走完的交互式 PKCE 登录。差别是「用签发它的 client 续期」而不是「跨 client 兑换」。剩下的那半——在交互式登录里报出微软自家的 client id——是真实存在的，本文件不替它辩解。

顺带交叉印证：下面那个完全独立的 Cowork 仓也把 `c0ab8ce9-…` 记成 Cowork 的公开 **M365ChatClient** app id（scope `6ab48b67-cd74-4ad4-81af-5932984589be/access_as_user`），两个互不相干的仓给出同一个值。

### 全新上游：M365 Copilot **Cowork**（`bakapiano/m365-copilot-cowork-proxy`）

无许可证（只能读），JS，0★，2026-09-09 才建。重要的不是代码而是**它打的不是 substrate**：

- 上游 `https://mcsaetherruntime-seas.as-ia101.gateway.prod.island.powerapps.com`，即 Power Apps 侧的 runtime，不是 `substrate.office.com`。
- 不是 SignalR：`GET /v1/subscribe?conversationId=…` 拿 SSE，再 `POST /v1/messages` 投递（`{content:[{text,type}],conversationId,messageId,queue:true,role:"user"}`），另有 `GET /v1/models`。
- 事件名是两字母的：`dx`（增量在 `data.t`）、`fr`（权威全文在 `data.content` + `stop`）、`rl`（`st=="ok"` 才算完成）、`error`/`err`。**没有 `fr` 就没有权威答案**，它据此报错而不是拿增量凑。
- 载荷可压缩：`{compressed:true,data:<base64(gzip)>}`，它对 base64 做了往返校验并把解压上限钉在 4 MiB、SSE 单帧上限 1 MiB。
- 头部是 `x-tenant-id` / `x-user-id` / `x-conversation-id` / `x-request-id` / `x-copilot-timezone` / `x-container-config`，模型和推理档位都在 `x-container-config` 里以 `model=…;reasoningEffort=…` 的形式传，Origin 是 `https://copilot.cloud.microsoft`。
- 模型 `melon` = Fable 5.1；它自陈 Cowork 的流里**没有权威 token 计数**，usage 全填 0 并靠响应头标注。

这是我们从未记录过的第二个上游面。**本账号是否有 Cowork 权限未测**，所以这条现在只是协议知识，不是候选。

### `KilimcininKorOglu/M365Bridge` v1.5.0（2026-09-04）

今天再查一次：**仍然没有 LICENSE**（`.license` 为空），所以边界不变，只取思路。47 个提交里 09-10 那一批全是 `refactor(servers): …` 的搬家，行为变化集中在 v1.5.0 的发布说明：

- 唯一的新测量：`feature.EnableMergingPureDeltas` 让同一条长答案的 `writeAtCursor` 从约 840 个降到约 130 个、字节相同；并称 `variants` 里其余每个 flag 对活体后端都是惰性的。**我们已经在发这个 flag**（`_VARIANTS` 里有），本条只是印证。
- 它 v1.5.0 的 personalization 读写 + 「POST 回 200 但不动 flag，所以只有读回来才算证据」——我们的 `personalization.py` 开头的 docstring 记的是同一件事，且我们还多记了一条「部分 POST 有字段耦合」。已有。
- 图片改写成本地引用、生成中提示、`snapshotDelta` 拒绝计数：前者我们有签名的 `/v1/m365-media`，后两者是遥测/提示细节，未排期。

### `protella/chatgpt-bots`（MIT）：G5 的不变量，可以直接抄

读了 v3.1.11（`85451fb2`）和 v3.2.2（`48fce8c`）的 `openai_client/api/tool_loop.py`。这是本轮对我们待办 5（工具调用卫生）最有价值的一份，全部是可复用的不变量：

1. **两个独立的上限，取小者**：每轮 fan-out 上限与本轮剩余的整轮预算，互不能放宽。动机是实测事故：一个响应里 20 个并行调用在 20 秒内烧掉约 1000 次 API 调用，第一轮就打满整轮预算，导致被迫的收尾轮无话可说。
2. **上限必须在 dispatch 之前生效**：一轮的调用是并行发出的，事后计费只能拦住下一轮。
3. **超额调用要「拒绝」而不是「丢弃」**：留下没有配对 `function_call_output` 的 `function_call`，下一次请求直接 400。所以超额的那些要喂一个合成的失败结果回去。这正是我们待办里「孤立 tool_result」的镜像面，直接适用于 Responses 续接路径。
4. **两种拒绝话术必须分开**：打满整轮预算是「预算已用尽，就用手上的信息作答」；只是撞到单轮 fan-out 上限是「装得下的已经跑了，读结果，下一轮再调」。用错话术会让模型在还有预算时就放弃。
5. **沉默/终止路径也要占用两个预算各一格**，否则 `no_response_needed` 带 19 个兄弟调用就能从安静的那条路绕过单轮上限。
6. **empty-final 兜底**：被上限逼出来的收尾轮返回 0 字符时，追加一条 developer 消息要求它现在就用已有信息作答，每轮最多一次，再不行才用固定兜底文案；而且兜底要**整体替换** segment 列表，只换文本会被下游重新拼成空串。
7. **v3.2.2 的自我更正值得照抄**：`tool_choice="required"` 且轮数上限为 1 时要**关掉**这个兜底 —— 「只有一轮、调用本身就是答案」是合法形状，它的收尾轮本来就该是空的，兜底在那里只会每次多花两次模型调用并打印两条误导性告警。
8. 兜底的 input item 每次要新建 dict：input 列表会被追加并重放，共享的模块级 dict 会同时挂到两轮上。

它的 `GPT-6 Astra default` 是 **OpenAI API 的模型**（这个仓走 `openai_client/api/responses.py`），**不是 M365 substrate tone**，不要当 tone 证据用；我只按仓库性质和该路径判定，没有再去读那个 commit 的 diff。

### 我们自己的两个缺口

**缺口一：`stop` 声明了但没人读，`stop_sequences` 根本没声明。** `models.py:72` 在 chat 请求模型上声明了 `stop: str | list[str] | None`，但全 `src/` 没有任何一处读它（`.stop` 的命中全是 `finish_reason:"stop"` / `stop_reason` / 前端一个同名局部变量），`stop_sequences` 在 `src/` 和 `tests/` 里都是 0 命中。也就是说客户端要求「遇到某个序列就停」时，我们静默忽略并继续输出到自然结束。是 OpenAI/Anthropic 兼容面上一个真实的小缺陷，且和上游能力无关，完全在我们这一侧。

**缺口一已修（2026-09-11，容器内实测通过）。** 新增 `stop_sequences.py`：`normalize_stop`（两种拼法归一，丢掉空串——空串会在 index 0 命中并把每个回答截成空）、`apply_stop`（**按位置**取最早命中，同位置取更长的那条，这样上报的 `stop_sequence` 是更具体的那个）、`StopSequenceTrimmer`（流式 hold-back）。四条投递路径全部接上，`models.py` 补了 `stop_sequences`。

边界与理由，都有测试盯着：

1. **截断是投递边界，不是提前退出。** 命中后仍把上游这一轮抽干，因为 usage 合计、会话里存的 assistant 消息、完成帧的记账都跟最后一个 delta 一起（或之后）到。为省几百毫秒 `break` 掉迭代器，换来的是错的 usage 行和错的会话记录，而客户端根本观察不到那点延迟。
2. **流式必须 hold-back。** 上游在哪切 delta 是它的自由，所以 `CHARLIE` 会以 `CHAR` + `LIE` 到达；逐 delta 检查永远看不见它，而一旦把尾部是某条 stop 前缀的 delta 转发出去就已经泄漏了。trimmer 因此扣住「还可能长成匹配」的最长后缀，只在它不可能再长成时才放出去——SSE 是 append-only，交出去的文本不能收回。
3. **扣住但最终没匹配的尾巴必须交付。** 一个正好以 `CHAR` 结尾的回答不能因为像 `CHARLIE` 的开头就被吞掉。
4. **只切模型的正文。** 不切 `tool_calls`（截断的参数对象不是合法 JSON），也不切我们自己那条「为什么这轮没有 tool_call」的说明——那是我们的话不是模型的话，截了等于把解释藏起来。
5. **`tool_use` 轮次仍报 `tool_use`**，不因为命中就改成 `stop_sequence`：调用方还得去跑那个工具。

一处真实教训，写下来免得重犯：**生产永远传 `text_transform=media_rewriter`**（两个流式调用点都是），而两个流式生成器里 `if text_transform is not None: continue` 在 trimmer 之前，所以**生产走的根本不是 hold-back 那条分支**，而是整轮缓冲完在尾部 `apply_stop`。我最初 10 条测试全部不传 `text_transform`，也就是说四条流式测试测的都是生产不走的那条路——活体测试之所以过，靠的是缓冲分支。已补两条 `text_transform` 版本的测试（`…cuts_the_transformed_text…`），并用只改缓冲分支的变异体确认恰好是这两条红、其余 10 条全绿。hold-back 那条分支现在是纵深防御（`media_rewriter` 若哪天不再无条件传入就会承重），不是当前生产路径。

另一处：变异测试之后我用 `git diff` 判断是否恢复——**新文件未入库，`git diff` 是空的**，`apply_stop` 的 `<` 被留成了 `>=` 而我以为已还原，直到全量跑出 6 red 才发现。判据要用文件内容本身，不是 `git diff`。

容器内实测（`ciallo-ms365-proxy-multi`，`/app/src` 是 editable 安装，改完重启生效；改前先把 4 个原文件备份到容器内 `/tmp/stopseq-backup-20260911/`，5 个文件传输后逐一比对 SHA-256 与本地一致）。提问固定要求逐行输出 `ALPHA/BRAVO/CHARLIE/DELTA`，`stop=CHARLIE`：

| 路径 | 修前 | 修后 |
|---|---|---|
| chat 非流式 | 全文，`DELTA` 泄漏 | `ALPHA\nBRAVO\n`，`finish_reason=stop` |
| chat 流式 | 全文，`DELTA` 泄漏 | 同上 |
| Anthropic 非流式 | 全文，`stop_reason=end_turn` | `ALPHA\nBRAVO\n`，`stop_reason=stop_sequence`、`stop_sequence=CHARLIE` |
| Anthropic 流式 | 全文，`DELTA` 泄漏 | 同上 |
| 对照（不带 stop） | — | 全文照出，未被误截 |

另外三格也在容器内量过：截断后 usage 仍完整（`prompt 22 / completion 7 / total 29`）；带 tools 的一轮 `finish_reason=tool_calls`、参数 `{"city":"Paris"}` 完好；Anthropic 带 tools 仍 `stop_reason=tool_use`、`stop_sequence=None`。全量 `2013 passed, 3 skipped`。

#### 三种规划模式 × 三协议的回归矩阵（2026-09-11）

上面那张表只覆盖了「stop 生不生效」，没有回答「改完之后直连 / 路由 / studio 会不会有一条不能用」。补测：每种 `tool_planning_mode` 各跑一遍 OpenAI chat、Anthropic Messages、OpenAI Responses 的工具轮（流式与非流式）、stop 轮，以及「工具与 stop 同时出现」这一格，共 27 格真实上游轮（`.probe/final_matrix.py`，仅本地保存）。

探针模型固定为 `claude-sonnet-4-6`，因为绑定 Key 的 tone 是 `Claude_Fable`，而它在 native 下回的是 `X-M365-Tool-Calling: unsupported` —— 用它测 native 只会测出这个 tone 本来就不支持本地工具调用（代理自己那条「不支持本地工具调用」的说明就是这么写的），不是回归。

| 模式 | chat 工具（非流式/流式） | Anthropic 工具（非流式/流式） | Responses 工具 | stop（chat/Anthropic） | 工具+stop 同轮 |
|---|---|---|---|---|---|
| studio | PASS / PASS | PASS / PASS | PASS | PASS / PASS | PASS |
| router | PASS / PASS | PASS / PASS | PASS | PASS / PASS | PASS |
| native（直连） | PASS / PASS | **1 次 FAIL** / PASS | PASS | PASS / PASS | PASS |

`TOTAL 27 PASS 26`。唯一那格失败**不是这次改动造成的**，三条独立证据：

1. **不带 stop 参数也复现。** 同一请求连发 5 次，`tool_use` 命中 4/5，请求体只有 `model` / `max_tokens` / `messages` / `tools`，没有 `stop_sequences`（`.probe/anthropic_native_repeat.py`）。没有 stop 参数时 `apply_stop` 是严格 no-op，所以这个失败不可能归因于它。
2. **结构上到不了。** Anthropic 非流式处理器里 `stop_reason=tool_use` 那条分支在**第 632 行 return**，而 `apply_stop` 在**第 638 行**；`_anthropic_stream_with_tools` 里 `apply_stop` 只作用于 `text_out`，从不碰 `blocks[]`。
3. **失败会换位置。** 一轮是 native+chat 非流式失败、Anthropic 通过，下一轮正好相反。代码缺陷不会换位置。

失败形态本身也一致指向模型侧：那一轮 header 是 `hdr=verified`（即该 tone 实测支持工具调用），但模型直接用正文答了天气，正文里还带着 `"Sure! Let me fetch the current weather in Paris for you.'s the current weather..."` 这种自我打断的痕迹，没有 fenced `tool_call` 块可解析。也就是说 native 模式下模型有时就是不按契约走 —— 这正是 router / studio 两种模式存在的理由，两者在本矩阵里 18/18 全绿。

为了排除「是不是我改坏了 native」，还做了一次 A/B：把 4 个改动文件换成 `git show HEAD:` 的原版（0 处 stop 引用）重启后跑同一个 native 复发探针，得到 4/4；换回改动版是 3/4。**样本太小不足以证明差异**，真正的判据是上面那三条，尤其是第 1 条（不带 stop 也复现）与第 2 条（结构不可达）。

A/B 过程里踩到一个必须记下的坑：还原时把容器内路径当成 `docker cp` 的源，而 `docker cp` 的源是**宿主机**路径，于是还原静默失败、容器带着原版代码继续跑了一段。是靠「数 stop 引用条数」发现的，不是靠命令返回码。之后改成从本地重推 5 个文件、逐个比对 SHA-256、再重启，容器 `healthy`、`restarts=0`、5 个文件与本地逐字节一致。教训与前面那条 `git diff` 的坑同源：**判据要落在文件内容上，不要落在「命令看起来成功了」上**。

还没做的那半：`/v1/responses` 没接。OpenAI 的 Responses API 本身没有 stop 参数，接了等于自造契约，所以是有意留空，不是漏。

**缺口二：`deepResearchModels` 只发了类型注解，没发值。** `substrate_client.py:369` 发的是 `"deepResearchModels@odata.type": "Collection(String)"` —— 一个 OData 类型注解，而它注解的那个属性我们从来不发（全 `src/` 只有这一处 `deepResearchModels`）。按 companion-mcp 的抓包，Researcher 的模型正是走 `gpts[0].clientOverrides.deepResearchModels[0]`。所以现状是「声明了会传一个字符串集合，然后不传」。

**缺口二已定案：删掉那条注解（2026-09-11，容器内四变体实测）。**

判据用服务端自己的裁决，不用正文 —— 完成帧的 `item.result.value`（`Success` / `InvalidRequest` 之类）加 `item.turnState`（`Completed`/`Failed`），这也正是 `substrate_client` 本来就在读的字段。正文answers不了这个问题：一个「格式不对但被容忍」的帧照样会返回一个完全正常的回答。四个变体各跑一轮真实上游，全部用一次性会话，不碰任何持久 session（`.probe/deepresearch_ab.py`，仅本地保存）：

| 变体 | `clientOverrides` 形状 | 服务端裁决 |
|---|---|---|
| A（现网原样） | `capabilities` + 注解，无值 | `Success` / `Completed` |
| B（删掉注解） | 只有 `capabilities` | `Success` / `Completed` |
| C（注解 + 值） | `capabilities` + 注解 + `["Default"]` | `Success` / `Completed` |
| D（只有值） | `capabilities` + `["Default"]` | `Success` / `Completed` |

四个全过，所以**这条注解是惰性的**：删掉它在下游观察不到任何差别。

差点被当成信号的一格：第一轮里 A 收到 8 帧、B 只有 7 帧，看着像「注解让服务端多发一帧」。复跑推翻了它 —— 第二轮那个 7 落在了 **D** 头上，然后 A/B 交替各跑 3 轮得到 `A=[8,8,8]`、`B=[8,8,8]`，两组完全重叠（`.probe/deepresearch_repeat.py`）。**帧数是流噪声，不是效应**；只跑一轮就下结论会得出反的答案。

**为什么是删而不是补值。** 补值等于凭空造一个我们没有的功能：`deepResearchModels` 在全 `src/` 只有那一处，`DeepResearch` 同样只有那一处，没有任何 Researcher / Deep Research 的模式、模型或路由（`runtime_settings.py` 里的 `copilot-research` 是**个人版**的 mode，与 Studio 的 `gpts[0]` 无关）。而留着一条为不存在属性准备的注解，等于在帧里宣布「有个字符串集合要来」然后永远不发。两害相权，删掉是唯一诚实的收尾。companion-mcp 抓到的 `"Default" -> "Claude"` 只证明**它的**客户端在用这个字段，不证明我们该发。

删除后在容器内复验 Studio 全链路（`.probe/studio_after_removal.py`）：chat 工具轮 `hdr=studio` / `finish=tool_calls`、Anthropic `stop_reason=tool_use`、Responses `function_call`、stop 仍生效，**4/4 PASS**。`tests/test_studio_planner.py` 里钉住这条注解的断言同步删掉（留着它会把「上游容忍」误记成「上游要求」）。全量 `2013 passed, 3 skipped`。

### tone：本轮无新证据

`Gpt_6_Reasoning` 全站 12 个文件 / 3 个仓，除我们自己外两个是 `Hexpy-Games/butler` 和 `einhaus/meteoric-helpers`，读了都是 OpenAI 的推理档位表（`["low","medium","high","xhigh","max"]`），不是 substrate tone。`Gpt_6_Chat` 只在 `jeremychone/rust-genai` 命中 1 处（按仓库性质是 OpenAI 模型目录，未逐行读）。`Gpt_6_Astra`、`Claude_Fable` 在我们仓之外 0 命中。09-07 那份 tone 调查的结论不变。

### 顺带否决

- `MIGHTYBLANK001/M365-Copilot2API-CE-Build`（无许可证，2 个文件）：没有源码，只是给上游 `s12ryt/M365-Copilot2API-CE` 自动构建 ARM64 镜像的 Actions 仓。上游属于 09-01 已判不可采纳的那一族，本身也没有可抄的东西。
- `microsoft/Agents-M365Copilot`：7 个提交全是各语言 v1/beta 的 request builder 与 model 生成更新加一个 release chore，没有新的能力信号，定位不变（下一候选，不是已可用）。
- `site-speed/M365-Copilot-Chat-Export-{userscript,extension}`（MIT）：从网页 UI 导出对话，走 DOM/JSON 不走协议。
- `cristiancastineiras/M365CopilotVSCode`（无许可证）：token 捕获 userscript + VS Code provider，形态与我们的 userscript 重合且不可采纳。
- `microsoft/m365-copilot-eval`（NOASSERTION）：评测 CLI。
- `nickhou1983/copilot2api-multiusers`（MIT）：上游是 GitHub Copilot（whtsky 的分叉），按开头的排除项不算候选。

## 2026-09-14 复扫：Cowork 从「协议知识」变成「可测候选」，外加我们自己两处死代码/丢字段

延续 08-30 / 09-01 / 09-11 的问法（找**许可证允许拿进来**的代码补已知缺口）。窗口 2026-09-01..09-14，819 个去重仓里 432 个不在已知清单，193 个 m365 相关。绝大多数是 **Claude Cowork**（Anthropic 的桌面 agent，与微软的 Copilot Cowork 同名不同物）和 M365 管理/报表仓，一句话否决。

### 方法上的两个坑

1. **单词歧义把噪声放大了一个数量级。** 本轮 `cowork` 命中的绝大多数是 Anthropic 的 Claude Cowork 插件生态，不是微软的 Copilot Cowork。同名不同物，先按描述里有没有 `Microsoft`/`M365`/`powerapps` 过滤，再看代码。
2. **协议字符串搜索仍然是唯一高信号的一条腿。** 真正有价值的四个仓，没有一个能靠仓名或描述找到：`microsoft/PyRIT` 是红队框架、`kdeps/kdeps` 是 YAML agent 构建器、`artlovan/copilot_cowork_mcp` 是 MCP server。它们是靠 `substrate.office.com/m365Copilot/Chathub`、`mcsaetherruntime`、`XRoutingParameterSessionKey`、`deepResearchModels` 这些字面量搜出来的。

### 判决表

| 仓 | 许可证 | 派生核查 | 结论 |
|---|---|---|---|
| [`microsoft/PyRIT`](https://github.com/microsoft/PyRIT) | MIT，4465★，微软自家 | 微软原创 | **可采纳，但没有可搬的东西**：见下 |
| [`kdeps/kdeps`](https://github.com/kdeps/kdeps) | Apache-2.0，37★，Go，09-14 仍活跃 | `HEXUXIU`/`Copilot2API`/`addToChainOfThought`/`cramt`/`M365Bridge` **各 0 命中**，NOTICE 署名 Kdeps KvK 94834768 → 独立实现 | **可采纳**，本轮最有价值 |
| [`artlovan/copilot_cowork_mcp`](https://github.com/artlovan/copilot_cowork_mcp) | MIT，3★，Python，4 个源文件 | `HEXUXIU`/`Copilot2API`/`bakapiano`/`cramt` **各 0 命中** → 独立实现 | **可采纳**，Cowork 的答案 |
| [`chrischall/opencode-copilot-plugin`](https://github.com/chrischall/opencode-copilot-plugin) | MIT，2★，TS，09-11 活跃 | `cramt` 4 处命中**全在文档**（README/AGENTS/CONTRIBUTING/issue 模板的致谢与链接），`src/` 里 0 命中 → 独立实现 | 可采纳，只印证 |
| [`uefi233/m365-copilot-gateway`](https://github.com/uefi233/m365-copilot-gateway) | Apache-2.0 | `docs/ATTRIBUTIONS.md` 把 HEXUXIU 列为「payload 参考」，且 `src/mcg/substrate/protocol.py:8` 的 docstring 直接写「HEXUXIU/M365-Copilot2API (payload.py)」 | **按不可采纳对待**（同 `jerbehe` / `xiaocongyu66` 先例：源文件里向 AGPL 仓致谢 payload 来源，署名链就不干净）。且**本来就没有可拿的**：见下 |

`uefi233` 那条值得单独说清楚，因为它的 `DEFAULT_VARIANTS` 和 `DEFAULT_OPTIONS_SETS` 看着像我们的。逐字节比过：不是相同，是**我们的严格超集** —— variants 它 890 字符 / 我们 1684，它有的我们全都有、我们多 18 项（`feature.EnableMergingPureDeltas`、`feature.EnableRemoveStreamingMode` 等）；optionsSets 它 14 项 / 我们 33 项，它有的我们全有。所以从它这里**一个新协议字段都拿不到**，判决不影响任何东西。

### `kdeps/kdeps`：我们待办 7 的可用设计（Apache-2.0，可直接采纳）

它把推理转录接到了 `reasoning_content` 上，两条路都接了。可复用的不变量：

1. **旁白与答案分两条 channel**（`stream.go:46/54` `Deltas()` / `ThinkingDeltas()`）。理由写在注释里，正是我们的形状：工具轮的答案必须缓冲到解析完（可能含未闭合的 fenced `tool_call`），**而推理文本任何时候都可以直接流** —— 它不含工具语法。所以推理能在工具轮里实时流，答案不能。
2. **旁白是快照不是增量**（`stream.go:179-183`）：同一个 `MessageID` 会被服务端反复重发（元数据在长大），所以按 MessageID **每条只发一次**，不能套用答案那套折叠逻辑。这条与我们 09-01 修 `fallback_text` 时踩的「快照当增量会变成 `166166166`」是同一个坑的另一面。
3. 判据是 `contentOrigin == "ChainOfThoughtSummary"`（`stream.go:175`）。比我们窄 —— 我们 09-01 实测出更准的判据是 `messageType` 拒绝表（能盖住 `EarlyProgress` 和无标记的 `Searching...`），所以**要抄的是它的渲染结构，不是它的判据**。
4. 非流式：`addReasoning` 在 `message` 上加 `reasoning_content`（`server.go:803-812`），`tool_calls` 那支也加（`server.go:831`）。流式：`onThinking` 回调发 `chunk(base, {"reasoning_content": t})`（`server.go:903-908`）。

顺带三条与我们已有结论互相印证的（不是新知识，但是独立第二来源）：

- **Claude tone 要保持 agent-less**：它的文档明说 tool calling 走自动创建的 Studio agent，**除非 tone 是 `Claude_*`，那时它故意不挂 agent，因为挂上会强制变成 GPT-5**。这正是我们 08-25 记的「本仓从来不创建 agent」那条路，且给出了「为什么不能挂」的机制。
- **服务端代码解释器会抢工具**：`server.go:597-605` 记着 gpt-5.x reasoning tone 会无视系统提示去用自己的 `/mnt/data` 沙箱、并且编造 bash 调用，重试也是同样失败，而 Claude tone 没这个习惯。与我们 08-25 那张取舍表同向。
- **它也没有精确 token 计数**：`server.go:983` 的 usage 是 `prompt_tokens: 0, completion_tokens: 0, total_tokens: 0`。

### 我们自己的缺口一：`tool_hygiene.py` 的单轮/整轮上限是死代码

待办 5（工具调用卫生）只完成了一半，而这一半和另一半在同一个文件里，所以很容易误以为都上线了。实测数（`grep` 全 `src/`，排除 `tool_hygiene.py` 自身与 `__pycache__`）：

| 符号 | `src/` 里除本模块外的调用点 |
|---|---|
| `dedupe_tool_call_ids` | chat / messages 各 2 处，**已接** |
| `dedupe_tool_call_payloads` | chat / messages 各 2 处，**已接** |
| `orphan_tool_results` | chat / messages 各 1 处，**已接** |
| `refuse_over_cap` | **0** |
| `tool_round_allowance` | **0** |
| `over_cap_reasons` | **0** |
| `MAX_TOOL_CALLS_PER_ROUND` | **0** |
| `MAX_TOOL_CALLS_PER_TURN` | **0** |

也就是说 protella 那 8 条不变量里，「两个独立上限取小者」「上限必须在 dispatch 之前生效」「超额要拒绝而不是丢弃」全部**实现了、测试了（`tests/test_tool_hygiene.py` 有 10 条断言）、但没有任何一条投递路径调用**。测试全绿，因为它们直接调函数，不经过路由。这正是「测试不等于上线」的一格 —— 和 09-11 那条「生产永远传 `text_transform`，所以 hold-back 分支根本没走」同源。

`MAX_TOOL_CALLS_PER_TURN = 32` 还有个额外前提：整轮预算需要一个跨轮计数器（会话级），而 `refuse_over_cap` 的 `remaining_turn_budget` 现在没有任何来源。接线时这是真正要设计的那部分，不是改个 import 就完。

#### 实测：这两个上限在真实流量里一次都不会触发（2026-09-14）

接线还是删掉，取决于一个没人量过的事实：真实的一轮到底会不会产出超过 8 个 tool call？`tool_hygiene.py` 自己的注释写的是「声明的工具数见过低二十几个（Claude Code），但一轮真需要几个以上并行调用的情况**没见过**」——「没见过」正是可以查的。

`.probe/toolcall_fanout_census.py` 只读部署容器里的 `call_log.json`（不发上游、不碰账号、不写状态）：

| 指标 | 实测 |
|---|---|
| 日志条数 | 100（`call_log_limit` 上界，是近期样本不是全史） |
| 带 ≥1 个 tool_call 的响应 | 42 |
| 单轮 tool_call 数分布 | **1 个：42 次；0 个：58 次。没有任何一次 ≥2** |
| 单轮观测最大值 | **1**（round cap 是 8） |
| 单轮上限本会拒掉的响应数 | **0** |
| 已接线的 dedupe/schema 拒绝 | 5 次（`Write` / `Read` / `Client Context Bridge` 不在本轮声明的工具里） |

**结论：接线是纵深防御，不是行为变更。** 观测最大值 1 离 8 有一个数量级，所以接上 `refuse_over_cap` 不会改变任何**当前可观测**的行为——这使它成为低风险改动，而不是「会开始拒绝客户端今天正在成功发出的调用」的策略变更。反过来说，它的收益也同样是假设性的：现在没有任何证据表明有流量正撞上这个上限。

两条样本限制，不能省：**(1)** 日志有界（100 条），所以「最大 1」是**下界**，不是历史最大值的证明；**(2)** `MAX_TOOL_CALLS_PER_TURN = 32` 这条**完全没量到**——日志里没有 conversation id，`turn_count` 在带工具的响应上全是 0，所以那个 32 治理的「每会话工具调用总数」在现有数据里根本不可见。

对比值得记：**已接线的那半在同一份日志里触发了 5 次**（dedupe/schema 拒绝），而两个上限触发 0 次。也就是说这个文件里两半代码的实际承重完全不同——已接的那半在干活，没接的那半即便接上也暂时不干活。

#### 更正我自己上一条建议：`refuse_over_cap` 不是「加个 import」就能接的（2026-09-14）

上面写「选项 (a) 按防御性接线（实测零行为变化，安全）」。**这条建议不准确**，读完它自己的契约才发现问题在架构上，而不是在风险上。

`refuse_over_cap` 的 docstring 明确承诺：超额的调用「**Refused, not dropped**」，理由是「客户端收不到结果的 `tool_calls` 条目会让它的转录不成对，下一个请求就会因为这个 orphan 被拒」，所以超额部分要「**作为一条合成的失败结果回去，让客户端能配对**」。它返回的 `refusals` 就是为此设计的：每项带 `tool_call_id` / `name` / `message`。

问题是**本代理从来不发送工具结果**。实测：

| 事实 | 实测 |
|---|---|
| 响应侧发出 `role:"tool"` 或 `tool_result` 的地方 | **0 处** |
| 工具执行器 / dispatch / run_tool | **0 处** |
| 响应侧实际发出的形状 | 只有 `{"role":"assistant","content":…,"tool_calls":[…]}`（`routes_api_chat.py:675,943`） |

也就是说本代理只**解析并投递** `tool_calls`，由**客户端**执行、再把结果放进下一个请求发回来（这也正是 `orphan_tool_results` 走的是**入站**转录的原因）。工具结果的方向是 客户端 → 代理，不是 代理 → 客户端。所以那个 `refusals` 字典**在本架构里没有投递通道**——它是为「代理自己跑工具循环、自己维护转录」的架构写的，而我们不是。

连带一条：docstring 担心的 orphan 在这里**不会发生**。我们若把超额调用从投递列表里去掉，客户端根本没见过它们，也就无从产生未配对的结果；orphan 只会由「投递了却没有结果」造成，而结果不由我们产生。

**所以真正能接的只有另一半：** `over_cap_reasons()` 产出的人类可读串，它有现成通道——和 dedupe/schema 拒绝走同一条：`rejected` 列表 → `call_record["tool_calls_rejected"]` → `rejected_calls_note` / `required_tool_call_error`。这也解释了为什么已接线的那半能接：它返回的就是 `(kept, reasons)` 字符串列表，形状本来就吻合。

结论修正为：接线的正确形状是「按 `per_round_cap` 截断 + 把 `over_cap_reasons` 并入现有 `rejected` 通道」，而 `refuse_over_cap` 的字典输出要么弃用、要么等到真有工具循环时再用。加上普查结论（单轮最大 1，会触发 0 次），**这条的优先级应当低于任何有实测承重的改动**，且不该在没有决定「弃用还是保留那个字典」之前动手。

### 我们自己的缺口二：服务端自己报的会话配额，我们收到了然后丢掉

`substrate_client.py` 对 throttling 只做一件事：完成帧的 `turn_failure` 等于 `throttled` 时抛 `SubstrateThrottled`（`substrate_client.py:713-714`）。而帧里带的是**计数器**，不只是布尔：

- `arguments[].throttling.numUserMessagesInConversation` / `.maxNumUserMessagesInConversation`
- `item.throttling.numUserMessagesInConversation` / `.maxNumUserMessagesInConversation`
- 另有 `numLongDocSummaryUserMessagesInConversation`

全 `src/` 对这三个键 **0 命中**。三个互不相干的实现都在读它：`kdeps`（`stream.go:363-366` 读 `item.throttling`，`443-448` 读 `arguments[].throttling`，两处都读是因为两种帧都会带）、`chrischall`（`src/session.ts:377-380` 与 `398-401`，同样两处）、以及按 09-11 记录的 HEXUXIU。`kdeps` 进一步把它当**权威配额**上报成 usage 扩展字段（`server.go:983-1000`：`x_m365_conversation_messages` / `_max` / `_pct` / `_remaining`）。

**这个键在我们自己的账号上确实到达，且已在部署容器里实测过值（2026-09-14）。** 此前只有路径没有值（旧捕获只存了 JSON path），所以「Max 是多少、Current 怎么涨」是空的；现在补上了。探针 `.probe/throttling_counters.py` 只挂 `_capture_suspicious_response_event` 记录，不改任何行为，在 `ciallo-ms365-proxy-multi` 内跑同一个 `PersistentSession` 的三轮（`tone=Claude_Sonnet`，账号 `acct_2eed3918214f`）：

| 轮 | 帧数 | 带 throttling 的对象 | `numUserMessagesInConversation` | `maxNumUserMessagesInConversation` | `numLongDocSummary…` |
|---|---:|---:|---:|---:|---:|
| 1 | 9 | 2（`arguments[]` 与 `item` 各一） | 1 | 600 | 0 |
| 2 | 8 | 2 | 2 | 600 | 0 |
| 3 | 8 | 2 | 3 | 600 | 0 |

三条实测结论：**(1)** 计数器**每轮 +1**，语义是「这个会话用掉的用户消息条数」，不是 token；**(2)** `max=600` 三轮恒定，所以它是会话上限而不是剩余额度；**(3)** `arguments[].throttling` 与 `item.throttling` **两处都到**且同值 —— 这正是 `kdeps` 和 `chrischall` 都读两处的原因，只读一处会在另一种帧上拿不到。接线前提因此已满足（这条原本写的是「接线前要先量一轮」，现在量完了）。

注意 600 这个数不要当成通用常量：它来自这一个账号的一个 tone，个人版和其他 licence 很可能不同，所以上报时应原样透传服务端给的值，不要硬编码。

为什么这条比 tiktoken 更值得做：待办 4 想把 usage 从 `estimated` 升级，而 token 计数在上游**根本不存在**（本轮第三次印证：`kdeps` 报 0，Cowork 自陈无计数，我们自己估算）。而 `throttling` 是**服务端自己算的、权威的**配额消耗。它计的是消息条数不是 token，所以不能替代 token 估算，但它是我们唯一能拿到的非估算用量信号，而且现在正被丢掉。

#### 缺口二已接线（2026-09-14，隔离覆盖层活体验证）

按上面量到的形状接线，五个文件，全部是**新增读取**，没有改任何协议输出：

| 文件 | 改动 |
|---|---|
| `substrate_client.py` | 新增 `_conversation_quota_from()`（模块级解析，两个帧位共用）、`conversation_quota` 只读属性、`_note_quota()`；两个帧位（`t==1` 的 `arguments[0]`、`t==2` 的 `item`）各调一次 |
| `conversation_quota.py` | 新文件：`ConversationQuotaStore`，按账号存最新一条读数，内存、带锁、上限 200 个账号 |
| `dependencies.py` | 新增 `_attach_quota_sink()`，与既有 `_attach_response_debug_sink()` 并列挂在同一处 |
| `state_init.py` | `app.state.conversation_quota_store = ConversationQuotaStore()` |
| `routes_admin_debug.py` | `_cache_stats()` 增加 `conversation_quota` 字段 |

**四条设计约束，都有测试盯着：**

1. **没有帧报告过就是 `None`，不是 0。** 「服务端没说」和「服务端说 0」是两件事，折叠掉会让每个不上报的构建显示成 `0/0`。
2. **`max` 原样透传，不与常量比较。** 600 只来自一个账号一个 tone。
3. **不进 `usage_store`。** 两重类别错误：它数的是**消息条数**不是 token，不能加进 token 合计；它是**按会话**的瞬时读数，不能像 lifetime 累计那样累加。所以是独立的小 gauge，不落盘 —— 重启后从磁盘读回来的配额描述的是可能已不存在的会话，而**过期的配额比没有配额更糟，因为它看起来权威**。
4. **sink 异常不能杀掉一轮。** 遥测失败只记 warning。

**一个差点上线的 bug，靠写测试才发现：** `_note_quota` 最初直接读 `self._quota_sink`，而**所有 substrate 测试夹具和 `scan_tones` 都用 `__new__` 建 client，从不跑 `__init__`** —— 任何带 throttling 的帧都会变成 mid-turn `AttributeError`。全量套件当时是绿的，因为**没有一个夹具帧带 throttling**。改成 `getattr(self, ..., None)`（与帧循环读 `_response_debug_sign` 的写法一致），并加了一条专门用 `__new__` client 喂带 throttling 帧的回归测试。这与 09-11「生产永远传 `text_transform`，所以 hold-back 分支根本没走」是同一类：**夹具没覆盖到的路径，绿色什么都不证明。**

`tests/test_conversation_quota.py` 21 条，帧形状照抄上表实测值。全量 **2071 passed, 3 skipped**，pyflakes 门禁对这五个文件干净。

**活体验证（不动生产代码）。** 部署容器跑的是 `4cb1dae`，且 `/app/src` 是 editable 安装，直接覆盖就等于改线上服务。所以把整棵树复制到容器内 `/tmp/newsrc`、把改动文件盖上去、只从那里 import（`.probe/quota_live_newcode.py`）；探针开头断言 `sc.__file__` 必须以 `/tmp/newsrc` 开头，否则「导入了旧模块」会伪装成「代码没生效」。5 个文件传输后逐一比对 SHA-256（宿主 → 容器），并确认 `/app/src` 对新符号 **0 命中**：

```
module_path_ok=/tmp/newsrc/m365_copilot_openai_proxy/substrate_client.py
before_any_turn conversation_quota=None          <- 约束 1
turn1 answered=True  {'messages': 1, 'max_messages': 600, 'long_doc_messages': 0}
turn2 answered=True  {'messages': 2, 'max_messages': 600, 'long_doc_messages': 0}
sink_call_count=4                                 <- 每轮两个帧位各一次
store.get={'messages': 2, 'max_messages': 600, 'remaining': 598, 'percent': 0.33, ...}
admin_stats_has_quota=True
  admin account=acct_2ee… messages=2 max=600 remaining=598 percent=0.33 long_doc=0
```

即整条线通了：真实帧 → 解析 → client 属性 → sink → store → `/admin/stats`。验证后 `/tmp/newsrc` 已删除，容器 `healthy`、`restarts=0`、生产 `/app/src` 未被触碰。

**这条与缺口一的关系（别忘了）：** 缺口一之所以是死代码，就是因为「实现了 + 测试了 + 没有任何投递路径调用」。所以这次的读取端（`/admin/stats`）是和解析端**同一次**接线的，而不是留到以后 —— 只加 `_note_quota` 不加读取端，等于再造一个缺口一。

#### 三协议 × 三规划模式的 HTTP 验收矩阵（2026-09-14，18/18 PASS）

上面那次验证走的是**直接调 client**，覆盖不到 `get_copilot_client` 那条依赖注入链，而这次改动恰好动了那个漏斗（每条 `/v1` 路由都过它）。所以按 `AGENTS.md` 的矩阵补一次**真实 HTTP** 验证：`.probe/quota_matrix_http.py` 在容器内用覆盖层 `create_app()` 起独立实例（各自的 `TOKEN_DIR`，绑一个 key 到一个账号），用 `TestClient` 打真实路由、真实上游。

| 规划模式 | chat 非流式 | chat 流式 | chat 工具轮 | Anthropic 文本 | Anthropic 工具 | Responses |
|---|---|---|---|---|---|---|
| native 配置 | PASS | PASS | PASS `tool_calls` | PASS `end_turn` | PASS `tool_use` | PASS `completed` |
| router 配置 | PASS | PASS | PASS `tool_calls` | PASS `end_turn` | PASS `tool_use` | PASS `completed` |
| studio 配置 | PASS | PASS | PASS `tool_calls` | PASS `end_turn` | PASS `tool_use` | PASS `completed` |

每格的判据是「这一轮答出来了 **且** `/admin/stats` 的 `cache.conversation_quota` 里该账号有值」，读到的都是 `1/600`、`remaining=599`、`percent=0.17`；每个实例开跑前先确认是 `None`，所以不是预置值。

**先说一个把我自己骗过去的坑。** 第一次跑，18 格**全 FAIL**、`quota=None`，看着像「接线在 HTTP 路径上根本不工作」。其实是探针的错：`/admin/*` 认的是 `POST /admin/login` 设下的**会话 cookie**，不是 `Authorization: Bearer`，所以每次读都是 401，而我的 `quota_from_admin` 把非 200 折叠成了空 dict。也就是说那 18 个 `None` **从来不是对接线的测量**，是对我自己请求头的测量。改成先登录拿 cookie，18 格全过。教训与前面 Cowork 那次 401 完全同源：**先证明判据本身有效，再用它下结论** —— 一个恒假的判据和一个真实的缺陷长得一模一样。

**两条必须写下来的局限，别把这张表读大了：**

1. **三行其实跑的是同一条路径。** 每个实例的 `call_log` 自报 `planning modes actually used: ['router']` —— 三种 `tool_planning_mode` 配置下实际执行的都是 router。原因已知且是既有设计：绑定 key 的 tone 是 `Claude_Fable`，它实测 `unsupported` 本地工具调用，所以 `auto`/`native` 都会被路由到 router turn（09-11 那份矩阵也踩过同一件事，当时是换成 `claude-sonnet-4-6` 才测到 native）。所以这张表证明的是**三个协议 × 工具/非工具/流式**都通，**不是**三种规划模式各自都通。要补 native/studio，得换一个 tone 重跑。
2. **`messages` 始终是 1，没看到跨轮递增。** 每个 `/v1` 请求不带会话头就是一轮新会话，所以每次都是该会话的第 1 条。递增是上一节直接调 client 时用同一个 `PersistentSession` 证过的（1→2），这里没有再证一次。

跑完 `/tmp/newsrc`、`/tmp/quotaverify`、探针全部删除；生产 `/app/src` 全程未被触碰（新符号在 `/app/src` 命中数 0），容器 `healthy`、`restarts=0`。

#### 自查：我自己也犯了缺口一那个毛病，外加一个真 bug（2026-09-14）

接完线之后按缺口一的同一把尺子量自己的代码——**「新加的符号里有几个在 `src/` 里没有调用点」**。结果不好看：

| 我新加的符号 | `src/` 里的调用点（不含定义处） | 处置 |
|---|---|---|
| `_conversation_quota_from` | 1（`_note_quota`） | 保留 |
| `_note_quota` | 2（两个帧位） | 保留 |
| `_attach_quota_sink` | 1（`get_copilot_client`） | 保留 |
| `ConversationQuotaStore.record` | 1（sink 闭包） | 保留 |
| `ConversationQuotaStore.stats` | 1（`/admin/stats`） | 保留 |
| `ConversationQuotaStore.get` | **0** | **已删** |
| `ConversationQuotaStore.clear` | **0** | **已删** |
| `SubstrateCopilotClient.conversation_quota`（property） | **0** | **已删** |

也就是说我一边写着「只加 `_note_quota` 不加读取端就等于再造一个缺口一」，一边顺手加了三个没有任何投递路径调用的符号。`get`/`clear` 是「以后可能有用」的臆测 API（`clear` 连一个能触发它的 admin 路由都没有，而 `usage_store` 那类清理路由是显式建的）；`conversation_quota` property 更微妙——sink 才是真正的投递路径，property 只是我下意识觉得「客户端应该能被问到这个值」，但没有任何代码问它。既然 property 删了，它背后那份 `self._conversation_quota` 副本也一起删：那是一份没人读的状态。

**顺带查出一个真 bug（这才是自查的实际收获）。** 这个 gauge 以 account id 为键，而 `DELETE /admin/accounts/{acc_id}` 只做了 `refresh_scheduler.remove_account` + `key_store.detach_account`，**没有清 quota**。账号删掉之后，它那一行会永远留在 `/admin/stats` 里：不会被覆盖（不会再有该账号的 turn），也不会被顶掉（LRU 只在 200 个账号上限时才淘汰）。这正好违反我自己写在模块头上的那句话——「过期的 quota 比没有 quota 更糟，因为它看起来是权威的」。修法是加 `forget(account_id)`，在删账号的路由里紧挨着 `detach_account` 调用，并补一条测试（`test_a_deleted_account_stops_being_reported`）。

注意这条**不是**用「以后可能要清理」论证 `forget` 的存在：它和 `get`/`clear` 的区别就是有没有真实调用点——`forget` 有一个明确的、已接线的调用点，`get`/`clear` 一个都没有。

**同一个毛病的第三次，这次是「测了函数没测路由」。** 上面刚把 `forget` 接进删账号路由，测试却只有 `store.forget(...)` 这种**直接调函数**的——`grep` 全 `tests/` 确认没有任何一条测试打过 `DELETE /admin/accounts/{id}`。这恰恰是缺口一那句话的另一半：`tests/test_tool_hygiene.py` 十条断言全绿，是因为它们直接调函数、不经过路由，所以「实现了」和「接线了」在测试里长得一模一样。于是补两条**走真实路由**的测试（`create_app` + `/admin/login` + `DELETE /admin/accounts/{id}`，再读 `/admin/stats` 的 `cache.conversation_quota`）：一条断言被删账号那行消失、同时另一账号那行还在；一条断言从未上报过 quota 的账号删起来不报错。

**并且验证了这两条测试有牙。** 一条「加了也照样过」的路由测试比没有更糟，因为它会把没接线伪装成已接线。做法是临时把 `routes_admin.py` 里那两行 `forget` 注释掉再跑：`test_deleting_an_account_clears_its_quota_from_the_admin_snapshot` **FAILED**（断言里能看到被删账号 `acct_a052a27b…` 仍在 stats 里），其余 25 条通过；恢复后 26 条全过，且 `git diff` 确认该文件回到 +7 行、mutation 标记无残留。这个「先破坏再确认测试会红」的动作，本轮已经三次证明是必要的：Cowork 那次 401、HTTP 矩阵那次 18/18 FAIL、以及这里——**判据本身有效，才有资格用它下结论**。

净结果：`substrate_client.py` 的改动从 +93 行降到 +79 行，`conversation_quota.py` 少两个方法（`get`/`clear`）多一个方法（`forget`），测试从 21 条增到 26 条（其中 2 条走真实 HTTP 路由），套件 2076 通过 / 3 跳过，pyflakes 门 exit=0。




### Cowork：五个问题全部有答案，本账号**已确认有权限**（2026-09-14 实测）

`artlovan/copilot_cowork_mcp`（MIT，独立实现，4 个源文件）的 `TECHNICAL.md` + `client.py` + `auth.py` 把 09-11 记下的 Cowork 协议补全了，并且**改正了其中三处**。它连的是 GitHub Copilot CLI ↔ Cowork，所以整条链路是完整可读的。

**对 09-11 那份记录的更正（三处）：**

| 09-11 记的（来自 `bakapiano`，无许可证） | 本轮（`artlovan`，MIT） |
|---|---|
| 运行时 host 是 `mcsaetherruntime-seas.as-ia101...`（看着像写死的区域码） | **是发现出来的**：先 `GET https://cowork.us-ia888.gateway.prod.island.powerapps.com/v1/routing`（带 `x-ms-user-pdl: NAM`）拿 `{"endpoint": ...}`，失败才回落 `mcsaetherruntime.cus-ia302...`（`client.py:27-28,50-61`） |
| `GET /v1/subscribe?conversationId=` 拿 SSE，再 `POST /v1/messages` | **首轮是 `POST /v1/subscribe`**（同一个请求既发消息又开流），后续才 `POST /v1/messages` 拿 202、答案回到已开的流上；`GET /v1/subscribe?conversationId=` 只是**断线重连**用（`client.py:204,234,252`） |
| Origin 是 `https://copilot.cloud.microsoft` | `https://m365.cloud.microsoft`，且 `Authorization` 与 **`x-ms-weave-auth` 两个头必须携带同一个 Bearer**（`client.py:36-46`）。后者我们完全没记过 |

**新事实：**

- `conversationId` 不是随机 uuid，是 `{tid}:{oid}:{uuid}`，前两段从 JWT claims 取（`client.py:80-84`）。
- 事件比我们记的四个多得多：除 `dx`（增量 `{"t"}`）/ `fr`（**一次回答结束，不是流结束**）/ `rl` 外，还有 `session`（`{"sid"}`）、**`th`（推理/思考块 `{"c"}`）**、`ta`（工具审批请求 `{tn, params, aid, to}`）、`ts`（工具开始）、`tx`（工具结果 `{tn, ok, dur}`）、`tk`（任务进度）、`ti`（标题）、`ps`（进度文案）、`rh`。
- **Cowork 有一套工具审批协议，而 substrate 没有。** 工具名是 MCP 风格的 `mcp__m365_teams__PostMessage`，拆成 `server_name` / `tool_name`，审批走 `POST /v1/tool-approval`，body 带 `approval_id` / `approved` / `always_allow` / `edited_input`（可改参数再放行）/ `scope`。这是一个我们两个上游面都没有的形态。
- 它也**没有权威 token 计数**（印证 09-11）。

**认证（这是本轮最要紧的一条）：** 运行时校验 JWT 的 `appid`。要求是 `aud` = `96ff4394-9197-43aa-b393-6a41652e21f8`（Power Virtual Agents）、`scp` = `user_impersonation`、`appid` = `c0ab8ce9-e9a0-42e7-b064-33d422df41f1`（M365ChatClient）。

`c0ab8ce9` **正是我们已经绑定的那个 client**（`refresh_via_rt.py:50` `M365_NATIVE_CLIENT_ID`，在 `M365_REFRESH_CLIENT_IDS` 里），而 `mint_scoped_token`（`refresh_via_rt.py:184-229`）做的事就是「用**签发这个 RT 的那个 client** 把 RT 换成任意 audience 的 token」—— 我们已经用它换 `ic3.teams.office.com`（媒体）和 `designerappservice`（Designer）两个 audience。所以拿 Cowork token 需要的改动是**一个 scope 常量**：

```
mint_scoped_token(accounts, account_id, "96ff4394-9197-43aa-b393-6a41652e21f8/user_impersonation")
```

不需要浏览器、不需要新凭据、不需要 Playwright，也**不触碰 09-11 记下的那条 FOCI 边界**（仍然是「用签发它的 client 续期」，不是跨 client 兑换）。`artlovan` 自己走的是 Playwright + `nativeclient` 重定向的交互式授权码流（`auth.py`，RT 约 90 天滑动窗口）—— 我们不需要那半，因为我们的 PKCE 登录已经产出了同一个 client 的 RT。

**这一格已经量掉了，而且答案是「有权限」。** 但过程里我自己先下了一个错的结论，按本文件的惯例把它记下来。

**第一次探测的判据是错的。** `.probe/cowork_entitlement.py` 只调了 `GET /v1/routing`（`cowork.us-ia888…`），拿到 401 `invalid_audience` 就打印了 `VERDICT=NOT_ENTITLED_OR_REFUSED`。**那个结论不成立**：401 是「这个 token 不对」，不是「这个账号没有 Cowork」，而我把两者当成了一回事——同一个坑的老形态（拿一次失败的返回码当事实判据）。真正的判据必须能区分「我发错了」和「上游拒绝我」，所以补了一个只读矩阵（`.probe/cowork_audience_matrix.py`：4 种 audience/scope 拼法 × 3 种 header 组合 × 2 个 host）。

**矩阵结果（全部只读，未 POST 过任何 endpoint，未创建会话）：**

| audience / scope | mint | `routing/v1/routing` | `runtime/v1/models` |
|---|---|---|---|
| `96ff4394…/user_impersonation`（artlovan 记的那条） | OK，`aud` 为裸 GUID、`appid=c0ab8ce9`、`scp` 含 `user_impersonation`、`tid`/`oid` 齐全 | 401 `invalid_token` | **200** |
| `96ff4394…/.default` | OK，同上 | 401 `invalid_token` | **200** |
| `api://96ff4394…/.default` | OK，但 `aud` 变成 `api://` 前缀形 | 401 `invalid_token` | 401 `INVALID_TOKEN`（"Protocol 'Bearer' failed to validate"） |
| Power Apps 那个 resource | **MINT_FAILED** `AADSTS65002`：first-party app `c0ab8ce9` 与 first-party resource `475226c6…` 之间未同意 | — | — |

三条结论，按重要性：

1. **本账号有 Cowork，判据是 runtime 自己答了 200。** `GET https://mcsaetherruntime.cus-ia302…/v1/models` 返回真实模型列表（见下），所以「权限」这一格是 **ENTITLED**。这是 Cowork 从 09-11 记录至今第一次有活体证据。
2. **`aud` 必须是裸 GUID，不能是 `api://` 前缀形。** 同一个 RT、同一个 client、只差这一个拼法，runtime 就从 200 变成 401。这也说明上面那个 401 确实是「token 形状不对」而不是权限问题——两种拼法的权限完全一样。
3. **`/v1/routing` 那个 host 不吃我们这个 token，而它并不是必需的。** header 组合也量了：只发 `Authorization` → `invalid_token`；只发 `x-ms-weave-auth` → `Missing Bearer token`（所以它确实两个头都要看）；两个都发 → 仍然 `invalid_token`。而 `artlovan` 自己就写了 routing 失败要回落到硬编码 runtime host，我们实测的正是这条回落路径可用。所以 routing 需要的可能是另一个 audience（未知，且不影响可用性）。

**顺带答上 `GET /v1/models`（09-11 列为未知）：** 3 个模型，`provider` 全是 `openai`、`orchestrator_type` 全是 `copilot`：

| id | display_name |
|---|---|
| `gpt-5.5` | GPT-5.5 |
| `gpt-5.6-sol` | GPT-5.6 Sol |
| `gpt-5.6-terra` | GPT-5.6 Terra |

每个模型带 `default_effort_level` / `supported_effort_levels` / `llm_health_bucket` / `requires_data_retention` / `alias` / `description`，顶层另有 `auto_health_buckets: ["llmapi","openai"]`。

**这解释了一条我们 08-28 记下的「查无此物」，而不是推翻它。** `tone_options.py:18` 记着 `gpt-5.6-sol` / `gpt-5.6-terra` / `gpt-5.6-luna` / `gpt-image-2` 这四个名字在 12 种拼法下全部「empty response twice」，结论是「它们不是本租户的 tone 值」。**那个结论是对的**——它们不是 substrate tone，而是 **Cowork 的 model id**，活在另一个上游面上。所以两条记录一致：同一批名字，在 substrate 上不存在，在 Cowork 上是一等公民。注意只解释了其中 2 个：`luna` 和 `gpt-image-2` 不在这份列表里，仍然无来源。

**与 09-11 记录的一处冲突：** `bakapiano` 记的 Cowork 模型是 `melon` = Fable 5.1，而本账号的列表里**没有 melon，也没有任何 Anthropic 模型**，三个全是 OpenAI。可能是租户/rollout 差异，也可能是它那份记录已经过期。未验证，只记差异。

**下一步不再是权限探测，而是一次真实对话。** 但那需要 `POST /v1/subscribe`（会创建会话、发消息），已超出只读边界，属于要单独决定的动作。在那之前，Cowork 的状态是：**协议已知、权限已确认、token 我们已有能力签发**。

### `microsoft/PyRIT`：微软自家 MIT 代码里有一个 substrate ChatHub target

`pyrit/prompt_target/websocket_copilot_target.py`（716 行）打的就是 `wss://substrate.office.com/m365Copilot/Chathub`，MIT，微软版权头。它的价值是**权威旁证**而不是可搬代码：

- **图片上传与我们逐字段一致**：`POST https://substrate.office.com/m365Copilot/UploadFile`，`scenario=UploadImage` + `conversationId` + `FileBase64`，头 `x-scenario: OfficeWebIncludedCopilot` + `x-variants: feature.EnableImageSupportInUploadFile`，Origin `https://m365.cloud.microsoft`，取回 `docId` 再拼成 `messageAnnotationType: "ImageFile"` 的 annotation。与我们 `substrate_upload.py:25,125-181` 完全同形。我们 08-xx 的实现原本是从 M365Bridge（无许可证）验证来的 —— 现在有了一份**微软自己的 MIT 版本作为同一事实的干净来源**。
- **一处差异，未验证后果**：上传的 `optionsSets` 它发 `["cwcgptvsan", "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch"]`，我们发 `gptvnorm2048`（三个我们都在 chat 的 `_OPTIONS_SETS` 里有）。它的 chat `optionsSets` 是完全另一族（`enterprise_flux_web` / `enterprise_flux_work` / `enterprise_toolbox_with_skdsstore` / **`enterprise_flux_work_code_interpreter`** / `enable_batch_token_processing`），与我们只有 `enable_batch_token_processing` 一项交集。**不要据此改我们的 flag**：08-25 实测过 `cwc_code_interpreter*` 那 6 个在本租户不承重，所以「换一族 flag 名」这种改动必须先有 oracle，否则只是把一组没测过的字符串换成另一组。
- **它的 `allowedMessageTypes` 比我们窄**（没有 `Progress` / `GeneratedCode` / `EndOfRequest` 等），所以它拿不到我们赖以工作的 `GeneratedCode` 帧；它也只认 type 2 的 `FINAL_CONTENT`，不折叠 type 1 增量。属于「红队一次性取答案」的取舍，不是我们要的形状。
- **它的认证是我们明确的停损线**：`CopilotAuthenticator` 用 Playwright 驱动登录并要求 `COPILOT_USERNAME` / `COPILOT_PASSWORD` 环境变量（`copilot_authenticator.py`）。存明文密码是我们 08-20 就写进停损条件的那一条，不采纳。`ManualCopilotAuthenticator` 接受外部 token，形态与我们相同。

### 个人版（消费者版）：本轮补上一直欠的那一面，两个 MIT 独立实现印证我们、并给出一条新事实

前几轮复扫都集中在 work/school substrate 那一面，个人版（`copilot.microsoft.com/c/api`）欠测。本轮补上：用我们自己的帧名去搜（`c/api/chat?api-version=2`、`reportLocalConsents`、`partialImageGenerated`、`appendTextSuggestion`），这一面的生态是**独立的一族**，与 substrate 那族几乎不重叠。

**先更正本文件自己的一条判决。** 下面「顺带否决」里原来把 `sums001/Windows-Copilot-API` 等一律按「上游是 Windows/消费者版 Copilot」排除。**这条排除标准用错了**：消费者版正是我们支持的第二个 provider（`consumer_client.py` 2044 行、`consumer_gate.py`、`consumer_camoufox.py`），不是本文件开头要排除的「不同产品」。开头的排除项针对的是 **GitHub** Copilot 和已归档的 Bing Chat，不是个人版。按正确标准重判：

| 仓 | 许可证 | 派生核查 | 结论 |
|---|---|---|---|
| [`sums001/Windows-Copilot-API`](https://github.com/sums001/Windows-Copilot-API) | MIT，1237★，Python | `fork=false`、`parent=none` | **可采纳**，本面最完整的一个 |
| [`atomic-reactor/msco-pi-lot`](https://github.com/atomic-reactor/msco-pi-lot) | MIT，8★，TS | `fork=false`、`parent=none` | 可采纳，带 `TECHNICAL_SPEC.md` |
| [`badafans/copilot2api`](https://github.com/badafans/copilot2api) | MIT，1★，Go | `fork=false`、`parent=none` | 可采纳，只印证 |
| `lemon-casino/Microsoft-Copilot-API`、`liwei9745/windows-copilot-api-custom`、`yo-steven/Windows-Copilot-API-exploration-*`、`b8myk8sbfg-stack/OpenClaw` 内嵌副本 | MIT | 与 `sums001` 同源（`copilot/protocol.py` + `copilot/driver.py` 同构） | 同一实现的分身，不重复评估 |
| `g4f`（`xtekky/gpt4free` 一族，13 个仓） | GPL-3.0 | — | **不可采纳**（GPL 与本项目 Apache-2.0 不兼容），且 `Copilot.py` 只处理 `appendText`/`partialImageGenerated` 两个事件，比我们浅 |

**它们印证了我们三条最贵的结论**（三处都是我们踩过坑才得到的，现在有独立第二来源）：

1. **握手必须在 `connected` 之后、且 `send` 不能早于 `setOptions`/`reportLocalConsents`。** `sums001/copilot/protocol.py` 的 docstring 明写「A `send` issued *before* the setOptions/consents handshake is rejected by the backend with ``error: invalid-event``」——与我们 `consumer_client.py` 里那段「curl_cffi 的 `ws_connect` 在 101 就返回，比 `connected` 早一个往返，所以从那里开轮每次都输掉这个竞态」逐字同义。
2. **空 challenge（`method`/`parameter` 皆 null）不是 no-op。** 它同样记着「ack an empty challenge with an empty token」是错的，会让 socket 等一个永不到来的 token 然后静默超时。我们的 `solve_challenge` 返回 `None` 并抛 `TurnRefused`（不回答、不重铸凭据），是同一个结论。
3. **`hashcash` / `copilot` 两种 PoW 可在进程内算，Turnstile 不行。** 分支与我们 `consumer_client.py:302-313` 完全一致。

**一条我们没有的新事实（来自 `sums001`）：** 它抓真实 web 客户端看到的是——网页端会用一个 `method:"cloudflare"` 的 **Turnstile token** 去回答 `{method:null}` 那帧，并且该帧**只在 `cf_clearance` 过期时出现**。这给了我们 08-12 那次「已撤回的 TLS 指纹判读」一个**替代解释**：不是 profile 选错，而是 clearance cookie 的状态。注意这仍是**它的观测、不是我们的**——我们自己的结论（同一账号同一出口，method 会自行漂移）没有被推翻，两者可以同时成立（clearance 过期 → 出现该帧；而何时过期与我们观察到的漂移一致）。**要证实需要一格对照实验**：同一账号，带新鲜 `cf_clearance` 与故意作废的 `cf_clearance` 各发一轮，看 `method` 是否分别为非 null / null。本轮没做。

**一处真实差异，够格成为待办（但仍是假设）：** 它们两个都处理**应用层 `ping`**，我们不处理。

| 实现 | 处理 | 位置 |
|---|---|---|
| `atomic-reactor/msco-pi-lot` | 收到 `event:"ping"` 立刻回 `{"event":"pong","id":<pingId 或 lastEventId+".0001">}` | `src/runtime/session-runtime.ts:539-541` |
| `badafans/copilot2api` | `pong` 列在「已知可忽略」事件里（说明它见过） | `internal/copilot/websocket.go:320` |
| **我们** | `consumer_client.py` 只认 10 个事件（`connected`/`appendText`/`imageGenerated`/`partialImageGenerated`/`generatingImage`/`done`/`challenge`/`chatMessageError`/`error`/`send`），**`ping` 与 `pong` 全 0 命中** | — |

为什么值得记：我们记了一族「个人版 `partialImageGenerated` 之后上游断连」的错误（08-25 记录里生产 100 条日志中 8 条 error 全是这一族），而出图轮正是**唯一会长时间静默**的轮次（每帧 250-460KB base64、解析慢）。如果上游用应用层 ping 判活、而我们从不回 pong，被断的正会是这种轮次。

**但这条目前只是假设，不能当成结论**：我们 27 个消费者相关的 `.probe` 制品里，**入站帧一个都没存**（唯一命中的 `send` 是我们自己发的），所以「上游到底发不发 ping」我们没有证据。**判据要先量**：加一条只记录不改行为的埋点，把入站 `event` 名去重记下来跑几轮出图轮；只有真的看到 `ping` 才谈回 pong。先改代码等于凭别人的抓包猜我们的上游。

另外 `msco-pi-lot` 还有两个我们没有的请求侧字段，同样未验证：`isIncremental`（把后续消息作为增量而不是整段 prompt 重发）与 URL 上的 `channel` / `edgetab=1`。它的 `TECHNICAL_SPEC.md` 明说 `isIncremental` 是它自己加的实验字段（注释里全是 "NEW FIELD"），不是抓包所得，所以**不要照抄**——那是它对服务端行为的猜测。

### 顺带否决

- `my788525/M365-Copilot2API-FNOS`（license `other`，Go）：描述自陈「enhanced fork of HEXUXIU/M365-Copilot2API」，按 09-11 的判决族直接排除，代码一行不能进。
- `Bosco1262/M365-Copilot2API-on-Cloudflare-Worker`（2★→6★，`other`）：`addToChainOfThought` 在 `src/chathub/protocol.ts` 命中，形态仍是 HEXUXIU 一族，08-30 的一句话否决不变。
- `de0921188/m365-copilot2api`、`jiajia2222/M365-Copilot2API-AutoAuth`、`rubber-duck-fly/copilot2api`、`dat267/m365-copilot`：无许可证或 `other`，无描述，属同族。
- `eduardoalco/cowork-cli`（MIT，TS）：描述称连 M365 Copilot Chat/Retrieval API 与 Cowork MCP，但走的是官方 Chat/Retrieval 面，不是 Cowork runtime，且没有我们缺的协议事实。
- `diegosouzapw/OmniRoute`（MIT，65917★）及其十余个镜像/vendor 仓（`bloodf/durindoor`、`jaccen/AIRoute`、`zcus0/z-OmniRoute` 等）：`copilot-m365-connection.ts` 里有 `XRoutingParameterSessionKey`，但量级与目标与本项目不同，09-01 的定位不变。
- `loryanstrant/M365Copilot-Cowork-Reporter`（MIT）/ `M365Copilot-Usage-Reporter` / `microsoft/PAX` 系 / 各类 readiness / prompt library / adoption 仓：报表与治理工具，不触协议。
- `asllani94/copilot2api`（MIT）、`c0rt3z4/unofficial-copilot-api`（MIT）、`OEvortex/copilot-api`（NOASSERTION）、`Ottitsch/m365-auth`（无许可证）：分别是 GitHub Copilot CLI 包装、旧版 WebSocket 玩具、以及 substrate 的薄封装，均无我们缺的协议事实。个人版那一面已按正确标准单独评估，见上一节。
- `artlovan/copilot_image_gen_mcp`（MIT，1★）：与 Cowork 同作者，走 Copilot 出图，命中 `XRoutingParameterSessionKey`；已读，无我们缺的字段。



## 2026-09-15 上线 + 部署容器实测：死代码已删、配额已在生产可见、两条旧结论被推翻

本轮不扫仓，只做三件事：把待办 11 定案执行、把配额接线部署到 `ciallo-ms365-proxy-multi`、按 `AGENTS.md` 在**部署容器内**跑完整验收矩阵。约束是宿主机不落任何文件，所以全部改动经 `docker exec -i ... tee` 由 stdin 流入容器，每个文件逐一核对 SHA-256。

### 待办 11 定案：删，不接线

按上一节两条实测（单轮最大 1 个调用 → 上限零触发；`refuse_over_cap` 的字典输出在本架构里没有投递通道，因为本代理从不发 `role:"tool"`），结论是**整块删除**而不是接线。已从 `tool_hygiene.py` 移除：

`MAX_TOOL_CALLS_PER_ROUND` / `MAX_TOOL_CALLS_PER_TURN` / `REASON_BUDGET_SPENT` / `REASON_TOO_MANY_THIS_ROUND` / `_REFUSAL_MESSAGE` / `tool_round_allowance` / `refuse_over_cap` / `over_cap_reasons`，以及 `tests/test_tool_hygiene.py` 里钉住它们的 allowance/refusals 两节（10 条断言）。

模块 347 → 230 行，测试 319 → 212 行，套件 2076 → 2066 通过（净减 10 条只测死代码的断言）。两个 docstring 都留了「为什么删、别凭直觉加回来」的说明，并指回本文件。剩下的两条卫生（id 去重、孤立 tool_result）本来就已接线，不受影响。

### 部署

改动落到容器 `/app/src`（先 `cp -a` 出 `/app/src.bak-0914`，110 个文件）。7 个文件逐一哈希核对一致，容器内先做导入检查（8 个模块全 OK、被删符号确认不再导出）再 `docker restart`。启动无报错，`healthy`、`restarts=0`。

### 验收矩阵：11/12 PASS

公网端点被 Cloudflare 以 `403 code 1010` 拦掉 urllib 的指纹（不是代理返回的），所以矩阵改从容器内直连 `127.0.0.1:8000` —— 这既绕开 CF，也更贴合「测部署构建本身」。

| 矩阵项 | 结果 |
|---|---|
| 1 M365 直连/原生 | PASS 文本 / 流式 / 工具轮（`finish=tool_calls`）/ 工具结果续轮 |
| 2 Router 规划 | PASS（见下：本轮 router 真实执行了） |
| 3 Studio 规划 | PASS（同上，studio 真实执行了） |
| 4 Anthropic Messages | PASS 文本 `end_turn` / `tool_use` / `tool_result` 续轮 |
| 5 OpenAI Responses | PASS 文本 / function tool / 工具续轮，均 `status=completed` |
| 6 个人版 | **FAIL**，但原因是环境不是代码，见下 |
| 新字段 `cache.conversation_quota` | PASS，部署构建上读到 `messages=1 max=600 remaining=599 percent=0.17` |

**规划模式这次是真覆盖，上一轮不是。** 上一轮 HTTP 矩阵三种配置全塌成 `router`，我如实记了那条局限。本轮从部署容器 `call_log.json` 普查，100 条里 `studio` 36 次、`router` 19 次、`inline` 3 次，且最近 10 条里能看到 `Claude_Sonnet -> studio` 带 `get_weather`、以及 `-> router`。所以矩阵 2、3 这次有真实证据，不是「配置写了但没走到」。

### 推翻我自己上一轮的两条记录

**(1) 个人版的阻塞项不是「没有 RT」，是账号自己配了一个死代理。**

待办 13 我写的是「凭据过期且没有可用于无浏览器续期的 RT」。前半对，后半的因果错了。部署后启动日志直接给出真正原因：

```
Consumer refresh unavailable for acct_b1172aff4361: the configured outbound proxy
204.76.203.9:3128 is unreachable (ConnectionRefusedError), so Camoufox would fail
its own geoip lookup before the browser starts. Fix or clear this account's proxy;
credentials are untouched.
```

即 Camoufox 续期路径**根本没走到浏览器**就退了：`consumer_camoufox._assert_proxy_reachable` 在启动前先探代理，而该账号 `proxy_url = 'http://204.76.203.9:3128'`（来自 `proxies_20260812_091451.txt` 那批节点，现已拒连）。`_proxy_option` 用 `geoip=True`，Camoufox 自己的 `public_ip()` 要穿这个代理，所以死代理会让整个 launch 失败——这个 fail-fast 是有意加的，日志也点名了修法。**结论变化：个人版凭据重铸不需要人工重推，清掉或换掉这个账号的 `proxy_url` 就能让无人值守续期恢复。** 容器 env 里没有任何代理变量（`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 全 unset），全局 `proxy_url` 也是空，所以这是纯账号级配置问题。

**(2) 「个人版可能也有 RT」这个猜想：实测否定，而且我上一个探针的判据是错的。**

我先写了个探针打印「has refresh_token field populated: True」，据此以为个人版存了 RT。**那个 True 是假的**：我检查的是 dataclass 上字段是否存在（`Account` 是 M365/consumer 共用的，字段永远存在），不是是否有值。改成检查值之后：个人版 `refresh_token present=False len=0`、`_stored_binding -> None`，即 `mint_scoped_token` / `refresh_via_rt` 会直接拒绝它；M365 那个账号则是 `len=1405`、绑定 `client=c0ab8ce9`（native 滑动 RT）。

所以**个人版这条路径在设计上就不用 RT**，长期凭据是 MSA 会话 cookie（`__Host-MSAAUTHP` / `WLSSC`），续期靠页内 MSAL 静默 SSO 现铸 ChatAI token。「捞 MSAL 缓存里的 RT 来省掉 Camoufox」这个想法本轮无法验证，因为该账号连 profile 目录都还没建（`/home/app/token/profiles/acct_b1172aff4361` 不存在，MSAL 缓存无从检查）——而 profile 建不起来正是因为上面那个死代理。**这条要等代理修好、续期跑通一次之后才有得看。**

### 个人版三个门的分诊：只有第一个能靠改配置解决（2026-09-15 实测）

既然阻塞项从「缺 RT」变成了「死代理」，就该问下一个问题：**清掉那个 `proxy_url` 之后，个人版是不是就通了？** 答案是「传输层通，另外两道门仍未测」。两个只读探针（`.probe/consumer_egress_check.py`、`.probe/consumer_blockers.py`，都不写任何状态）给出：

| 门 | 实测 | 能否靠改配置解决 |
|---|---|---|
| 1. 传输层 | **直连 `copilot.microsoft.com` HTTP 200**，回 8 个 cookie（`MUID` / `MUIDB` / `_C_Auth` / `__cf_bm` …）；同一目标经配置的代理 `curl: (7)` 连接被拒 | **能** —— 清掉该账号 `proxy_url` 即可 |
| 2. 凭据新鲜度 | `consumer_token` 有值（1716 字符）但**不是可解码的 JWT**，所以本地无法判断过期；MSA cookie 快照 **9.6 天** 前更新 | 不能，只能由一次真实调用分类 |
| 3. 出口地域资格 | 直连出口是 **JP / Tokyo / AS31898 Oracle**。落地页 200 **不代表**该出口有资格聊天——拒绝是以 `chat-service-unavailable` 出现在 chat socket 上（映射成 `RegionBlocked`） | **未测**，且无法在不发真实轮次的前提下测 |

三条要记住的：

1. **`consumer_token` 不是 JWT。** 它是 MSAL 铸出的 ChatAI token，本地拿不到 `exp`，所以「凭据是否还有效」这个问题**在容器内无法离线回答**——我 09-14 写「consumer_token 存在但已失效」时其实没有证据支持「已失效」，那是从 401 反推的猜测。准确说法是：**状态未知，只有一次真实调用能分类**。
2. **落地页 200 是最弱的一种成功。** 它只说明 TCP+TLS+Cloudflare 放行了这个出口，不说明该出口能开聊天。08-12 记录的 `chat-service-unavailable`（→ `RegionBlocked`）正是「传输通、地域不通」的形态。所以修完代理后如果仍然失败，**要看错误是 `RegionBlocked` 还是 `ClearanceRequired`**：前者要换出口，后者要重铸凭据，两者的修法完全不同。
3. **9.6 天的 cookie 快照是硬约束。** `consumer_camoufox` 的静默 SSO 是拿这份快照去 seed 的，MSA 会话 cookie 有自己的有效期；快照越旧，静默流回落到登录墙的概率越高。所以「清代理 → 立刻跑续期」这个顺序有时效性，不宜久拖。

**结论：清掉 `proxy_url` 是必要但可能不充分的一步。** 它是唯一一个我们能确定性修好的门，且不需要碰凭据（错误信息自己就写着 `credentials are untouched`）。修完之后立刻跑一次 Camoufox 续期，然后按上面第 2 条读错误类型分流。矩阵第 6 项在此之前无法转 PASS。

### 更正上面那张表：门 2 先于门 3 触发，清代理确定不够（2026-09-16 实测）

上一节把「清掉 `proxy_url` 之后会怎样」留成了推测，并且默认门 3（地域）是下一个要面对的东西。真发一轮就知道排序是反的。

探针 `.probe/consumer_direct_egress_turn.py`（只读：运行时强制 `proxy=None`、`gate=None`，**不改**存储的 `proxy_url`；`gate=None` 保证 Cloudflare 一旦要求验证只会抛异常，不会拉起浏览器去写 profile）。流入容器、SHA-256 `542e15f7…` 双端一致后运行，结果：

```
cookies handed to the client: 28
consumer_token present: True
identity_type: (none)
VERDICT=OTHER_CONSUMER_ERROR
  ConsumerCopilotError: Could not create a Copilot conversation (HTTP 401): Unauthorized
```

**401 不是三种预期错误里的任何一个。** 不是 `RegionBlocked`（那是 chat socket 上的 `chat-service-unavailable`），不是 `ClearanceRequired`（那是 403），也不是 `AccountThrottled`。它是会话创建这一步就被拒。

两条推论：

1. **直连出口的传输层是通的，已经通到应用层了。** 401 是服务本身给出的应用层回答，说明 TCP、TLS、Cloudflare 和路由全部放行——门 1 不只是「落地页 200」那种弱成功，而是真的能把带凭据的请求送到会话创建端点。JP/Oracle 机房出口在**这一步**没有被拦。
2. **门 2 在门 3 之前触发，而且已经被分类了。** 上一节第 989 条我写「凭据状态未知，只有一次真实调用能分类」——那次调用现在做了，分类结果是**凭据被拒**。所以门 3（地域资格）不是「未测」而是**在拿到有效凭据之前不可测**：请求根本走不到 chat socket，`chat-service-unavailable` 没有机会出现。表里第 3 行的「未测」要按这个理解，不是还差一次测量，是缺前置条件。

**因此上一节的结论要收紧：清掉 `proxy_url` 是必要的，而且现在可以确定它不充分。** 不再是「可能不充分」——401 已经证明存储的 `consumer_token` + 28 个 cookie 这套组合不再能认证。清代理只解锁续期路径，不修凭据；凭据要靠 Camoufox 那次静默 SSO 重铸，而它正是被死代理 fail-fast 挡住的东西。

**关于「换一个活节点」而不是「清掉」：本轮做不到，因为节点表已经不在磁盘上了。** 该值出处 `proxies_20260812_091451.txt` 已不存在；`api.txt` 只有 1 行且不含该节点；`.tmp-github-scan/new_xiaocong{,2}/frontend/data/proxies.txt` 两个路径都是空壳（glob 命中但文件缺失）。而 README 明确把「Consumer 账户级出站代理」列为受支持特性（第 47、598、692 行），所以这个字段**很可能是有意配置的**，不是误填——如果它的用途是绕开机房 IP，那么清掉之后门 3 就会变成真实风险。**要换节点必须由你提供，仓库里已经没有可用来源。**

修复顺序因此是：清掉或换掉 `proxy_url` → 立刻跑一次 Camoufox 续期重铸 ChatAI token → 只有拿到有效凭据后，门 3 才第一次变得可测。续期若自己撞上登录墙，说明 MSA cookie 快照（探针当时 9.6 天）已过期，得走 userscript 重推凭据。矩阵第 6 项在此之前无法转 PASS，阻塞项现在是精确的：**凭据被 401 拒绝，且重铸路径被账号自己的死代理堵住。**

### 再更正：Camoufox 不是唯一的重铸路径，profile 里有一枚仍然有效的 RT（2026-09-16 实测）

上一节写「凭据要靠 Camoufox 那次静默 SSO 重铸」，09-14 我还记过「个人版这条路径在设计上就不用 RT」。两条都错。错因是我 09-15 找 profile 时用的是裸账号 id，而 Camoufox profile 的命名规则带 subject 摘要（`refresh_scheduler.py:187`，`{account_id}-consumer-{sha256(subject)[:24]}`），于是 `acct_b1172aff4361` 查无目录，我据此推断「profile 都还没建，MSAL 缓存无从检查」。真实目录是 `acct_b1172aff4361-consumer-ddd1db7238dd519797a30ab5`，`cookies.sqlite` 最后写入 2026-09-06。

该 profile 的 localStorage 走 Firefox LSNG（`storage/default/https+++copilot.microsoft.com/ls/data.sqlite`，值按 snappy 原始格式压缩；容器 venv 没有 snappy 绑定，探针 `.probe/consumer_msal_rt_metadata.py` 自带解码器，`mode=ro&immutable=1` 只读打开，密钥一律按长度或 sha256 摘要打印）。解出 19 行，MSAL 凭据三枚：

| 凭据 | clientId | target | expiresOn | 相对容器时间 1789488994 |
|---|---|---|---|---|
| RefreshToken | `14638111-3389-403d-b206-a6a71d9f8f16` | 空（正常） | 1791246127 | **剩余 20.34 天，有效** |
| AccessToken | 同上 | `140e65af-45d1-4427-bf08-3e7295db6836/ChatAI.ReadWrite` | 1788682926 | **已过期 9.33 天**，extendedExpiresOn 也过期 9.0 天 |
| IdToken | 同上 | — | — | — |

`familyId` 字段不存在，所以这不是 FOCI 家族 token，不能跨 client 复用。RT 的 `target` 为空是 MSAL 的正常形态：scope 在兑换时指定，不烘进 RT，空 target 不构成阻塞。

三条结论：

1. **401 的形态就是普通过期。** ChatAI 那枚 AT 在探针发请求前 9.33 天就到期，连 extended 窗口也过了 9.0 天。会话创建返回 401 与此完全一致，不需要更复杂的解释。
2. **存储的 `consumer_token` 不是 profile 里这枚 AT。** 前者 2361 字符，后者 1716 字符，不同串；`accounts.json` 中该账号 `provider` 已是 `consumer`。**并更正我上一句写过的「28 vs 3 未查明」——没有这个差异。** 磁盘上的 `cookies` 是 AES-GCM 信封而不是 3 条 cookie：`account_crypto.py:19` 定义的 `{"__enc__": 1, "n": <nonce>, "ct": <ciphertext>}` 恰好三个键，我把信封键数当成了 cookie 条数。用 `/app/.venv/bin/python`（系统解释器缺 `httpx`，`AccountStore` 的访问器是 `.get()` / `.list()`）经 store 解密后是 **38 条 cookie 记录**，含 `__Host-MSAAUTHP` 与 `WLSSC`，`consumer_gate._pick_cookies` 按域名白名单过滤到 **28 条**——正是直连探针交给客户端的数量。两个数字自始一致。
3. **无浏览器重铸从「设计上不可能」变成「值得设计」，但不能顺手试。** 拿这枚 RT 去 `login.microsoftonline.com` 换 ChatAI scope 的 AT，在协议上是通的；可**一旦兑换，MSA/AAD 会轮换 RT**——兑换成功却没把轮换后的新 RT 写回 profile，磁盘上这枚当场作废，唯一的免浏览器路径就被我自己烧掉。所以兑换必须发生在会持久化新 RT 的代码里，不能由一次性只读探针去打。这是本轮**主动没做**的动作。另需注意：MSAL.js 的 SPA 客户端 RT 兑换要求带 `Origin` 且应用注册为 SPA 类型，否则会撞 `AADSTS9002326` 跨源兑换限制——[INFERENCE]，本轮未实测。

修复顺序因此再改一次：不再是「必须先修代理才能重铸」。RT 还有 20 天，兑换打的是 `login.microsoftonline.com`，与该账号那枚死代理无关；死代理只挡 Camoufox 这一条路。两个方案——方案 A：在续期路径里实现 RT 兑换并持久化轮换结果，绕开浏览器与代理；方案 B：继续走 Camoufox，那就得先清掉或换掉 `proxy_url`，而换节点所需的活节点仓库里已无来源。矩阵第 6 项依旧 FAIL，但阻塞项从「凭据被拒且重铸被代理堵住」收敛为「需要你在方案 A / 方案 B 之间选一个」。

方案 A 还有一条本轮实测出来的约束：**账号级 `refresh_token*` 字段全空**（`refresh_token` 长度 0，`refresh_token_authority` / `_client_id` / `_tenant_id` / `_object_id` 皆空串，三个时间戳皆 0.0）。这些字段是 M365 那条 RT 链路用的，个人版从没往里写过。所以方案 A 读不到账号存储里的 RT，唯一的 RT 来源是 profile 的 LSNG localStorage（`storage/default/https+++copilot.microsoft.com/ls/data.sqlite`，snappy 压缩）。这决定了实现形状：要么在兑换后把轮换出的新 RT 写回那个 sqlite（要与 Firefox 的 LSNG 编码一致，风险高），要么给 consumer 账号新增独立的持久化字段，把 RT 从 profile 迁进账号存储后由代码自己接管轮换。后者更可控，但它是一次真实的 schema 变更，不该在没有你确认的情况下就动。

### Cowork：权限有，但真实对话被上游拒绝

09-14 确认了权限（runtime host `/v1/models` 200、3 个模型）。本轮做了那次会写状态的 `POST /v1/subscribe`，结果是**拒绝**，且拒绝方式提供了新信息：

- 不带 `model` 字段 → `409 MODEL_UNAVAILABLE`，body 回显 `"model":""`，即错误点名了缺失字段。
- 带 `model=gpt-5.5` → `409`，`"No model is available for 'gpt-5.5' right now"`，**`available_models":[]`**。
- 带 `model=gpt-5.6-sol` → 同样 `409`、`available_models":[]`。

同一次运行里 `GET /v1/models` 仍然 200 并列出那 3 个 id。**所以 `/v1/models` 列出的是产品目录，不是本账号可用的容量**：目录里有、真要用时 `available_models` 是空。这是一条对 09-14 判决的重要修正——「`/v1/models` 200 + 3 个模型」足以证明**有权限访问 runtime**，但**不足以证明能对话**。

两种可能，本轮无法区分：租户没给 Cowork 分配模型容量（需要管理员在 Power Platform 侧配置），或者还缺一个我们没发的字段/前置调用。`artlovan` 的实现里首轮就是 `POST /v1/subscribe`，没有额外的容量声明步骤，所以更像前者。

**Cowork 的状态因此回退半格：协议已知、runtime 可达、token 可自签，但真实对话未通，做 Provider 的前提尚未满足。** 在 `available_models` 非空之前不值得投入。

### 清理

容器内 7 个探针全部删除，`/app/src.bak-0914` 保留（回滚用）。容器 `healthy`、`restarts=0`。宿主机未落任何文件。

## 2026-09-18 复扫：没有新的可直接采纳实现

窗口为 2026-09-14..09-18，补查 M365 Copilot、Copilot2API、SignalR Copilot、Copilot Cowork，以及已知高信号仓的最新提交。结论仍是：**不换仓、不搬代码**。

### 新出现或有更新的候选

| 仓 | 许可证/状态 | 新信号 | 判定 |
|---|---|---|---|
| `MasayukiTa/m365-copilot-companion-mcp` | MIT，独立实现 | 09-18 更新集中在 fleet/cockpit 可见性、UploadFile 观测字段、桥接器断线重排队、图片读取；没有新的 substrate 协议字段或个人版帧处理 | **IDEAS-ONLY**；继续作为抓包与证据方法参考 |
| `Bosco1262/M365-Copilot2API-on-Cloudflare-Worker` | `NOASSERTION`，9★ | 09-17 有推送，但属于 Copilot2API 同族的 Cloudflare Worker 端口；无干净许可证证据 | **REJECTED**；不能复制 |
| `my788525/M365-Copilot2API-FNOS` | `NOASSERTION`，3★ | 09-16 有推送，明确是 HEXUXIU/M365-Copilot2API 增强分支；无许可证 | **REJECTED**；派生链与许可边界不变 |
| `HEXUXIU/M365-Copilot2API` | `NOASSERTION`，492★ | 09-15 仍有仓库活动，但许可证字段仍为 `NOASSERTION` | **REJECTED**；只可黑盒参考 |
| `Yugpat1835/awesome-copilot-cowork-skills` | CC-BY-SA-4.0 | 15 个 Cowork skill/文档集合，不是运行时客户端或协议实现 | **IDEAS-ONLY**；与反代无可搬代码 |

### 已知仓的增量

- `protella/chatgpt-bots` MIT：09-17 的提交修复 Slack 文件挂载首轮浪费轮次（静态文件 ID 枚举、别名解析、错误码日志）；09-16 的提交修复其自有代码解释器沙箱 OOM/容器替换。它是 OpenAI Responses 本地工具执行器，不是 M365 substrate/Consumer 上游；我们的代理也不在服务端执行客户端工具，因此不搬。
- `microsoft/Agents-M365Copilot` MIT：09-15/16 仍主要是各语言 SDK 的生成模型与 request builder 更新，没有 Graph Provider 新能力可接入当前项目。
- `MasayukiTa` 09-18 的最新提交虽继续强调“先记录观测再写探针”，但内容是其 fleet UI、UploadFile 和桥接器自身缺陷修复；没有改变 09-14 已记录的 Cowork 结论：runtime 目录可读不等于 `POST /v1/subscribe` 有可用模型。

本轮新增搜索结果中，`SignalR + Copilot` 命中的 `fleetpulsesystem` / `dotnet-enterprise-itsm` 是泛 SignalR 应用；`Copilot Cowork` 的高排名结果主要是 benchmark、skill 和插件文档，不是可复用的运行时。未发现新的 MIT/Apache-2.0、独立、可直接补齐当前 M365/Consumer 缺口的实现。

### 当前可执行结论

1. 继续使用现有 Router 默认、Studio 显式实验、Consumer 独立凭据链；没有证据支持换仓。
2. 可继续参考 `MasayukiTa` 的抓包证据纪律、`kdeps` 的 reasoning channel 分离、`artlovan` 的 Cowork SSE/审批协议，但不复制与当前架构无关的代码。
3. 任何 Copilot2API 同族仓仍不得引入：当前 API 元数据均无许可证，且至少两个新仓明确是该族派生分支。

 ## 后续顺序

1. Copilot Studio 账号级显式实验模式已实现，正式 A/B + 一次复测完成，三协议全链路实测通过；Router 继续默认，不自动推广 Studio。
2. 统一三协议的 write deadline/客户端断连释放测试，并覆盖 Studio fallback 的取消路径。
3. 下一候选：若租户具备所需权限，验证官方 Graph chatOverStream Provider。
4. usage 从 `estimated` 升级为带 `token_source`，精确计数放可选开关。
5. 工具调用卫生：tool_call id 唯一性、孤立 tool_result 拒绝、单轮工具轮数上限。
6. 需要补协议测试时，再从 sideeffffect 和 kuchris 提取可验证的测试思路。
7. 推理转录已确认在线（2026-09-01），可选做：渲染成 Anthropic `thinking` 块与 OpenAI `reasoning_content`。要动三个协议渲染器，收益是把现在丢掉的转录变成可见的推理过程。**09-14 补充：`kdeps`（Apache-2.0）已实测落地这条，两条不变量可直接用（转录与答案分开成两条流；工具轮里答案要缓冲、转录始终可以直播），见上。**
8. `stop` / `stop_sequences` **已完成**（2026-09-11，见上）。剩 `/v1/responses` 有意未接（该 API 无此参数）。
9. `deepResearchModels`：**已于 09-11 定案删除**，四变体实测证明它是惰性的。
10. Cowork **09-15 降级：有权限 ≠ 能对话**。09-14 用 `GET /v1/models` 在 runtime host 拿到 200 + 3 个模型，我据此写下「已确认本账号有权限、剩下只差一次真实对话」。09-15 做了那次真实对话，**被拒**：`POST /v1/subscribe` 三次都是 **409 `MODEL_UNAVAILABLE`**，且回包 `"available_models":[]`。不带 `model` 字段时报 `"model":""`，带上 `gpt-5.5` / `gpt-5.6-sol` 后报 `No model is available for 'gpt-5.5' right now`——即字段形状对了、模型池是空的。所以 `/v1/models` 那 200 只证明**目录可读**，不证明**运行时可用**：那是两个不同的东西，而我把前者当成了后者。token 签发（`mint_scoped_token` + 裸 GUID audience）、conversationId 形状（`{tid}:{oid}:{uuid}`）、双 Bearer 头（`Authorization` + `x-ms-weave-auth`）三条仍然有效且已验证。现状：**协议已知、目录可读、运行时无模型**，做 Provider 的前提不成立。是租户未开通、还是 SKU 差异、还是暂时性，本轮无法区分——`available_models` 空数组是上游给的唯一线索。routing host 仍然 401（09-14 的坑不变）。
11. **已完成（09-15 定案删除）。** `MAX_TOOL_CALLS_PER_ROUND` / `MAX_TOOL_CALLS_PER_TURN` / `refuse_over_cap` / `tool_round_allowance` / `over_cap_reasons` / `REASON_*` / `_REFUSAL_MESSAGE` 全部从 `tool_hygiene.py` 删除，钉住它们的 13 条测试同时删除（`tests/test_tool_hygiene.py` 从 26 条降到 13 条）。删而不接的依据是两次实测：**(1)** 单轮最大调用数 = 1（部署容器 100 条日志里 42 条带 tool_call），上限一次都不会触发；**(2)** `refuse_over_cap` 的契约要求把超额调用变成「客户端可配对的合成失败结果」，但本代理**从不发 `role:"tool"` / `tool_result`**、也没有工具执行器，那个字典在本架构里没有投递通道。模块 docstring 里留了一段「为何删除、什么条件下才该重新引入」，防止凭直觉重建。待办 5 里真正承重的那半（`dedupe_tool_call_ids` / `dedupe_tool_call_payloads` / `orphan_tool_results`）不受影响，仍在四条投递路径上接着，同一份日志里触发过 5 次。
12. **上游权威配额已接线（2026-09-14 完成）**，这条从「缺口」转为「已交付」。完成帧/更新帧的 `throttling.numUserMessagesInConversation` / `maxNumUserMessagesInConversation` 现在由 `substrate_client._conversation_quota_from` 解析、`_note_quota` **转发给 sink**（client 自己不留副本——留了就是没人读的状态，见下面「自查」），`ConversationQuotaStore` 存最新值，`/admin/stats` 的 `cache.conversation_quota` 呈现，账号被删时 `forget()` 清掉那一行。活体验证两层：直接调 client 时同一 `PersistentSession` 两轮 `messages` 1→2、`max=600`、sink 触发 4 次；真实 HTTP 路由上三协议 18/18 PASS（读到 `1/600`、`remaining=599`）。**它不进 token usage** —— 计的是消息条数不是 token，且是会话级 gauge 而非累计量，混进 `usage_store` 会同时犯两个类别错误。详见上面「缺口二已接线」「HTTP 验收矩阵」「自查」三节。
13. **个人版 `ping`/`pong` 仍未测到，但 09-15 推翻了我记的阻塞原因。** 我 09-14 写的是「凭据过期且没有可用于无浏览器续期的 RT」，把它当成设计使然。真实原因是**该账号自己的 `proxy_url` 指着一个死代理**：`acct_b1172aff4361.proxy_url = 'http://204.76.203.9:3128'`，连接被拒（`ConnectionRefusedError`）。两条路径都因此断掉——`consumer_camoufox._assert_proxy_reachable` 在启动浏览器前就 fail fast（`geoip=True` 会让 Camoufox 自己的 `public_ip()` 走这个代理），而 curl_cffi 的聊天轮直接 `curl: (7) Failed to connect to copilot.microsoft.com:443 over proxy 204.76.203.9`。容器 env 里**没有**任何代理变量，`runtime_settings.proxy_url` 也是空——纯粹是这一个账号的字段。**修法是清掉或修好该账号的 proxy，不需要重铸凭据**（错误信息自己就写着 `credentials are untouched`），也不需要 userscript 重推。另外更正一个我自己制造的假信号：中途有一个探针报 `has refresh_token field populated: True`，那是在检查 dataclass **字段是否存在**（永远为真），不是是否有值；精确探针的结果是 `refresh_token present=False len=0`、`_stored_binding -> None`，所以「个人版没有 RT、走 MSAL cookie 静默续期」这条原始记录是对的。**个人版 MSAL RT 那条只读探查（我上一轮建议的第 3 项）本轮无法进行**：`/home/app/token/profiles/acct_b1172aff4361` 不存在，没有 profile 就没有磁盘上的 MSAL 缓存可查——而 profile 要等一次成功的 Camoufox 续期才会生成，那又被同一个死代理挡着。所以顺序是：先清代理 → 跑一次续期 → 再查 MSAL 缓存里有没有 RT → 最后才是 `ping` 埋点。
14. **个人版 `method:null` 挑战多一条外部事实**：`sums001`（MIT，1237★）抓真实网页客户端，看到它用 `method:"cloudflare"` 的 Turnstile token 回这个帧，并断言它只在 `cf_clearance` 过期时出现。我们 08-12 的结论（无 token 可过、不要重铸凭据）在**行为上与它一致**，但它给出了「为什么无解」的机制。我们的 Camoufox 路径理论上能取 Turnstile token —— 是否值得做取决于这个帧在生产里的频率，目前未量。


## 当前判断

- 当前项目不需要换仓，也不需要跨用户账号调度。本轮（09-14）也没有任何一行外部代码被搬进来。
- Copilot Studio 两次独立实验各出现 1 次失败（97%），Router 两次 100%，因此不能默认替换 Router；但 180 秒超时未复现，说明那是波动而非固有缺陷。
- Studio 的延迟优势可复现：正式配对中位快 3636 ms、复测快 4347 ms，值得保留为单人单账号的显式低延迟实验备选，且已在 OpenAI / Anthropic / Responses 三协议（流式与非流式、含工具闭环）实测通过。
- jairbj 式动态协议 profile 已落地为 `protocol_profile.py` + 抓包捕获，可 apply/rollback；usage 与首页调用占比圆环已实测有数据。
- 最值得长期补充的是官方 Graph Provider；缓冲流的 SSE preamble/保活已落地，统一断连和写超时仍待补齐。
- 任何候选都不能原样公网部署；必须保留当前项目的下游鉴权、用户隔离、凭据加密和媒体 SSRF 防护。
- 本轮（09-11）唯一可采纳的新仓是 `MasayukiTa/m365-copilot-companion-mcp`（MIT，独立实现）；它的抓包驱动做法印证了我们大部分帧处理，并挖出上面的缺口二。
- 09-14 新增三个可采纳仓：`kdeps/kdeps`（Apache-2.0，37★，独立实现，推理转录已落地）、`artlovan/copilot_cowork_mcp`（MIT，独立实现，Cowork 三个未知项全部答上）、`chrischall/opencode-copilot-plugin`（MIT，仅致谢 cramt，读同一批 throttling 字段）。`uefi233/m365-copilot-gateway` 虽为 Apache-2.0 且只在文档/docstring 里引用 HEXUXIU（无代码痕迹），但其 variants/optionsSets 是我们的严格子集，没有可拿的东西。
- `microsoft/PyRIT`（MIT，4465★，微软自家）里有一个 substrate ChatHub target：这是**微软自己**发布的参考载荷形状，可用于核对；但它的认证是 Playwright + 账号密码，属于我们已判的停损形态，只取载荷不取认证。
- 发现了一个我们从未记录的第二上游面（M365 Copilot Cowork，Power Apps runtime + SSE + gzip 事件）；**09-14 已实测确认本账号有 Cowork 权限**（runtime host `/v1/models` 200，3 个模型），token 用现成的 `mint_scoped_token` 就能签出，不需要浏览器或新凭据。它现在是**一个真正可做的第二 Provider 候选**，而不是协议知识；剩下的唯一动作是一次会写状态的真实对话（`POST /v1/subscribe`），需单独决定。
- **一条对旧结论的补充（不是推翻）：** `gpt-5.6-sol` / `gpt-5.6-terra` 在 2026-08-28 按 substrate **tone** 探测时 12 种拼法全部「empty response twice」（`tone_options.py:14-22`），当时记为「本租户不存在」。现在知道它们是 **Cowork 的 model id**（`/v1/models` 直接列出），不是 substrate tone —— 所以那条记录是对的（作为 tone 确实不存在），但「这些名字在别人租户能用」的传闻也有了解释：说的是另一个上游面。不要因此把它们加回 `TONE_OPTIONS`。
- 个人版这一面本轮才第一次按同样标准扫（此前六轮都只扫工作/学校版）。两个 MIT 独立实现（`atomic-reactor/msco-pi-lot`、`badafans/copilot2api`）逐帧印证了我们的 `consumer_client.py`，没有一条可搬代码；但它们暴露出两处差异：我们不回 `ping`/`pong`（因果未建立，见待办 13），以及 `method:null` 挑战的机制解释（见待办 14）。`sums001/Windows-Copilot-API` 的 1237★ 说明这一面的关注度远高于工作版，值得每轮都扫。
- `protella/chatgpt-bots`（MIT）的工具循环不变量可直接用于待办 5，含一条它自己的更正（强制单轮时要关掉 empty-final 兜底）。**其中「上限必须在 dispatch 之前生效」这条我们至今没接线**，见待办 11。
