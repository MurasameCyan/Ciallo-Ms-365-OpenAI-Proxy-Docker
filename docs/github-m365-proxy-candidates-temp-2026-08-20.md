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


## 后续顺序

1. Copilot Studio 账号级显式实验模式已实现，正式 A/B + 一次复测完成，三协议全链路实测通过；Router 继续默认，不自动推广 Studio。
2. 统一三协议的 write deadline/客户端断连释放测试，并覆盖 Studio fallback 的取消路径。
3. 下一候选：若租户具备所需权限，验证官方 Graph chatOverStream Provider。
4. usage 从 `estimated` 升级为带 `token_source`，精确计数放可选开关。
5. 工具调用卫生：tool_call id 唯一性、孤立 tool_result 拒绝、单轮工具轮数上限。
6. 需要补协议测试时，再从 sideeffffect 和 kuchris 提取可验证的测试思路。
7. 推理转录已确认在线（2026-09-01），可选做：渲染成 Anthropic `thinking` 块与 OpenAI `reasoning_content`。要动三个协议渲染器，收益是把现在丢掉的转录变成可见的推理过程。
8. `stop` / `stop_sequences` **已完成**（2026-09-11，见上）。剩 `/v1/responses` 有意未接（该 API 无此参数）。
9. `deepResearchModels`：要么补值（Studio 路径选 Researcher 模型），要么删掉那条无值的 `@odata.type` 注解。上线前必须本账号实测。
10. Cowork（`mcsaetherruntime-*.gateway.prod.island.powerapps.com`）是第二个上游面，协议已记录；先确认本账号有无权限，再谈是否值得做 Provider。

## 当前判断

- 当前项目不需要换仓，也不需要跨用户账号调度。
- Copilot Studio 两次独立实验各出现 1 次失败（97%），Router 两次 100%，因此不能默认替换 Router；但 180 秒超时未复现，说明那是波动而非固有缺陷。
- Studio 的延迟优势可复现：正式配对中位快 3636 ms、复测快 4347 ms，值得保留为单人单账号的显式低延迟实验备选，且已在 OpenAI / Anthropic / Responses 三协议（流式与非流式、含工具闭环）实测通过。
- jairbj 式动态协议 profile 已落地为 `protocol_profile.py` + 抓包捕获，可 apply/rollback；usage 与首页调用占比圆环已实测有数据。
- 最值得长期补充的是官方 Graph Provider；缓冲流的 SSE preamble/保活已落地，统一断连和写超时仍待补齐。
- 任何候选都不能原样公网部署；必须保留当前项目的下游鉴权、用户隔离、凭据加密和媒体 SSRF 防护。
- 本轮唯一可采纳的新仓是 `MasayukiTa/m365-copilot-companion-mcp`（MIT，独立实现）；它的抓包驱动做法印证了我们大部分帧处理，并挖出上面的缺口二。
- 发现了一个我们从未记录的第二上游面（M365 Copilot Cowork，Power Apps runtime + SSE + gzip 事件），但本账号权限未测，暂不构成候选。
- `protella/chatgpt-bots`（MIT）的工具循环不变量可直接用于待办 5，含一条它自己的更正（强制单轮时要关掉 empty-final 兜底）。
