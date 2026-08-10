# Consumer Copilot 独立模型与 Mode 管理设计

## 1. 背景

本项目同时代理两套不同的 Microsoft Copilot 上游协议：

- Microsoft 365 Copilot（下文简称 M365）通过 Substrate SignalR 调用，模型选择字段是 `arguments[0]["tone"]`。
- Consumer Copilot（个人版 Copilot，下文简称 Consumer）通过 `copilot.microsoft.com` WebSocket 调用，模型选择字段是 `{"event": "send", "mode": ...}`。

两套协议中的选择值不是同一个命名空间，也不存在可安全复用的 `toneId` 字段。管理后台目前只有 M365 tone 列表，Consumer 则依赖代码内的静态 model → mode 映射。这带来以下问题：

1. Consumer mode 会随账户、地区和 Microsoft rollout 变化，硬编码目录无法由管理员及时调整。
2. 静态映射和 `/v1/models` 容易形成不同的事实源。
3. 如果根据模型名猜测 Provider，可能把 M365 tone 发给 Consumer，或把 Consumer mode 发给 M365。
4. 未知模型静默回退到 `smart` 会掩盖客户端配置错误，也可能产生与请求意图不同的回答。

本设计为 Consumer 增加独立的模型 / Mode 管理，同时保持现有 M365 tone 行为不变。

## 2. 调查结论与证据边界

截至 2026 年 8 月，没有发现可复核、稳定且适用于所有账户的 Microsoft Consumer mode 目录接口。第三方实现能够证明某些字符串曾被发送给 Consumer WebSocket，但不能证明它们在所有账户、地区或 rollout 中均可用。

参考实现提供的证据如下：

