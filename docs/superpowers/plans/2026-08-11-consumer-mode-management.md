# Consumer Copilot 独立模型与 Mode 管理实现计划

> **执行说明：** 按任务顺序实施；每个任务先写失败测试，再完成最小实现。文中的提交步骤是建议检查点，只有用户明确授权提交时才执行。当前 `fox` 分支已有未提交 WIP：保留其中正确的 Consumer `mode` wire 传递方向，但以批准规格和新测试为准纠正宽松校验、静态映射及 `smart` fallback。不要暂存或提交无关的 `.superpowers/`。

**目标：** 为 Consumer Copilot 建立严格、可持久化、可热更新且 Provider-aware 的 model → mode 管理，同时保持 M365 tone、模型目录、持续会话和错误协议不变。

**架构：** `runtime_settings.py` 是 Consumer 内置目录与配置标准化的唯一持久化边界；`app.state.consumer_mode_options` 是请求期 resolver 与 `/v1/models` 共用的唯一 live 事实源。API Key 绑定账户的 `account.provider` 是唯一 Provider 判定来源。三条兼容路由先使用共享 resolver 校验模型，再创建对应上游 client；Consumer adapter 负责 mode 传递和 experimental 错误提示，不新增基于错误字符串的 mode-rejection 分类器。

**技术栈：** Python、FastAPI、Pydantic、pytest、curl-cffi、内嵌 HTML/JavaScript、Node.js `--check`

**规格来源：** `docs/superpowers/specs/2026-08-11-consumer-mode-management-design.md`

---

## 任务 1：严格定义 Consumer 配置规范

**文件：**

- 修改：`src/m365_copilot_openai_proxy/runtime_settings.py`
- 重写 WIP 测试：`tests/test_consumer_mode_options.py`

- [ ] **步骤 1：把 WIP 测试改成批准规格要求的红灯测试**

在 `tests/test_consumer_mode_options.py` 中把 `_DEFAULT_OPTIONS` 改为精确的 11 项三字段列表，顺序不得改变：

```python
_DEFAULT_OPTIONS = [
    {"model": "copilot", "mode": "smart", "status": "stable"},
    {"model": "copilot-smart", "mode": "smart", "status": "stable"},
    {"model": "copilot-reasoning", "mode": "reasoning", "status": "experimental"},
    {"model": "copilot-thinking", "mode": "reasoning", "status": "experimental"},
    {"model": "copilot-search", "mode": "search", "status": "experimental"},
    {"model": "copilot-study", "mode": "study", "status": "experimental"},
    {"model": "copilot-chat", "mode": "chat", "status": "experimental"},
    {"model": "copilot-default", "mode": "default", "status": "experimental"},
    {"model": "copilot-research", "mode": "research", "status": "experimental"},
    {"model": "copilot-computer-use", "mode": "computer_use", "status": "experimental"},
    {"model": "copilot-coco", "mode": "coco", "status": "experimental"},
]
```

将当前两个宽松测试替换为以下测试函数：

- `test_consumer_mode_defaults_are_canonical`
- `test_consumer_mode_normalizer_accepts_three_column_text_and_json`
- `test_consumer_mode_normalizer_migrates_two_column_entries`
- `test_consumer_mode_normalizer_normalizes_model_and_status_but_preserves_mode`
- `test_consumer_mode_normalizer_allows_multiple_models_for_one_mode`
- `test_consumer_mode_normalizer_empty_list_restores_defaults`
- `test_consumer_mode_normalizer_rejects_invalid_top_level_types`
- `test_consumer_mode_normalizer_rejects_blank_text_and_bad_column_counts`
- `test_consumer_mode_normalizer_rejects_invalid_entries_and_field_types`
- `test_consumer_mode_normalizer_rejects_blank_fields_invalid_status_and_duplicate_models`
- `test_consumer_mode_normalizer_rejects_field_and_entry_limits`

关键断言：

- 文本三列和对象三字段都输出完整的 `model`、`mode`、`status`。
- 两列输入中，trim 后的 `mode == "smart"` 补 `stable`，其他 mode 补 `experimental`。
- `model`、`status` 执行 `strip + lowercase`；`mode` 只执行 `strip`，大小写和内容保持原样。
- 同一 mode 可对应多个不同 model。
- 只有 `[]` 恢复内置默认；`""`、纯空白字符串、`None`、数字、对象均抛 `ValueError`。
- 文本每个非空行必须恰好 2 或 3 列。
- 列表项必须是对象；`model`、`mode` 和显式提供的 `status` 必须是字符串。
- 未知额外对象键可以忽略，但标准输出只保留三个字段。
- 空 model、空 mode、未知 status、标准化后重复 model 均整单失败。
- 任一字段 81 字符或第 41 项都报错，不截断、不保留有效子集。
- 错误信息包含 1-based `line N` 或 `entry N` 及具体原因。

