from __future__ import annotations

from m365_copilot_openai_proxy.tone_resolver import (
    PERSIST_DISPLAY_SUFFIX,
    build_models_list,
    normalized_session_model,
    resolve_tone,
    split_persist,
)

# A representative tone list after normalize_tone_options: display names have
# whitespace collapsed to underscores, label_en mirrors label.
_TONES = [
    {"value": "Magic", "label": "自动", "label_zh": "自动", "label_en": "自动"},
    {"value": "Gpt_5_2_Chat", "label": "GPT_5.2_快速响应", "label_zh": "GPT_5.2_快速响应", "label_en": "GPT_5.2_快速响应"},
]


def test_split_persist_recognizes_both_markers():
    assert split_persist("自动") == ("自动", False)
    assert split_persist("自动-持续") == ("自动", True)
    assert split_persist("Magic:persist") == ("Magic", True)
    assert split_persist("Magic:PERSIST") == ("Magic", True)
    assert split_persist("") == ("", False)
    assert split_persist(None) == ("", False)


def test_resolve_tone_matches_display_name():
    assert resolve_tone("自动", _TONES, "Magic") == ("Magic", False)
    assert resolve_tone("自动-持续", _TONES, "Magic") == ("Magic", True)


def test_resolve_tone_matches_underlying_value():
    assert resolve_tone("Gpt_5_2_Chat", _TONES, "Magic") == ("Gpt_5_2_Chat", False)
    assert resolve_tone("Gpt_5_2_Chat:persist", _TONES, "Magic") == ("Gpt_5_2_Chat", True)


def test_resolve_tone_is_case_insensitive_on_label():
    assert resolve_tone("gpt_5.2_快速响应", _TONES, "Magic") == ("Gpt_5_2_Chat", False)


def test_resolve_tone_falls_back_to_default_when_unmatched():
    assert resolve_tone("gpt-4o", _TONES, "Magic") == ("Magic", False)
    assert resolve_tone("gpt-4o-持续", _TONES, "Magic") == ("Magic", True)
    assert resolve_tone("", _TONES, "Reasoning") == ("Reasoning", False)


def test_build_models_list_emits_normal_and_persist_per_tone():
    created = 1234567890
    data = build_models_list(_TONES, created)
    ids = [m["id"] for m in data]
    assert ids == [
        "自动",
        f"自动{PERSIST_DISPLAY_SUFFIX}",
        "GPT_5.2_快速响应",
        f"GPT_5.2_快速响应{PERSIST_DISPLAY_SUFFIX}",
    ]
    assert all(m["object"] == "model" for m in data)
    assert all(m["created"] == created for m in data)
    assert all(m["owned_by"] == "microsoft-365-copilot" for m in data)


def test_build_models_list_advertises_vision_capability():
    """Every model advertises image input so vision-aware clients (LobeChat,
    OpenWebUI, etc.) enable image upload. CherryStudio ignores these fields."""
    data = build_models_list(_TONES, 0)
    assert data  # non-empty
    for m in data:
        assert "image" in m["architecture"]["input_modalities"]
        assert m["capabilities"]["vision"] is True


def test_normalized_session_model_canonicalizes_persist_marker():
    # Display-suffix persist is rewritten to the canonical :persist suffix that
    # _persistent_session's endswith check understands.
    assert normalized_session_model("自动-持续") == "自动:persist"
    assert normalized_session_model("Magic:persist") == "Magic:persist"
    # Normal variant is stripped of any marker.
    assert normalized_session_model("自动") == "自动"
