# Protocol options diff (Ciallo vs HEXUXIU/M365-Copilot2API)

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