- [ ] **步骤 2：运行测试确认红灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_mode_options.py" -q
```

预期：FAIL。当前默认目录只有 6 项且没有 `status`；无效、重复和超限输入被静默过滤或截断，多个 `pytest.raises(ValueError)` 报 `DID NOT RAISE`。

- [ ] **步骤 3：实现最小严格 normalizer**

只修改现有 `_BUILTIN_CONSUMER_MODE_OPTIONS` 和 `normalize_consumer_mode_options()`：

1. 将内置目录替换为上述固定 11 项三字段列表。
2. 顶层只接受 `str` 或 `list`；其他类型抛 `ValueError`。
3. 文本忽略空白行；若没有非空行则报错。
4. 每个非空文本行必须恰好 2/3 列，位置使用 1-based `line N`。
5. 列表位置使用 1-based `entry N`；列表项必须是 `dict`。
6. `model`、`mode` 必须存在且为字符串；显式 `status` 必须为字符串。
7. 缺省 status 根据 trim 后的 mode 精确迁移：`smart → stable`，其他 → `experimental`。
8. 标准化后检查空值、80 字符上限、status 枚举和重复 model。
9. 超过 40 项立即整单失败。
10. `[]` 返回内置默认条目的新副本；其他空输入报错。
11. 首个错误即抛 `ValueError`，不返回部分结果。

使用稳定、可定位的错误格式，例如：

```text
consumer_mode_options line 2: expected 2 or 3 pipe-separated columns
consumer_mode_options entry 3: model must be a string
consumer_mode_options entry 4: mode must not be empty
consumer_mode_options entry 5: status must be stable or experimental
consumer_mode_options entry 6: duplicate model 'copilot'
consumer_mode_options: maximum 40 entries
```

不要修改 `normalize_tone_options()`、`tone_options.py` 或 `tone_resolver.py`。

- [ ] **步骤 4：运行测试确认绿灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_mode_options.py" -q
```

预期：PASS。

- [ ] **步骤 5：提交本任务**

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" add -- \
  src/m365_copilot_openai_proxy/runtime_settings.py \
  tests/test_consumer_mode_options.py
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" commit -m "feat(consumer): 严格规范化模型 mode 配置"
```

---

## 任务 2：损坏持久化回退并发布启动 live state

**文件：**

- 修改：`src/m365_copilot_openai_proxy/runtime_settings.py`
- 修改：`src/m365_copilot_openai_proxy/state_init.py`
- 测试：`tests/test_consumer_mode_options.py`
- 测试：`tests/test_state_init_split.py`

- [ ] **步骤 1：编写持久化与启动状态红灯测试**

在 `tests/test_consumer_mode_options.py` 新增：

- `test_read_runtime_settings_migrates_legacy_consumer_modes`
  - 向 `runtime_settings.json` 写入合法两字段 Consumer 列表。
  - 调用 `_read_runtime_settings(str(tmp_path))`。
  - 断言加载结果补齐完整 status。

- `test_read_runtime_settings_falls_back_whole_consumer_field_and_warns`
  - 参数化损坏字段：错误顶层对象、mode 为空、status 非法、一个合法项与一个非法项混合。
  - 同一 JSON 中写入合法 `model_alias="preserved-alias"`。
  - 使用 `caplog.at_level(logging.WARNING)`。
  - 断言 Consumer 字段完整回退 11 项，不保留混合列表中的有效子集。
  - 断言 `model_alias` 仍为 `preserved-alias`。
  - 断言 warning 包含 `consumer_mode_options` 和具体失败原因。

在 `tests/test_state_init_split.py` 新增 `test_init_app_state_exposes_loaded_consumer_mode_options`：

1. 预写合法 `runtime_settings.json`，含自定义三字段 Consumer 列表。
2. 调用 `init_app_state()`。
3. 断言：

```python
assert app.state.runtime_settings["consumer_mode_options"] == expected
assert app.state.consumer_mode_options == expected
```

- [ ] **步骤 2：运行测试确认红灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_mode_options.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_state_init_split.py" -q
```

预期：FAIL。严格 normalizer 会让损坏 Consumer 字段阻止启动，并且 `app.state.consumer_mode_options` 尚未发布。

- [ ] **步骤 3：实现整字段加载回退**

在 `runtime_settings.py` 增加模块 logger，并仅包裹 Consumer 字段的加载：

```python
try:
    data["consumer_mode_options"] = normalize_consumer_mode_options(
        data.get("consumer_mode_options")
    )
except ValueError as exc:
    _log.warning(
        "Invalid persisted consumer_mode_options; using built-in defaults: %s",
        exc,
    )
    data["consumer_mode_options"] = [
        dict(option) for option in _BUILTIN_CONSUMER_MODE_OPTIONS
    ]
```

要求：

