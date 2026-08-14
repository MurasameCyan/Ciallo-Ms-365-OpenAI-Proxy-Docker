# Responses Function Tools 实现计划

> **面向 AI 代理的工作者：** 在当前会话按 TDD 执行；每个行为先写失败测试，再写最少实现。

**目标：** 支持 OpenAI SDK 与 Codex 的 Responses function-tool 客户端循环；适配 Codex `namespace` 工具容器，要求以顶层 `web_search = "disabled"` 禁用不受支持的 Web Search，并对其他无法由微软上游承载的工具明确返回 `400`。

**架构：** 将 Responses 的扁平 function tool 定义和 `namespace` 内嵌 function 统一适配为项目现有工具契约，复用已有 tool choice、Consumer 压缩和 tool-call 解析逻辑。微软上游只接收裸函数名，因此 namespace 子函数名必须无歧义；路由在输出 `function_call` 时恢复 namespace 元数据。工具执行结果通过 `function_call_output` input item 回传并进入下一轮上下文。流式路径先发 `response.created`，缓冲上游回合后再发文本或 function-call 生命周期事件。

**技术栈：** FastAPI、Pydantic、pytest、现有 `tool_call_parser` 与 Consumer/M365 客户端适配层。

---

### 任务 1：请求模型与输入转换

**文件：**
- 修改：`src/m365_copilot_openai_proxy/models.py`
- 修改：`src/m365_copilot_openai_proxy/translator.py`
- 测试：`tests/test_responses_tools.py`

- [x] 测试 Responses 扁平 function tool 会注入现有工具契约。
- [x] 测试 `tool_choice=none` 会同时禁用契约与响应解析。
- [x] 测试 `function_call` 与 `function_call_output` 被写入上下文，末项工具结果会生成续轮 prompt。
- [x] 测试非 function 工具在触达上游前返回明确 `400`。
- [x] 用 Codex 0.145.0 请求形状回归 `function`、`namespace`、`web_search` 三种工具类型。
- [x] 展平 `namespace` 内的 function tools，保留输出与续轮 namespace，并拒绝畸形、重名或包含其他工具类型的 namespace。
- [x] 验证顶层 `web_search="disabled"` 后 Codex 请求不再携带 `web_search`；`tools.web_search=false` 不作为兼容开关。

### 任务 2：非流式 function_call 输出

**文件：**
- 修改：`src/m365_copilot_openai_proxy/routes_api_responses.py`
- 测试：`tests/test_responses_tools.py`

- [x] 测试上游 fenced tool call 转换为 Responses `function_call` output item。
- [x] 测试 prose 与 function call 可同时输出，工具 fence 不泄漏。
- [x] 测试声明工具集合和基于名称白名单的只读过滤。
- [x] 测试普通文本响应维持 message/output_text 结构。

### 任务 3：流式 function_call 生命周期

**文件：**
- 修改：`src/m365_copilot_openai_proxy/response_helpers.py`
- 修改：`src/m365_copilot_openai_proxy/routes_api_responses.py`
- 测试：`tests/test_responses_tools.py`
- 测试：`tests/test_responses_stream_failed.py`

- [x] 测试 function call 事件包含 `response.output_item.added`、`response.function_call_arguments.delta`、`response.function_call_arguments.done`、`response.output_item.done` 和 `response.completed`。
- [x] 测试文本事件补齐 `response.content_part.done` 与 `response.output_item.done`。
- [x] 测试事件带单调递增 `sequence_number`，且 Responses 流不发送 `[DONE]`。
- [x] 测试上游错误仍以 `error` + `response.failed` 正常终止。

### 任务 4：验证与文档

**文件：**
- 修改：`README.md`

- [x] 使用真实 Codex CLI 完成 namespace `function_call → function_call_output → 最终 message` 循环。
- [x] 运行 Responses 定向测试。
- [x] 运行工具链与 provider 回归测试。
- [x] 运行完整 pytest、Python 编译和 `git diff --check`。
- [x] README 明确 namespace 行为、Codex Web Search 禁用方式、只读过滤边界、托管工具返回 `400`，以及 Consumer `resp_...` 不是续接句柄。

实现边界：`strict:true` 在代理侧按 JSON Schema 校验模型返回参数，但 Microsoft 上游没有原生 schema 强制。M365 `previous_response_id` 只允许最新 ID 的单次线性续接，不提供丢帧后的幂等重放；并行调用结果必须一次全部提交。响应中的 `tool_choice` 始终回显规范化值，保证官方 SDK 可解析。
