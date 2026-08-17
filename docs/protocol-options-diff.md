# Protocol options diff (Ciallo vs HEXUXIU/M365-Copilot2API)

## 2026-07-20 轮

对照日期：2026-07-20。  
对方参考：`HEXUXIU/M365-Copilot2API` `payload.py`（v0.6.0 附近）。  
本仓库：`src/m365_copilot_openai_proxy/substrate_client.py`（`_OPTIONS_SETS` / `_VARIANTS`）。

> 目的：协议能力对齐，**不是**换鉴权/长效 RT。  
> 结论：本仓库在 variants / 多租户 / 媒体上更完整；对方 FULL optionsSets 里若干图/引用 flag 值得并入（已并入本轮）。

## optionsSets

| Flag | 对方 FULL | 本仓库（改前） | 本轮 |
|------|-----------|----------------|------|
| `search_result_progress_messages_with_search_queries` | ✅ | ✅ | 保留 |
| `update_textdoc_response_after_streaming` | ✅ | ❌ | **新增** |
| `deepleo_networking_timeout_10minutes_canmore` | ✅ | ❌ | **新增**（长思考更稳） |
| `cwc_flux_image` | ✅ | ✅ | 保留 |
| `cwc_code_interpreter` + amsform / charts / matplotlib | ✅ | ✅ | 保留 |
| `cwcfluxgptv` | ✅ | ✅ | 保留 |
| `flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch` | ✅ | ✅ | 保留 |
| `gptvnorm2048` | ✅ | ❌ | **新增**（与 UploadFile 一致） |
| `cwc_fileupload_odb` | ✅ | ✅ | 保留 |
| `update_memory_plugin` / `add_custom_instructions` | ✅ | ✅ | 保留 |
| `cwc_flux_v3` / `flux_v3_progress_messages` | ✅ | ✅ | 保留 |
| `enable_batch_token_processing` / `enable_gg_gpt` | ✅ | ✅ | 保留 |
| `flux_v3_references` / `flux_v3_references_entities` | ✅ | ❌ | **新增** |
| `flux_v3_image_gen_enable_dimensions` | ✅ | ✅ | 保留 |
| `flux_v3_image_gen_enable_non_watermarked_storage` | ✅ | ❌ | **新增** |
| `flux_v3_image_gen_enable_icon_dimensions` | ✅ | ❌ | **新增** |
| `flux_v3_image_gen_enable_system_text_with_params` | ✅ | ✅ | 保留 |
| `flux_v3_image_gen_enable_designer_dimensions_meta_prompting_in_system_prompts` | ✅ | ✅ | 保留 |
| `flux_v3_image_gen_enable_story` | ✅ | ❌ | **新增** |
| `rich_responses` | ✅ | ❌ | **新增** |
| `pages_citations` / `pages_citations_multiturn` | ✅ | ❌ | **新增** |
| `enable_structured_output` / `precise_mode` | ❌ | ✅ | **保留**（我方独有） |

## variants（摘要）

双方均有 Helix / bizchatflux / streaming / source attributions 等核心串。  
本仓库额外偏 Office Web / Designer / 引用 / 会议等（如 `EnableDesignEditorImageGrounding`、`feature.EnableDesignerEditor`、`feature.enableGenerateGraphicArtOptionsSet`）。  
**本轮不改 `_VARIANTS`**：风险高、收益不确定；需要时再对浏览器抓包 diff。

## 明确不搬

| 对方项 | 原因 |
|--------|------|
| Desktop `client_id` / 90 天 RT | 已否决 |
| `messageHistory` 全量重放 | 无会话痛点时不做（S3 可选） |
| Lite `OPTIONS_SETS` / Windows hostContext | 我方固定 officeweb 已够用 |
| 按 `enable_image_gen` 拆 FULL 子集 | 我方始终开图+文件，与产品一致 |

## 回归关注