- Consumer 字段损坏不阻止应用启动。
- 其他合法运行设置继续按现有路径加载。
- 不保留 Consumer 有效子集。
- 不扩大为整个 runtime settings 的异常吞掉或重构。

在 `state_init.init_app_state()` 的 `app.state.tone_options` 附近增加：

```python
app.state.consumer_mode_options = runtime_settings["consumer_mode_options"]
```

- [ ] **步骤 4：运行测试确认绿灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_mode_options.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_state_init_split.py" -q
```

预期：PASS。

- [ ] **步骤 5：提交本任务**

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" add -- \
  src/m365_copilot_openai_proxy/runtime_settings.py \
  src/m365_copilot_openai_proxy/state_init.py \
  tests/test_consumer_mode_options.py \
  tests/test_state_init_split.py
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" commit -m "fix(settings): 损坏个人版 mode 配置整字段回退"
```

---

## 任务 3：Admin POST 严格校验且失败无副作用

**文件：**

- 修改：`src/m365_copilot_openai_proxy/routes_admin_settings.py`
- 重写 WIP 测试：`tests/test_admin_settings_routes_split.py`

- [ ] **步骤 1：重写成功契约并增加原子失败测试**

将当前 `test_runtime_settings_saves_live_consumer_mode_options` 的无效、重复两字段输入改为合法三字段输入，断言：

- HTTP 200。
- 响应返回标准三字段结构。
- `app.state.runtime_settings["consumer_mode_options"]` 与 `app.state.consumer_mode_options` 均立即更新。
- 用同一 token dir 新建 app 后恢复相同列表。

新增 `test_runtime_settings_rejects_invalid_consumer_modes_without_side_effects`：

1. 先成功 POST 一份基线 Consumer 配置，使 `runtime_settings.json` 存在。
2. 保存：
   - 文件原始 bytes。
   - `app.state.runtime_settings` 对象引用。
   - `app.state.consumer_mode_options` 对象引用。
   - `app.state.model_alias` 当前值。
3. 再 POST：

```python
{
    "model_alias": "must-not-apply",
    "consumer_mode_options": "ok | smart | stable\nbad | | experimental",
}
```

4. 断言 HTTP 400，`response.json()["error"]["message"]` 包含 `line 2` 与 `mode must not be empty`。
5. 断言文件 bytes 完全相同。
6. 断言两个 state 对象引用均未替换，`model_alias` 未改变。

新增 `test_runtime_settings_reset_lists_are_independent`：

1. 保存自定义 M365 tone 和自定义 Consumer mode。
2. POST `{"consumer_mode_options": []}`，断言 Consumer 恢复 11 项默认，M365 tone 保持自定义值。
3. 再保存自定义 Consumer mode。
4. POST `{"tone_options": []}`，断言 M365 恢复默认，Consumer 保持自定义值。

- [ ] **步骤 2：运行测试确认红灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_admin_settings_routes_split.py" -q
```

预期：FAIL。当前 POST 未处理 Consumer 字段，不会返回可定位 400，也不会发布 live Consumer state。

- [ ] **步骤 3：在所有副作用前完成 Consumer 校验**

在 `routes_admin_settings.py`：

1. 导入 `normalize_consumer_mode_options`。
2. 在构建 `data` 时调用：

```python
"consumer_mode_options": normalize_consumer_mode_options(
    body.get("consumer_mode_options", current.get("consumer_mode_options"))
),
```

3. 用 `try/except ValueError` 包住数据解析与既有字段校验，失败时直接：

```python
return _json_err(400, str(exc), "validation_error")
```

4. 保证 Consumer normalizer、log level、run permission 和 proxy 校验都发生在任何以下副作用之前：
   - 替换 `app.state.runtime_settings`。
   - 修改其他 `app.state` 字段。
   - 调度器参数更新。
   - `apply_proxy_env()`。
   - `_set_log_flags()`。
   - `_write_runtime_settings()`。
5. 成功路径在 `app.state.tone_options` 附近增加：

```python
app.state.consumer_mode_options = data["consumer_mode_options"]
```

6. 继续用既有 `_write_runtime_settings()` 持久化完整 `data`。
7. 不实现写盘 I/O 失败或后续副作用异常的全事务回滚；该行为不在批准规格范围内。

- [ ] **步骤 4：运行聚焦与邻接回归测试**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_admin_settings_routes_split.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_outbound_proxy.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_rate_limit_middleware.py" -q
```

预期：PASS，proxy、rate-limit 和 runtime flag 行为无回归。

