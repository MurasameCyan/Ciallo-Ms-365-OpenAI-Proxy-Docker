# Consumer 个人版提示词预算设计

## 背景与证据

Consumer Copilot 通过单个 WebSocket text part 接收完整提示词。Claude Code 请求会把 system、工具定义、历史和当前问题全部带入；现有 Consumer adapter 每轮完整重发，实测 56,020 字符被上游以 `text-too-long` 拒绝。

2026-08-14 在目标容器、同一 Consumer 账号和同一流式路径做阶梯探测：4,000、6,000、8,000、10,000 字符成功，12,000 字符返回 `text-too-long`。因此采用可配置的 8,000 字符默认预算，给格式差异和上游波动留余量。该结论只适用于 Consumer；M365 已验证不存在同类字符上限，本设计不改变 M365。

## 目标

- 仅限制 Consumer 最终发送的文本，覆盖 Chat Completions、Anthropic Messages、Responses，以及流式和非流式调用。
- 保留当前用户请求、最新工具结果、所有客户端声明的工具名称和参数签名。
- 压缩冗长工具描述、旧历史和重复工具协议。
- 最终 Consumer text part 严格不超过配置预算。
- M365 翻译、`_combine_text()`、持续会话和工具提示行为保持不变。

## 非目标

- 不为 M365 增加输入预算。
- 不在本阶段增加 Consumer `conversation_id` 缓存。
- 不猜测精确、永久的 Microsoft 字符上限。
- 不删除客户端声明的工具，也不按“常用工具”静默筛选。
- 不在本补丁中改变工具返回名称校验；该安全加固另行处理。

## 设计

### Provider 隔离

`Settings` 增加 `CONSUMER_PROMPT_MAX_CHARS`，默认 8,000。`dependencies.py` 仅在 `account.provider == "consumer"` 时把该值传给 `ConsumerClientAdapter`。M365 继续直接使用 `SubstrateCopilotClient`。

### Consumer 工具合同

OpenAI 与 Anthropic translator 增加可选的 Consumer 工具预算参数：

- 参数为空时生成现有完整工具提示，保证 M365 原样。
- 参数存在时生成 Consumer 专用紧凑合同，并作为独立 context part 输出。
- 所有工具名称、顶层参数名称、类型和 required 标记必须保留。
- 删除 description、example、title、default 等非执行必需字段；若仅必需签名已超预算，返回明确 HTTP 400，不静默删除工具。
- Consumer 合同明确说明模型不执行工具，只输出 `tool_call` JSON，由客户端执行。
- Consumer adapter 不再追加 M365 专用、语义重复的 `[FORMAT]` 长段落。

### 最终文本压缩

压缩只发生在 `ConsumerClientAdapter.chat_stream()`，非流式 `chat()` 自动复用同一路径。输入仍是当前 `prompt` 与分段 `additional_context`。

优先级：

1. Consumer 工具合同：完整保留。
2. 当前 prompt：完整保留；单条本身超限时才采用带标记的首尾截断。
3. 最近 transcript：从尾部保留，确保最新 `tool_result` 优先。
4. system instructions：用首尾保留方式使用剩余预算。
5. 更早历史和冗长说明最先丢弃。

压缩器完成后重新计算最终拼接长度，保证 `len(text) <= max_chars`。字符口径与上游日志一致，使用 Python `len(str)`，不是 token 数。

## 错误行为

- Consumer 工具的必需签名本身超过工具预算：在调用上游前返回清晰的请求错误。
- 配置预算过小：应用配置校验失败，不启动一个必然破坏工具协议的实例。
- 上游仍返回 `text-too-long`：沿用已经修复的可见错误正文，不隐藏或自动重试。

## 测试与验收

- Consumer 未超限请求拼接结果保持不变。
- Consumer 超限请求严格小于等于预算，并保留当前问题哨兵。
- 最近 `tool_result` 保留、旧历史被裁剪。
- 工具请求保留所有名称、参数名、类型和 required，且不包含重复 `[FORMAT]`。
- 工具必需签名超预算时明确失败。
- Chat、Messages、Responses 三条 Consumer 路径统一受限。
- 相同长请求走 M365 fake client 时保持完整，证明 Provider 隔离。
- 全量 pytest、JS 语法和 diff 检查通过。