- 出图 / 代码解释器 / 引用列表是否异常  
- 流式 cite 是否被清干净（见 `clean_m365_citations`）  
- 若某 flag 触发上游错误，从 `_OPTIONS_SETS` 回退该行即可  

---

## 2026-08-18 轮（续写，不重做上一轮）

对照日期：2026-08-18。  
对方参考：`HEXUXIU/M365-Copilot2API` `internal/chathub/client.go`（`const variants` / `optionsSets` / `buildWSURL` / `uploadAttachments`），已不再是 `payload.py`。  
本仓库：`substrate_client.py`（`_VARIANTS` / `_OPTIONS_SETS` / `_ws_url` / `_chat_invoke`）、`substrate_upload.py`。

> 上一轮的「明确不搬」四项**不再复议**。  
> 本轮结论：optionsSets 已反向——对方生产串是我方的真子集，没得抄；真正值钱的是**帧字段**，其中一个 flag 拼错、一个时区偏移写死，两者都是静默失效。

### variants

对方 41 项，我方 51 项（本轮 +1 后）。

| 方向 | 数量 | 明细 |
|------|------|------|
| 对方有、我方无 | 1 | `turnOffWorkTabUpsellFromClient` → **已加**（注意它无 `feature.` 前缀，紧跟在 `feature.turnOnWorkTabRecommendation` 后面，成对出现） |
| 我方有、对方无 | 10 | `SingletonEnvOn`、`feature.EnableMergingPureDeltas`、`feature.EnableConversationShareApis`、`feature.EnableContentApiandDocTypeHtmlInRichAnswers`、`cdxgrounding_api_v2_rich_web_answers_reference_bottom_force`、`cdxenablerenderforisocomp`、`feature.EnableSkipRehydrationForSpeCIdImages`、`feature.EnableSkipEmittingMessageOnFlush`、`feature.EnableRemoveEmptySourceAttributions`、`feature.EnableRemoveStreamingMode` — 全部保留 |

补完后差集为空，`_VARIANTS` 这条线以后只需盯浏览器抓包，不必再回头对它。

### optionsSets

对方生产串已从上一轮的 FULL 缩到 **14 项**，且是我方 33 项的**严格子集**——本轮 0 项可抄。上一轮并入的 `rich_responses` / `pages_citations*` / `flux_v3_image_gen_enable_*` 等他们已经不发了，我方继续发（线上有效，见下）。

唯一改动是拼写：

| 改前 | 改后 | 理由 |
|------|------|------|
| `cwc_code_interpreter_interactive_charts_inline_image` | `code_interpreter_interactive_charts_inline_image` | 上下两行兄弟项（`code_interpreter_interactive_charts`、`code_interpreter_matplotlib_patching`）都是裸前缀；带 `cwc_` 的这个拼法在浏览器抓包和对方仓库里都不存在，即**一直是被上游忽略的空转项** |

### 帧字段（本轮重点）

`_chat_invoke` 的 `arguments[0]` 对比：

| 字段 | 对方 | 我方（改前） | 本轮 |
|------|------|--------------|------|
| `productThreadType: "Office"` | ✅ | ❌ | **已加**（放在 `threadLevelGptId` 之后，与浏览器顺序一致） |
| `message.locationInfo.timeZoneOffset` | 按时区算 | 写死 `9`，旁边 `timeZone` 却可配（默认 `Asia/Shanghai`） | **已改为按 `timeZone` 现算**（`_tz_offset_hours`，`zoneinfo`）；即默认账号过去一直告诉模型自己的本地钟比它刚报出的时区快一小时 |
| `allowedMessageTypes` | 较短 | 超集 | 保留我方 |
| type-1 `Metrics` 帧（`Timestamps` 四个字段全空串） | 每轮在 chat 帧后追发一帧 | 不发 | **不搬**：四个时间戳他们全填空串，等于纯遥测噪声，上游不依赖它（我方不发也一直正常成轮） |