- [ ] **步骤 5：提交本任务**

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" add -- \
  src/m365_copilot_openai_proxy/routes_admin_settings.py \
  tests/test_admin_settings_routes_split.py
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" commit -m "feat(admin): 原子保存个人版 mode 配置"
```

---

## 任务 4：共享 Provider-aware resolver、三路会话隔离与 live 模型目录

**文件：**

- 修改：`src/m365_copilot_openai_proxy/routes_api_common.py`
- 修改：`src/m365_copilot_openai_proxy/routes_api_chat.py`
- 修改：`src/m365_copilot_openai_proxy/routes_api_messages.py`
- 修改：`src/m365_copilot_openai_proxy/routes_api_responses.py`
- 保留并校正 WIP：`src/m365_copilot_openai_proxy/consumer_adapter.py`
- 保留并校正 WIP：`src/m365_copilot_openai_proxy/consumer_client.py`
- 重写 WIP 测试：`tests/test_provider_model_selection.py`
- 修改测试：`tests/test_consumer_curl.py`

- [ ] **步骤 1：把 fallback 测试改成严格未知模型契约**

在 `tests/test_provider_model_selection.py` 删除 `test_unknown_consumer_model_falls_back_to_smart`，重写/新增：

- `test_consumer_routes_apply_live_model_mode_without_m365_session`
  - 参数化 `/v1/chat/completions`、`/v1/messages`、`/v1/responses`。
  - 使用 live 配置中的自定义 model，request model 带两端空白及不同大小写。
  - 断言三路均设置相同 mode。
  - monkeypatch 各路由模块已经导入的 `_persistent_session` 为一旦调用就失败的 spy，证明 Consumer 完全不进入 M365 session helper。

- `test_unknown_consumer_model_is_rejected_before_client_creation`
  - 三路参数化。
  - 请求未知 model。
  - 断言 HTTP 400。
  - 错误详情包含用户原始 model 和当前 live 配置中的全部 model ID。
  - 断言 Consumer factory 记录仍为空。

- `test_provider_is_selected_from_bound_account_not_model_name`
  - Consumer Key 请求 M365 风格 model，仍只在 Consumer 表中查找并返回 400。
  - M365 Key 请求 Consumer facade model，仍走 M365 resolver 的既有默认 tone 行为。
  - 全局 Key或开放模式继续走 M365。

- `test_m365_routes_still_apply_model_as_tone_and_session`
  - 三路参数化。
  - 断言 M365 client `_tone` 正确。
  - monkeypatch `_persistent_session` 记录调用，断言 M365 路径仍调用它。
  - 不设置 Consumer `mode`。

- `test_models_list_is_provider_specific_and_live`
  - Consumer live 配置含三个 model，其中两个映射同一个 mode。
  - 断言按配置顺序返回三个 ID。
  - 断言不返回 `status`、`-持续`、`:persist` 或 M365 ID。
  - 断言 `owned_by == "microsoft-copilot"`。
  - M365 Key 仍返回 tone 目录及 `-持续` 变体。
  - 全局 Key或开放模式仍返回 M365 目录。

- `test_model_alias_only_changes_response_display`
  - 设置 `app.state.model_alias="display-only"`。
  - 断言响应对象 `model` 为 alias。
  - 断言上游 mode 仍来自 request model。
  - 断言 `/v1/models` 继续显示配置 model ID，不显示 alias。

保留并加强 `test_substrate_payload_keeps_using_tone`。

在 `tests/test_consumer_curl.py::test_send_frame_uses_the_selected_consumer_mode` 增加：

```python
send_frame = sessions[0].socket.sent[-1]
assert send_frame["mode"] == "reasoning"
assert "tone" not in send_frame
assert "toneId" not in send_frame
```

- [ ] **步骤 2：运行测试确认红灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_provider_model_selection.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_curl.py::test_send_frame_uses_the_selected_consumer_mode" -q
```

预期：FAIL。当前 resolver 仍使用静态六项表，未知 model 回退 `smart`，client 由 FastAPI dependency 在 handler 前创建，三路无条件调用 `_persistent_session()`，Consumer 模型目录不读取 live state。

- [ ] **步骤 3：将共享 selector 改为“先解析，再建 client”**

在 `routes_api_common.py`：

1. 删除 `_CONSUMER_MODEL_MODES`。
2. 从 `runtime_settings.py` 导入 `_BUILTIN_CONSUMER_MODE_OPTIONS` 作为仅初始化缺失时的 fallback。
3. 将 `apply_request_model()` 改为：

```python
def apply_request_model(
    app: FastAPI,
    raw_request: Request,
    client_factory: Callable[[Request], object],
    model_str: str | None,
) -> tuple[object, str, bool]:
    """Return (configured_client, upstream_value, is_consumer)."""
```

Consumer 分支：

1. 只根据 `raw_request.state.account.provider == "consumer"` 分流。
2. 从 `app.state.consumer_mode_options` 读取 live 列表；仅属性缺失或为空时回退内置 11 项。
3. 请求 key 为 `(model_str or "").strip().lower()`。
4. 按标准化 model 精确查找，不解析 `-持续` 或 `:persist`。
5. 未找到时抛 `ValueError`，错误包含 `model_str` 原始值和按 live 顺序列出的所有 model ID。
6. 只有查找成功后才调用 `client_factory(raw_request)`。
7. 设置 `client.mode = option["mode"]`。
8. 返回 `(client, option["mode"], True)`。

