from __future__ import annotations

# Conversation tone (mode) options discovered from M365 Copilot's mode picker.
# The `tone` field in the Substrate chat payload controls which model/mode is used.
# Display labels become /v1/models ids (spaces → underscores via normalize_tone_options).
#
# Which of these an account may actually use is decided on the M365 side, not here:
# `Claude_Fable` and `Claude_Opus` are real modes that this tenant is currently
# refused on (measured 2026-08-02 with scan_tones.py) and are listed on purpose, so
# they come back by themselves once Microsoft rolls them out -- do not "clean them
# up". A refused mode now surfaces as an upstream error naming the mode rather than
# as a silent canned reply (see substrate_client._M365_REFUSAL_TEXTS).
TONE_OPTIONS = [
    {"value": "Magic", "label": "Copilot_自动", "label_zh": "Copilot_自动", "label_en": "Copilot_自动"},
    {"value": "Chat", "label": "Copilot_快速答复", "label_zh": "Copilot_快速答复", "label_en": "Copilot_快速答复"},
    {"value": "Reasoning", "label": "Copilot_深度思考", "label_zh": "Copilot_深度思考", "label_en": "Copilot_深度思考"},
    {"value": "Claude_Sonnet", "label": "claude-sonnet-4-6", "label_zh": "claude-sonnet-4-6", "label_en": "claude-sonnet-4-6"},
    {"value": "Claude_Sonnet_Reasoning", "label": "claude-sonnet-4-5_Reasoning", "label_zh": "claude-sonnet-4-5_Reasoning", "label_en": "claude-sonnet-4-5_Reasoning"},
    {"value": "Claude_Fable", "label": "claude-fable-5", "label_zh": "claude-fable-5", "label_en": "claude-fable-5"},
    {"value": "Claude_Opus", "label": "claude-opus", "label_zh": "claude-opus", "label_en": "claude-opus"},
    {"value": "Gpt_5_6_Reasoning", "label": "gpt-5.6_Reasoning", "label_zh": "gpt-5.6_Reasoning", "label_en": "gpt-5.6_Reasoning"},
    {"value": "Gpt_5_5_Chat", "label": "gpt-5.5_Chat", "label_zh": "gpt-5.5_Chat", "label_en": "gpt-5.5_Chat"},
    {"value": "Gpt_5_5_Reasoning", "label": "gpt-5.5_Reasoning", "label_zh": "gpt-5.5_Reasoning", "label_en": "gpt-5.5_Reasoning"},
    {"value": "Gpt_5_4_Chat", "label": "gpt-5.4_Chat", "label_zh": "gpt-5.4_Chat", "label_en": "gpt-5.4_Chat"},
    {"value": "Gpt_5_4_Reasoning", "label": "gpt-5.4_Reasoning", "label_zh": "gpt-5.4_Reasoning", "label_en": "gpt-5.4_Reasoning"},
    {"value": "Gpt_5_3_Chat", "label": "gpt-5.3_Chat", "label_zh": "gpt-5.3_Chat", "label_en": "gpt-5.3_Chat"},
    {"value": "Gpt_5_2_Chat", "label": "gpt-5.2_Chat", "label_zh": "gpt-5.2_Chat", "label_en": "gpt-5.2_Chat"},
    {"value": "Gpt_5_2_Reasoning", "label": "gpt-5.2_Reasoning", "label_zh": "gpt-5.2_Reasoning", "label_en": "gpt-5.2_Reasoning"},
]
TONE_VALUES = {option["value"] for option in TONE_OPTIONS}
