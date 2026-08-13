# Consumer 个人版提示词预算实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 Consumer 个人版增加工具感知的 8,000 字符默认预算，保持 M365 完全不变。

**架构：** translator 仅在 Consumer 请求下生成独立、紧凑的工具合同；`ConsumerClientAdapter` 是三条 API 的统一最终压缩点。配置通过依赖注入只进入 Consumer adapter，不修改共享 `_combine_text()`。

**技术栈：** Python 3.11、FastAPI、Pydantic Settings、pytest。

---

### 任务 1：锁定 Consumer 最终预算行为

**文件：**
- 修改：`tests/test_consumer_adapter.py`

- [ ] 添加未超限逐字保持、严格总长度、当前 prompt、最近 transcript/tool result、system 首尾和中文字符计数测试。
- [ ] 运行 `pytest tests/test_consumer_adapter.py -q`，确认新增测试因预算功能缺失而失败。

### 任务 2：实现 Consumer 统一压缩点

**文件：**
- 创建：`src/m365_copilot_openai_proxy/consumer_prompt.py`
- 修改：`src/m365_copilot_openai_proxy/consumer_adapter.py`
- 修改：`src/m365_copilot_openai_proxy/config.py`
- 修改：`src/m365_copilot_openai_proxy/dependencies.py`

- [ ] 实现纯函数 `compact_consumer_prompt(prompt, context, max_chars)`，按工具合同、当前 prompt、最近 transcript、system 的顺序分配预算。
- [ ] 让 adapter 的流式和非流式路径共用该函数。
- [ ] 增加 `CONSUMER_PROMPT_MAX_CHARS=8000` 设置并只注入 Consumer adapter。
- [ ] 运行 `pytest tests/test_consumer_adapter.py -q`，确认任务 1 测试转绿。

### 任务 3：生成紧凑但完整的 Consumer 工具合同

**文件：**
- 修改：`src/m365_copilot_openai_proxy/translator.py`
- 修改：`src/m365_copilot_openai_proxy/routes_api_chat.py`
- 修改：`src/m365_copilot_openai_proxy/routes_api_messages.py`
- 测试：`tests/test_anthropic_tool_calls.py`
- 测试：`tests/test_tool_choice.py`

- [ ] 添加失败测试：Consumer 合同保留所有工具名、参数名、类型、required，并受独立预算限制；M365 完整提示保持原样。
- [ ] 运行定向测试确认红灯。
- [ ] 为 OpenAI/Anthropic translator 增加可选 Consumer 工具预算，生成独立 `Tool calling contract:` context。
- [ ] 路由仅在 `is_consumer` 时传入预算；M365 传 `None`。
- [ ] 运行定向测试确认绿灯。

### 任务 4：覆盖三条 Provider 路径

**文件：**
- 修改：`tests/test_provider_model_selection.py`

- [ ] 为 Chat Completions、Messages、Responses 添加长输入 Consumer 参数化测试，断言上游收到的最终文本不超过设置值且保留当前用户哨兵。
- [ ] 添加 M365 长输入回归，断言未被裁剪。
- [ ] 运行 `pytest tests/test_provider_model_selection.py -q` 并修复任何路径差异。

### 任务 5：验证和真实协议复测

**文件：**
- 不新增生产文件。

- [ ] 运行 Consumer/translator/routes 定向测试。
- [ ] 运行完整 `pytest -q`。
- [ ] 运行 `node --check get_token.user.js` 和 `git diff --check`。
- [ ] 构建部署后，在目标容器内以 Claude Code 风格带工具请求复测，确认不再发送超长 text part，并收到正文或 `tool_use` 与 `message_stop`。