M365 分支：

1. 保持 `resolve_request_tone()` 原行为。
2. resolver 成功后调用 `client_factory(raw_request)`。
3. 设置 `client._tone = tone`。
4. 返回 `(client, tone, False)`。

不要让 `model_alias` 参与查表。

- [ ] **步骤 4：三条路由惰性创建 client 并隔离 Consumer session**

在三个 handler 中移除：

```python
client: SubstrateCopilotClient = Depends(get_copilot_client)
```

保留 route registration 闭包中的 `get_copilot_client` callable，并统一调用：

```python
client, resolved_value, is_consumer = apply_request_model(
    app, raw_request, get_copilot_client, request.model
)
```

随后仅在 M365 分支计算 session：

```python
session = None
if not is_consumer:
    session = _persistent_session(
        app,
        raw_request,
        normalized_session_model(request.model),
        session_key,
        request_if_applicable,
    )
```

要求：

- Consumer 分支不调用 `_persistent_session()`、`normalized_session_model()`、`_messages_session_key()`、`_responses_session_key()` 或 `_encode_responses_session_id()` 来创建 M365 会话状态。
- Responses 的 Consumer `resp_id` 继续生成普通随机 `resp_...`；只在 M365 session key 存在时编码 session ID。
- M365 的自动 session、`-持续` 和 `:persist` 行为保持不变。
- 三路既有 `except ValueError → HTTP 400` 继续提供一致错误。
- 将局部变量和 call log 的含义改为中性的 `resolved_value`；若为兼容现有管理 UI 仍写 `call_record["tone"]`，其值在 Consumer 下记录实际 mode，不新增 schema。

- [ ] **步骤 5：让 `/v1/models` 使用同一 live Consumer 列表**

将 `build_consumer_models_list()` 改为接收 options：

```python
def build_consumer_models_list(
    mode_options: list[dict],
    created: int,
) -> list[dict]:
```

只遍历每项的 `model` 字段生成 OpenAI 模型对象，不输出 `status`，不生成持续变体。

在 `list_models()` 的 Consumer 分支传入：

```python
getattr(app.state, "consumer_mode_options", None)
or _BUILTIN_CONSUMER_MODE_OPTIONS
```

M365 分支继续使用 `build_models_list()`；无账户上下文继续走 M365。

- [ ] **步骤 6：保留正确 WIP 的 wire 传递，删除错误 fallback**

保留并验证：

- `ConsumerCopilotClient.__init__(..., mode: str = "smart")`
- `ConsumerCopilotClient.mode` getter/setter
- `_chat_stream_once()` 中 `send_frame["mode"] = self._mode`
- `ConsumerClientAdapter.mode` 转发属性

不向 Consumer frame 添加 `tone`、`toneId` 或 status；不改变 M365 `_chat_invoke()` payload。

- [ ] **步骤 7：运行聚焦与 M365 回归测试**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_provider_model_selection.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_adapter.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_curl.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_tone_resolver.py" -q
```

预期：PASS。

- [ ] **步骤 8：提交本任务**

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" add -- \
  src/m365_copilot_openai_proxy/routes_api_common.py \
  src/m365_copilot_openai_proxy/routes_api_chat.py \
  src/m365_copilot_openai_proxy/routes_api_messages.py \
  src/m365_copilot_openai_proxy/routes_api_responses.py \
  src/m365_copilot_openai_proxy/consumer_adapter.py \
  src/m365_copilot_openai_proxy/consumer_client.py \
  tests/test_provider_model_selection.py \
  tests/test_consumer_curl.py
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" commit -m "feat(api): 按账户 Provider 解析模型与目录"
```

---

## 任务 5：experimental 错误提示且禁止 mode fallback/retry

**文件：**

- 修改：`src/m365_copilot_openai_proxy/routes_api_common.py`
- 修改：`src/m365_copilot_openai_proxy/consumer_adapter.py`
- 测试：`tests/test_consumer_adapter.py`
- 测试：`tests/test_consumer_curl.py`
- 测试：`tests/test_provider_model_selection.py`
- 回归测试：`tests/test_upstream_error_and_token_status.py`
- 回归测试：`tests/test_responses_stream_failed.py`

- [ ] **步骤 1：编写错误契约红灯测试**

在 `tests/test_consumer_adapter.py` 新增 `test_adapter_appends_rollout_hint_only_for_experimental_mode`：