- [`oljh0/WindowsCopilotAPI`](https://github.com/oljh0/WindowsCopilotAPI) 将 mode 原样写入 `send` 帧，并为 `smart` 留有来自 live session 的较强注释证据；其余值主要来自硬编码映射。
- [`badafans/copilot2api`](https://github.com/badafans/copilot2api) 在实现中发送 `default`、`research`、`computer_use` 和 `coco` 等值，但其 `/v1/models` 输出并未完整覆盖内部 mapper，说明第三方模型目录也不能视为 Microsoft 的完整能力目录。
- [`hung319/mcopilot2api`](https://github.com/hung319/mcopilot2api) 提供了发送 `chat` 的独立第三方证据。

因此，本设计采用以下表述和行为：

- `smart` 标记为 `stable`，表示当前证据相对较强，不表示 Microsoft 提供了永久兼容保证。
- 其余收集到的 mode 标记为 `experimental`。
- 管理后台明确提示：实验 mode 可能受账户、地区和 rollout 限制。
- 本项目不声称默认列表是 Microsoft 官方完整列表，也不通过静态代码阻止管理员配置未来出现的新 mode。

## 3. 目标

1. 在管理后台分别管理 M365 tone 与 Consumer model → mode 映射。
2. 使用 API Key 绑定账户的 `provider` 决定请求采用哪套模型选择协议。
3. 让 Consumer 请求解析与 Consumer `/v1/models` 共用同一份实时配置。
4. 支持保存后热更新，并从 `<TOKEN_DIR>/runtime_settings.json` 恢复。
5. 对配置错误、未知 Consumer model 和上游拒绝给出明确且可诊断的错误。
6. 保持 OpenAI Chat Completions、Anthropic Messages 和 OpenAI Responses 三条兼容路由行为一致。

## 4. 非目标

本次不实现：

- 按 API Key 或按账户分别维护 Consumer mode 列表；配置仍是全局配置。
- 自动探测某个 Consumer 账户当前支持的 mode。
- 从 Microsoft 动态抓取 mode 目录。
- 根据请求中的 `model` 名称推断 Provider。
- 实验 mode 失败后的自动重试或自动降级。
- Consumer 的 `-持续` 或 `:persist` 会话模型变体。
- 改变 M365 tone 的配置格式、解析规则、持续会话行为或 payload。
- 让 `model_alias` 参与上游 tone / mode 的选择。

## 5. Provider 边界

### 5.1 Provider 的唯一判定来源

请求使用哪套协议，只由鉴权后 API Key 绑定账户的 `account.provider` 决定：

- `provider == "consumer"`：按 Consumer model → mode 列表解析，并设置 Consumer client 的 `mode`。
- 其他值或缺省值：维持现有 M365 路径，按 M365 tone 列表解析并设置 `_tone`。

不得根据 `request.model` 的前缀、别名或是否能在某张表中找到来猜测 Provider。

全局 Key 或开放模式没有绑定账户上下文时，继续采用当前 M365 默认行为。这是兼容性选择，不新增自动 Provider 选择。

### 5.2 协议字段隔离

- M365 payload 只写 `tone`，不得写 `mode` 或 `toneId`。
- Consumer WebSocket `send` 帧只用 `mode` 表达模型选择，不得写 M365 `tone` 或 `toneId`。
- `tone_options` 只供 M365 使用。
- `consumer_mode_options` 只供 Consumer 使用。

## 6. 配置模型

### 6.1 存储位置

沿用同一个 `<TOKEN_DIR>/runtime_settings.json`，但保留两个语义独立的字段：

```json
{
  "tone_options": [],
  "consumer_mode_options": []
}
```

两者共用运行设置的读取、保存和热更新机制，不共用条目结构或 resolver。

### 6.2 Consumer 条目结构

标准化后的 Consumer 条目结构为：

```json
{
  "model": "copilot-reasoning",
  "mode": "reasoning",
  "status": "experimental"
}
```

字段含义：

| 字段 | 含义 |
|---|---|
| `model` | 代理对 OpenAI / Anthropic 兼容客户端公开的模型 ID，也是请求时的精确查表键。 |
| `mode` | 原样发送给 Consumer WebSocket `send.mode` 的上游字符串。 |
| `status` | 证据及可用性提示，只允许 `stable` 或 `experimental`；不改变请求执行策略。 |

一个 mode 可以对应多个 model，例如 `copilot-reasoning` 和 `copilot-thinking` 均可映射到 `reasoning`。model 必须唯一，mode 无须唯一。

### 6.3 默认目录

默认配置包含目前收集到的全部 11 个 facade model：

```text
copilot              | smart        | stable
copilot-smart        | smart        | stable
copilot-reasoning    | reasoning    | experimental
copilot-thinking     | reasoning    | experimental
copilot-search       | search       | experimental
copilot-study        | study        | experimental
copilot-chat         | chat         | experimental
copilot-default      | default      | experimental
copilot-research     | research     | experimental
copilot-computer-use | computer_use | experimental
copilot-coco         | coco         | experimental
```

这些是代理的默认兼容目录，而非 Microsoft 官方能力清单。管理员可替换、增加或删除条目。

### 6.4 文本编辑格式与旧格式兼容

后台文本编辑器每行使用：

```text
model | mode | status
```

为兼容已经写入的两列 WIP / 旧配置，也接受：

```text
model | mode
```

缺少 `status` 时按以下规则迁移：

- `mode == "smart"`：补为 `stable`。
- 其他 mode：补为 `experimental`。

无论输入来自文本还是 JSON，保存响应与持久化文件都使用完整的三字段标准结构。

### 6.5 标准化规则

- 去除 `model`、`mode` 和 `status` 两端空白。
- `model` 转为小写；请求模型也执行 `trim + lowercase` 后精确查表。
- `status` 转为小写，并限制为 `stable` 或 `experimental`。
- `mode` 不进行语义映射，标准化后原样进入 `send.mode`。
- 保留现有条目数量和字段长度上限，超限属于配置错误，不静默截断或丢弃。
- 空列表表示「恢复内置默认列表」，与现有恢复默认操作保持一致；它不表示禁用所有 Consumer 模型。

## 7. 严格保存与原子性

Consumer 配置采用严格、整单校验。以下任一情况都使整个 `/admin/runtime-settings` 保存请求返回 HTTP 400：

- 条目不是支持的对象或文本行格式。
- 文本行不是 2 列或 3 列。
- `model` 为空。
- `mode` 为空。
- `status` 不是 `stable` 或 `experimental`。
- 标准化后出现重复 `model`。
- 条目数或字段长度超过上限。

错误响应应指出具体行或条目及原因，便于后台把错误定位到对应行。失败时必须满足：

1. 不写入 `runtime_settings.json`。
2. 不替换 `app.state.runtime_settings`。
3. 不替换 `app.state.consumer_mode_options`。
4. 同一请求中其他运行设置也不部分生效。

也就是说，必须先完成整份请求的解析和校验，再执行任何 live state 修改和磁盘写入。不得静默过滤错误条目，也不得保存剩余的「有效子集」。

从磁盘读取历史配置时，仍执行兼容迁移与标准化；两列合法条目可自动补齐 `status`。如果持久化数据损坏，应沿用运行设置层现有的安全恢复策略并记录诊断信息，不让请求 resolver 获得半有效目录。

## 8. 管理后台

运行设置页面新增独立的「个人版模型 / Mode」卡片，并保留现有「M365 模型 / Tone」卡片。

Consumer 卡片应包含：

- `model | mode | status` 格式说明。
- `stable` 与 `experimental` 的含义。
- 实验 mode 依赖账户、地区和 Microsoft rollout 的警告。
- 独立的「恢复个人版默认」操作。
- 保存失败时的具体错误行提示。

M365 与 Consumer 可由同一个「保存运行设置」请求提交，但两个编辑器、恢复默认按钮和帮助文案相互独立。恢复 Consumer 默认不得改动 `tone_options`；恢复 M365 默认不得改动 `consumer_mode_options`。

中英文管理界面的 i18n 文案均需补齐。内嵌 JavaScript 必须继续通过现有脚本语法测试。

## 9. 运行时数据流

### 9.1 启动与保存

```text
后台 Consumer 编辑器
  → 完整解析和严格校验
  → 标准化 consumer_mode_options
  → runtime_settings.json
  → app.state.runtime_settings
  → app.state.consumer_mode_options
```

应用启动时，`state_init` 从已加载的 runtime settings 发布 `app.state.consumer_mode_options`。管理后台保存成功后，同步更新持久化数据和 live state；后续请求无需重启即可使用新目录。

Consumer 请求 resolver 与 Consumer `/v1/models` 必须只读取 live `app.state.consumer_mode_options`（在初始化缺失时才使用内置默认值）。应删除 `routes_api_common` 中重复的静态映射，避免两个事实源。

### 9.2 请求解析

Consumer 请求流程：

```text
API Key 绑定的 account.provider == consumer
  → 对 request.model 执行 trim + lowercase
  → 在 live consumer_mode_options 中按 model 精确查找
  → 将匹配条目的 mode 设置到 Consumer adapter/client
  → 写入 WebSocket send.mode
```

Chat Completions、Messages 和 Responses 三条路由必须调用同一个共享 resolver。Consumer 路径不得执行 M365 的持续会话模型解析，也不得因为 model 后缀创建 M365 persistent session。

`model_alias` 仅控制兼容 API 响应中显示的模型名称，继续按现有优先级处理；它不参与 model → tone 或 model → mode 的上游选择。

## 10. `/v1/models` 行为

`GET /v1/models` 根据已鉴权 Key 的绑定账户返回 Provider 对应目录：

- Consumer Key：按配置顺序返回 `consumer_mode_options` 中的 model ID。
- M365 Key：继续返回 M365 tone 模型及现有的 `-持续` 变体。
- 没有账户上下文的全局 Key / 开放模式：继续返回当前 M365 默认目录。

Consumer 目录：

- 不生成 `-持续` 或 `:persist` 变体。
- model 顺序与后台配置顺序一致。
- 多个 model 可以展示为不同 ID，即使它们映射到同一个 mode。
- `owned_by` 继续使用 Consumer 目录既有的 Microsoft Copilot 标识。

`status` 首先用于管理后台的证据提示，不要求改变 OpenAI 标准模型对象结构；若未来需要通过 API 暴露状态，应作为单独兼容设计处理。

## 11. 错误行为

### 11.1 未知 Consumer model

如果 Consumer 请求中的 model 在 live 列表中不存在：

- 在创建上游调用前返回 HTTP 400。
- 错误详情包含请求的模型 ID和当前可用的 Consumer model ID。
- 不静默回退到 `smart`。
- 不根据同名 M365 tone 改走 M365 协议。

### 11.2 实验 mode 被上游拒绝

如果已配置的实验 mode 被 Consumer 上游拒绝：

- 返回明确的上游错误，并补充该 mode 可能受账户、地区或 rollout 限制的提示。
- 不重试同一请求。
- 不切换到 `smart`。
- 不修改保存的配置或 status。

该策略保证请求语义可预测，也避免一次失败请求意外产生另一模型的回答。

### 11.3 传输或鉴权故障

普通 WebSocket 断开、超时、Cookie / token 失效等故障继续使用 Consumer 路径现有的错误映射。本设计不把所有上游错误都解释为 mode 不可用；只有上游明确拒绝或能够可靠分类为 mode 不可用时才添加 rollout 提示。

## 12. 兼容与迁移

- 现有 `copilot`、`copilot-smart`、`copilot-reasoning`、`copilot-thinking`、`copilot-search` 和 `copilot-study` 别名继续存在于默认列表。
- 新默认列表追加 `copilot-chat`、`copilot-default`、`copilot-research`、`copilot-computer-use` 和 `copilot-coco`。
- 已持久化的合法两字段条目在加载或下次保存时补齐 status。
- Consumer 未知模型从静默回退 `smart` 改为 HTTP 400。这是有意的行为修正，调用方必须改用 `/v1/models` 中的 ID 或由管理员添加映射。
- M365 tone resolver、默认 tone、`-持续` / `:persist` 行为和 payload 均保持不变。

## 13. 实现边界

预计涉及以下模块：

| 区域 | 职责 |
|---|---|
| `runtime_settings.py` | 定义 11 个默认条目；实现三字段兼容迁移、标准化和严格校验。 |
| `state_init.py` | 启动时发布 `app.state.consumer_mode_options`。 |
| `routes_admin_settings.py` | 在保存前原子校验；持久化并热更新 Consumer 配置。 |
| `routes_api_common.py` | 从 live 配置解析 Consumer model；生成 Consumer 模型目录；删除重复静态映射。 |
| `routes_api_chat.py`、`routes_api_messages.py`、`routes_api_responses.py` | 统一调用 Provider-aware selector，并隔离 Consumer 与 M365 的会话行为。 |
| `consumer_adapter.py`、`consumer_client.py` | 将解析后的 mode 传递到最终 WebSocket `send` 帧。 |
| `template_admin_shell.py`、`template_admin_settings_js.py`、`template_admin_i18n.py` | 增加独立 Consumer 编辑器、默认恢复、错误定位及中英文说明。 |

`tone_options.py` 与 `tone_resolver.py` 不应因本功能改变行为。

## 14. 测试矩阵

### 14.1 Normalizer 与配置验证

- 默认值精确包含 11 个 model / mode / status 条目，顺序固定。
- 文本三列和 JSON 对象输入均可标准化。
- 两列输入按 `smart → stable`、其他 mode → `experimental` 补齐 status。
- model 大小写与两端空白正确标准化。
- 同一 mode 的多个 model 合法。
- 空 model、空 mode、未知 status、重复 model、无效条目、字段过长和条目过多分别返回可定位错误。
- 任一错误不会返回部分列表。
- 空列表恢复内置默认值。

### 14.2 Admin API 与持久化

- GET 返回标准化后的 `consumer_mode_options`。
- POST 成功时响应返回完整三字段列表，并更新 `app.state.runtime_settings` 与 `app.state.consumer_mode_options`。
- 新建应用读取同一个 token dir 后恢复相同列表。
- POST 失败时文件、live Consumer 列表及同请求中的其他设置都不改变。
- 恢复 Consumer 默认不改变 M365 tone 配置，反向亦然。

### 14.3 Provider-aware API 路由

对以下三条路由使用参数化测试：

- `/v1/chat/completions`
- `/v1/messages`
- `/v1/responses`

断言：

- Consumer Key 的已知 model 在三条路由中得到相同 mode。
- live 配置修改后，三条路由立即采用新映射。
- 未知 Consumer model 在实例化 / 调用上游前返回 HTTP 400，并列出当前可用 ID。
- Consumer model 不触发 M365 persistent session helper。
- M365 Key 继续把 model 解析为 tone。
- Provider 不由 model 名猜测。

### 14.4 Wire payload

- Consumer 最终 `send` 帧包含所选 `mode`。
- Consumer 帧不包含 `tone` 或 `toneId`。
- M365 invocation argument 包含所选 `tone`。
- M365 argument 不包含 `mode` 或 `toneId`。

### 14.5 模型目录

- Consumer Key 只获得 live Consumer model 列表，顺序与配置一致。
- Consumer 列表不含 `-持续` 或 `:persist` 变体。
- M365 Key 只获得 M365 tone 目录及其现有持续变体。
- 全局 Key / 开放模式继续获得 M365 默认目录。
- 多个 model 映射同一 mode 时仍各自出现在目录中。

### 14.6 管理后台

- 页面存在独立的 M365 和 Consumer 配置区及独立恢复按钮。
- Consumer 文本的加载与序列化保留三列。
- 保存错误能显示具体错误行。
- stable / experimental 与 rollout 警告的中英文文案齐全。
- 管理页内嵌 JavaScript 通过语法检查。

## 15. 验收标准

满足以下条件即完成本功能：

1. Consumer 的配置、resolver 和 `/v1/models` 只有一个 live 事实源。
2. Provider 只由 Key 绑定账户决定，三条 API 路由行为一致。
3. Consumer 使用 `send.mode`，M365 使用 `tone`，任何路径都不引入 `toneId`。
4. 后台可独立编辑并恢复 Consumer 默认列表，保存后立即生效且重启后保留。
5. 配置错误整单拒绝，未知 Consumer model 返回 HTTP 400。
6. 实验 mode 被上游拒绝时不重试、不回退 `smart`。
7. Consumer `/v1/models` 不包含 M365 模型或持续变体，M365 行为无回归。
8. 本文测试矩阵对应的自动化测试全部通过。
