from __future__ import annotations

# Conversation tone (mode) options discovered from M365 Copilot's mode picker.
# The `tone` field in the Substrate chat payload controls which model/mode is used.
TONE_OPTIONS = [
    {"value": "Magic", "label": "自动 / Auto", "label_zh": "自动", "label_en": "Auto"},
    {"value": "Chat", "label": "快速答复 / Fast", "label_zh": "快速答复", "label_en": "Fast"},
    {"value": "Reasoning", "label": "深度思考 / Think", "label_zh": "深度思考", "label_en": "Think"},
    {"value": "Gpt_5_5_Chat", "label": "GPT 5.5 快速响应", "label_zh": "GPT 5.5 快速响应", "label_en": "GPT 5.5 Fast"},
    {"value": "Gpt_5_5_Reasoning", "label": "GPT 5.5 深度思考", "label_zh": "GPT 5.5 深度思考", "label_en": "GPT 5.5 Think"},
    {"value": "Gpt_5_2_Chat", "label": "GPT 5.2 快速响应", "label_zh": "GPT 5.2 快速响应", "label_en": "GPT 5.2 Fast"},
    {"value": "Gpt_5_2_Reasoning", "label": "GPT 5.2 深度思考", "label_zh": "GPT 5.2 深度思考", "label_en": "GPT 5.2 Think"},
]
TONE_VALUES = {option["value"] for option in TONE_OPTIONS}