- 对相同 `ConsumerCopilotError("Copilot error: mode-code")`：
  - `experimental` 转换后的 `SubstrateCopilotError` 必须以原错误开头，并包含批准规格中的中文提示：

    ```text
    该实验 mode 可能受账户、地区或 Microsoft rollout 限制
    ```

  - `stable` 必须完全保留原错误，不含 rollout 提示。

在 `tests/test_consumer_curl.py` 新增或加强：

- `test_consumer_event_error_never_retries_or_falls_back_mode`
  - 配置 `mode="reasoning"`，WebSocket 返回普通 `event:error`。
  - 即使传入 gate，也断言只创建一个 session、gate 未调用、只发送一次 turn、发送 mode 始终是 `reasoning`，从未出现 `smart`。

- 在既有 `test_browser_gate_refreshes_auth_and_retries_one_unstarted_turn` 增加 mode 断言：
  - client 使用 `mode="reasoning"`。
  - 两次 attempt 的 `send` 帧均为 `reasoning`。
  - 仍只允许一次 gate recovery。

在 `tests/test_provider_model_selection.py` 新增：

- `test_consumer_routes_preserve_upstream_error_and_hint_by_status`
  - 三路参数化，并参数化 stable/experimental。
  - fake Consumer client 抛出带原始 code/message 的 `ConsumerCopilotError`。
  - 断言非流式响应沿用现有 HTTP 状态映射，原始 code/message 保留，仅 experimental 追加 rollout 提示。

- `test_consumer_stream_errors_keep_existing_envelopes_and_hint`
  - 三路参数化，`stream=True`。
  - Chat 保留 SSE error 与 `[DONE]`。
  - Messages 保留 Anthropic `error` event。
  - Responses 保留 `error` 与 `response.failed`。
  - 流内 detail 保留原错误，并仅按 experimental status 追加提示。

- [ ] **步骤 2：运行测试确认红灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_adapter.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_curl.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_provider_model_selection.py" -q
```

预期：FAIL。当前选中条目的 status 没有传到 adapter，最终错误没有 experimental 提示。

- [ ] **步骤 3：在 adapter seam 上做最小错误装饰**

在 `ConsumerClientAdapter` 增加默认状态属性：

```python
self.mode_status = "stable"
```

在 `apply_request_model()` 的 Consumer 命中分支设置：

```python
client.mode = option["mode"]
client.mode_status = option["status"]
```

在 adapter 现有 `except ConsumerCopilotError` 中：

1. `detail = str(exc)`，不丢失原始 error code/message。
2. 仅当 `self.mode_status == "experimental"` 时在末尾追加固定中文提示。
3. 抛 `SubstrateCopilotError(detail)`，让三条路由继续复用既有非流式 HTTP 映射和流式错误 envelope。

禁止：

- 不根据错误字符串猜测 mode rejection。
- 不新增 `UnsupportedModeError` 或新错误分类器。
- 不把普通 event error、WebSocket 关闭、超时、HTTP 错误或 challenge 断言为 mode 不支持。
- 不换到 `smart`，不修改保存配置，不因 mode 失败重发 turn。

保留：

- `ConsumerCopilotClient.chat_stream()` 现有一次 `ClearanceRequired` browser-gate recovery。
- 仅在尚未输出时恢复。
- 恢复后仍使用同一个 `self._mode`。
- challenge-response 内复用同一 `send_frame`，因此 mode 不变。

- [ ] **步骤 4：运行聚焦与错误映射回归测试**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_adapter.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_curl.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_provider_model_selection.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_upstream_error_and_token_status.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_responses_stream_failed.py" -q
```

预期：PASS；M365 error mapping 和 Responses 现有终止 envelope 无回归。

