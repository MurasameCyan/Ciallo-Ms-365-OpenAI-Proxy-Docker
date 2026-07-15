from __future__ import annotations

# Conversation tone (mode) options discovered from M365 Copilot's mode picker.
# The `tone` field in the Substrate chat payload controls which model/mode is used.
# Display labels become /v1/models ids (spaces → underscores via normalize_tone_options).
TONE_OPTIONS = [
    {"value": "Magic", "label": "Copilot_自动", "label_zh": "Copilot_自动", "label_en": "Copilot_自动"},
    {"value": "Chat", "label": "Copilot_快速答复", "label_zh": "Copilot_快速答复", "label_en": "Copilot_快速答复"},
    {"value": "Reasoning", "label": "Copilot_深度思考", "label_zh": "Copilot_深度思考", "label_en": "Copilot_深度思考"},
    {"value": "Claude_Sonnet", "label": "claude-sonnet-4-6", "label_zh": "claude-sonnet-4-6", "label_en": "claude-sonnet-4-6"},
    {"value": "Claude_Sonnet_Reasoning", "label": "claude-sonnet-4-5_Reasoning", "label_zh": "claude-sonnet-4-5_Reasoning", "label_en": "claude-sonnet-4-5_Reasoning"},
    {"value": "Claude_Fable", "label": "claude-fable-5", "label_zh": "claude-fable-5", "label_en": "claude-fable-5"},
    {"value": "Gpt_5_6_Reasoning", "label": "gpt-5.6_Reasoning", "label_zh": "gpt-5.6_Reasoning", "label_en": "gpt-5.6_Reasoning"},
    {"value": "Gpt_5_5_Chat", "label": "gpt-5.5_Chat", "label_zh": "gpt-5.5_Chat", "label_en": "gpt-5.5_Chat"},
    {"value": "Gpt_5_5_Reasoning", "label": "gpt-5.5_Reasoning", "label_zh": "gpt-5.5_Reasoning", "label_en": "gpt-5.5_Reasoning"},
    {"value": "Gpt_5_2_Chat", "label": "gpt-5.2_Chat", "label_zh": "gpt-5.2_Chat", "label_en": "gpt-5.2_Chat"},
    {"value": "Gpt_5_2_Reasoning", "label": "gpt-5.2_Reasoning", "label_zh": "gpt-5.2_Reasoning", "label_en": "gpt-5.2_Reasoning"},
]
TONE_VALUES = {option["value"] for option in TONE_OPTIONS}