`_tz_offset_hours` 取整到小时（半时区如 `Asia/Kolkata` 丢 `:30`，浏览器该字段是整数）；时区名不可用时回落 `+8`，与默认时区一致。  
新增依赖 **`tzdata`**：`zoneinfo` 自身不带库，宿主没装 tz 数据（Windows、将来的 slim 镜像）时每个时区都会静默落到 `+8`——那就等于把刚修掉的 bug 换个形状装回来。

### WS URL

| 参数 | 对方 | 我方 | 处置 |
|------|------|------|------|
| `chatsessionid` | 发（值同 `clientrequestid`） | 不发 | **不搬**：线上不发一样成轮，重复同一个值没有信息量 |
| `source` | `"officeweb"`（带字面引号，被编码成 `%22officeweb%22`） | `officeweb` | 保留我方裸值，线上通 |
| 其余（`ClientRequestId` / `X-SessionId` / `ConversationId` / `access_token` / `variants` / `product` / `agentHost` / `licenseType` / `agent` / `scenario`） | 同 | 同 | — |

### 图片上传

对方代码里有一条硬结论：

> `Live-verified 2026-08-08: UploadFile rejects multipart bodies (HTTP 400 InvalidRequest); it requires x-www-form-urlencoded`

**今天（2026-08-18）在生产容器上实测复现不出来**——先走 admin API 强制刷新令牌，再对同一账号打三发：

| 请求形态 | 结果 |
|----------|------|
| 我方现状：`multipart/form-data` + `optionsSets=gptvnorm2048` | **200**，返回 docId |
| 对方形态：`application/x-www-form-urlencoded` | **200** |
| `multipart` + `optionsSets=cwcgptvsan` | **200** |

结论：`substrate_upload.py` **不改**。两条线都通，多一次形态迁移只有回归风险没有收益。顺手记下他们多带的东西，将来上游真的收紧了再取：`optionsSets` 发两个值（`cwcgptvsan` + `flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch`）、`Referer: https://m365.cloud.microsoft/`、以及显式剔掉空 `Origin`。我方另有他们没有的 `x-anchormailbox: Oid:<oid>@<tid>`（多租户必需），保留。

### 他们的 `scripts/*probe*.py` 里值得学的

- `genprobe.py`：把上游每一帧原样落盘再解析，而不是边收边判——协议漂移时这是唯一能事后复盘的东西。我方 `RESPONSE_DEBUG_SINK` 已经接近，缺的是「连接建立/关闭也记一条」。
- `genprobe.py` 的 `walk()`：在响应 JSON 里递归捞所有 URL 字段，用来发现新的媒体/引用端点，不必事先知道字段名。
- `multimodal_probe.py` / `chathub_probe.py`：单账号硬编码 token 的一次性脚本，架构上不用参考。

### 验证方式

- variants / optionsSets 差集：脚本对 `client.go` 与 `substrate_client.py` 直接取串求差，不靠眼看。
- 帧字段：`tests/test_substrate_frame_options.py`（8 测）钉住 offset 与时区名一致（**从 `zoneinfo` 现算期望值，跨夏令时不会假失败**）、未知时区回落 8、`productThreadType`、inline-chart flag 的正确拼法与错误拼法的缺席、`turnOffWorkTabUpsellFromClient` 在串里。
- 线上 A/B：把四处帧改动在生产容器内进程内打补丁，同一账号跑真实轮次，baseline 与 patched 都返回 `OK` → 新字段被上游接受，不是「发了不报错但答不出来」。
- 上传：三种形态各打一发真实请求，见上表。

### 回归关注（本轮新增）

- 镜像里必须有 `tzdata`，否则 `timeZoneOffset` 回落 `+8` 且**不报错**——只会让模型的「今天/现在」偏掉。
- 若 `productThreadType` 未来触发上游拒答，删该行即可，与其他字段无耦合。