- [ ] **步骤 5：提交本任务**

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" add -- \
  src/m365_copilot_openai_proxy/routes_api_common.py \
  src/m365_copilot_openai_proxy/consumer_adapter.py \
  tests/test_consumer_adapter.py \
  tests/test_consumer_curl.py \
  tests/test_provider_model_selection.py
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" commit -m "fix(consumer): 保留错误并提示实验 mode 风险"
```

---

## 任务 6：增加独立 Admin HTML、JavaScript 与中英文说明

**文件：**

- 修改：`src/m365_copilot_openai_proxy/template_admin_shell.py`
- 修改：`src/m365_copilot_openai_proxy/template_admin_settings_js.py`
- 修改：`src/m365_copilot_openai_proxy/template_admin_i18n.py`
- 测试：`tests/test_admin_observability_routes_split.py`
- 语法测试：`tests/test_template_inline_js_syntax.py`

- [ ] **步骤 1：编写 HTML/JS/i18n 红灯测试**

在 `tests/test_admin_observability_routes_split.py` 新增：

- `test_admin_settings_include_independent_m365_and_consumer_model_cards`
  - 断言现有 M365 IDs `tone-options-details/input/save/reset/saved` 保留。
  - 断言新增 Consumer IDs：
    - `consumer-mode-options-details`
    - `consumer-mode-options-input`
    - `consumer-mode-options-save`
    - `consumer-mode-options-reset`
    - `consumer-mode-options-saved`
  - 断言两个 textarea 和两个 reset button 为不同元素。
  - 断言 M365 标题明确为“M365 模型 / Tone”，Consumer 标题明确为“个人版模型 / Mode”。

- `test_admin_consumer_mode_editor_serializes_three_columns`
  - `_ADMIN_SETTINGS_JS` 包含 `_consumerModeOptionsToText`、`saveConsumerModeOptions`、`resetConsumerModeOptions`。
  - 序列化顺序固定为 `model | mode | status`。
  - 保存时把 textarea 原始字符串作为 `consumer_mode_options` 提交，不在浏览器端过滤行，从而保留后端 `line N` 定位。
  - 成功后使用响应中的标准三字段列表重渲染。

- `test_admin_consumer_mode_actions_are_independent_and_surface_errors`
  - Consumer reset 只覆盖 `consumer_mode_options: []`。
  - M365 reset 仍只覆盖 `tone_options: []`。
  - Consumer 保存/reset 失败读取 `(d.error && d.error.message)` 并写入 `consumer-mode-options-saved`，不再静默 `if(!r.ok)return`。

- `test_admin_consumer_mode_i18n_explains_status_and_rollout`
  - 中英文都包含 `model | mode | status`。
  - 都解释 `stable` 与 `experimental`。
  - 都以“可能 / may”表述账户、地区和 Microsoft rollout 限制，不断言失败原因。
  - 都有独立恢复 Consumer 默认文案。

保留现有：

- `test_admin_generated_javascript_passes_node_check`
- `test_template_inline_js_parses[admin]`

- [ ] **步骤 2：运行测试确认红灯**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_admin_observability_routes_split.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_template_inline_js_syntax.py::test_template_inline_js_parses[admin]" -q
```

预期：FAIL。当前模板没有 Consumer editor IDs、三列 JS 函数或对应 i18n key。

- [ ] **步骤 3：将现有 M365 卡片命名明确并增加独立 Consumer 卡片**

在 `template_admin_shell.py`：

1. 保留现有 M365 textarea、保存和恢复逻辑，仅将标题/提示改为明确的 M365 Model/Tone 语义。
2. 在其后新增 Consumer `<details>` 卡片，使用上述独立 IDs。
3. Consumer 卡片包含：
   - `model | mode | status` 格式说明。
   - stable/experimental 说明。
   - 账户、地区和 Microsoft rollout 风险提示。
   - 独立保存按钮。
   - 独立“恢复个人版默认”按钮。
   - 可同时显示成功或错误的独立状态元素。

不要合并两个编辑器，不改变 M365 `value | display name` 格式。

- [ ] **步骤 4：增加最小 JavaScript 并显示具体服务端错误**

在 `renderRuntimeSettings(s)` 增加：

```javascript
const co=document.getElementById('consumer-mode-options-input');
if(co&&document.activeElement!==co){
  co.value=_consumerModeOptionsToText(s.consumer_mode_options||[]);
}
```

新增：

- `_consumerModeOptionsToText(opts)`：每项输出 `model + ' | ' + mode + ' | ' + status`。
- `saveConsumerModeOptions()`：
  - `body={...__runtimeSettings,consumer_mode_options:ta.value}`。
  - HTTP 400 时解析 `d.error.message` 并原样显示在 `consumer-mode-options-saved`，包括 `line N`。
  - 成功时更新 `__runtimeSettings`，用三列标准结果重渲染，并显示保存成功。
- `resetConsumerModeOptions()`：
  - `body={...__runtimeSettings,consumer_mode_options:[]}`。
  - 成功后只重渲染 Consumer textarea。
  - 失败时同样显示服务端错误。

现有 `resetToneOptions()` 继续只设置 `tone_options: []`，不得调用 Consumer reset。

- [ ] **步骤 5：补齐配对 i18n key**

在 `template_admin_i18n.py` 的 `zh` 和 `en` 中成对增加：

- `m365_tone_options_title`
- `m365_tone_options_hint`
- `consumer_mode_options_title`
- `consumer_mode_options_hint`
- `consumer_mode_status_hint`
- `consumer_mode_rollout_warning`
- `consumer_mode_restore_default`
- `consumer_mode_saved`

要求中文使用“可能”，英文使用 “may”；不得将 experimental 描述为确定不支持。

- [ ] **步骤 6：运行聚焦和 JavaScript 语法测试**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_admin_observability_routes_split.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_template_inline_js_syntax.py" -q
```

预期：PASS；Node `--check` 无语法错误。若 Node 不可用，只允许测试按现有 skip 条件跳过。

- [ ] **步骤 7：提交本任务**

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" add -- \
  src/m365_copilot_openai_proxy/template_admin_shell.py \
  src/m365_copilot_openai_proxy/template_admin_settings_js.py \
  src/m365_copilot_openai_proxy/template_admin_i18n.py \
  tests/test_admin_observability_routes_split.py
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" commit -m "feat(admin): 增加个人版模型 mode 管理界面"
```

---

## 任务 7：完整验证与交付检查

**文件：**

- 验证：上述所有改动文件
- 不新增功能代码，除非验证暴露批准规格内的缺陷

- [ ] **步骤 1：运行 Consumer/M365 相关定向测试集**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_mode_options.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_admin_settings_routes_split.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_state_init_split.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_provider_model_selection.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_adapter.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_consumer_curl.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_tone_resolver.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_admin_observability_routes_split.py" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests/test_template_inline_js_syntax.py" -q
```

预期：全部 PASS；仅 Node 不可用时允许现有 JS syntax 测试 SKIP。

- [ ] **步骤 2：运行完整 pytest**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m pytest \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests" -q
```

预期：全部 PASS。若失败，先记录真实失败输出，再只修复本功能引起的回归；不得隐藏或跳过失败测试。

- [ ] **步骤 3：运行 Python 编译检查**

```bash
"S:/AIWorker/M365_Copilot_Proxy/docker-multi/.venv/Scripts/python.exe" -m compileall -q \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/src/m365_copilot_openai_proxy" \
  "S:/AIWorker/M365_Copilot_Proxy/docker-multi/tests"
```

预期：退出码 0，无语法错误。

- [ ] **步骤 4：运行 diff 与工作树检查**

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" diff --check
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" status --short
```

预期：`git diff --check` 退出码 0。确认 `.superpowers/` 未被暂存或提交；CRLF 工作区提示不是空白错误，但不得忽略真实 `diff --check` 报错。

- [ ] **步骤 5：完成规格覆盖自检**

逐项确认：

- [ ] 默认 Consumer 目录精确为 11 项三字段结构，顺序固定。
- [ ] 只有 `[]` 恢复默认；空文本和非法容器报可定位错误。
- [ ] Admin Consumer 校验失败时文件、两个 live state 和同请求其他设置均不改变。
- [ ] 损坏持久化 Consumer 字段整字段回退并 warning，其他合法设置保留。
- [ ] `init_app_state()` 发布 Consumer live state。
- [ ] resolver 与 `/v1/models` 共用 live Consumer state，不存在静态第二映射。
- [ ] Provider 只取绑定账户，不根据 model 名推断。
- [ ] 未知 Consumer model 在 client factory 前返回 400，并列出当前可用 ID。
- [ ] 三条 Consumer 路由不进入 M365 persistent session 或 model suffix 解析。
- [ ] Consumer wire 只含 `mode`，M365 payload 只含 `tone`，两者均无 `toneId`。
- [ ] experimental 失败保留原错误并追加非断言式 rollout 提示；stable 不追加。
- [ ] 普通 mode/upstream 错误不重发 turn、不 fallback `smart`。
- [ ] 现有一次 browser-gate recovery 仍可执行，输出前最多一次且 mode 不变。
- [ ] Consumer `/v1/models` 保持 live 顺序、无持续变体、同 mode 多 model 均展示。
- [ ] `model_alias` 只改响应显示，不改 resolver 或模型目录。
- [ ] M365 tone、持续会话、模型目录和 payload 无回归。
- [ ] Admin 中英文文案齐全，具体行错误可见，内嵌 JavaScript 语法通过。

- [ ] **步骤 6：提交验证中必要的修复（仅当确有修复）**

若步骤 1–5 暴露并修复了本功能回归，只暂存对应文件并使用：

```bash
git -C "S:/AIWorker/M365_Copilot_Proxy/docker-multi" commit -m "test(consumer): 补齐 mode 管理回归覆盖"
```

若无需修复，不创建空提交。

---

## 计划质量门禁

执行前或评审时确认：

- [ ] 所有实现任务都有明确红灯命令、预期失败原因、最小实现和绿灯命令。
- [ ] 所有命令使用仓库 `.venv/Scripts/python.exe`，不使用外部 Hermes Python。
- [ ] 没有修改 `tone_options.py` 或 `tone_resolver.py` 行为。
- [ ] 没有新增数据库、per-account Consumer 配置、动态 mode 探测、依赖或错误字符串分类器。
- [ ] 所有实施步骤均给出确定的文件、函数、命令、行为和预期结果，不含未决占位语句。
- [ ] 函数签名与调用顺序一致：共享 selector 返回 `(client, resolved_value, is_consumer)`，三条路由仅在非 Consumer 时解析 M365 session。
- [ ] 提交信息只描述改动本身，不含 AI 工具署名、生成标记、链接、水印或脚注。
- [ ] 仅在用户明确要求时才 push 或创建 PR。
