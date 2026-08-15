from __future__ import annotations

import json

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy import runtime_settings
from m365_copilot_openai_proxy.runtime_settings import normalize_tone_options
from m365_copilot_openai_proxy.tone_options import TONE_OPTIONS, TONE_VALUES


EXPECTED_TONE_VALUES = {
    "Magic",
    "Chat",
    "Reasoning",
    "Claude_Sonnet",
    "Claude_Sonnet_Reasoning",
    "Claude_Fable",
    "Claude_Opus",
    "Gpt_5_6_Reasoning",
    "Gpt_5_5_Chat",
    "Gpt_5_5_Reasoning",
    "Gpt_5_4_Chat",
    "Gpt_5_4_Reasoning",
    "Gpt_5_3_Chat",
    "Gpt_5_2_Chat",
    "Gpt_5_2_Reasoning",
}

EXPECTED_TONE_OPTIONS = [
    ("Magic", "Copilot_自动"),
    ("Chat", "Copilot_快速答复"),
    ("Reasoning", "Copilot_深度思考"),
    ("Claude_Sonnet", "claude-sonnet-4-6"),
    ("Claude_Sonnet_Reasoning", "claude-sonnet-4-5"),
    ("Claude_Fable", "claude-fable-5"),
    ("Claude_Opus", "claude-opus"),
    ("Gpt_5_6_Reasoning", "gpt-5.6"),
    ("Gpt_5_5_Chat", "gpt-5.5_Chat"),
    ("Gpt_5_5_Reasoning", "gpt-5.5"),
    ("Gpt_5_4_Chat", "gpt-5.4_Chat"),
    ("Gpt_5_4_Reasoning", "gpt-5.4"),
    ("Gpt_5_3_Chat", "gpt-5.3_Chat"),
    ("Gpt_5_2_Chat", "gpt-5.2_Chat"),
    ("Gpt_5_2_Reasoning", "gpt-5.2"),
]

PREVIOUS_DEFAULT_LABELS = {
    "Claude_Sonnet_Reasoning": "claude-sonnet-4-5_Reasoning",
    "Gpt_5_6_Reasoning": "gpt-5.6_Reasoning",
    "Gpt_5_5_Reasoning": "gpt-5.5_Reasoning",
    "Gpt_5_4_Reasoning": "gpt-5.4_Reasoning",
    "Gpt_5_2_Reasoning": "gpt-5.2_Reasoning",
}


def _previous_default_tone_options():
    options = []
    for option in TONE_OPTIONS:
        old = dict(option)
        label = PREVIOUS_DEFAULT_LABELS.get(old["value"], old["label"])
        old.update(label=label, label_zh=label, label_en=label)
        options.append(old)
    return options


def test_tone_options_define_supported_modes():
    assert {option["value"] for option in TONE_OPTIONS} == EXPECTED_TONE_VALUES
    assert TONE_VALUES == EXPECTED_TONE_VALUES
    assert [(option["value"], option["label"]) for option in TONE_OPTIONS] == EXPECTED_TONE_OPTIONS
    assert all(option["label_zh"] == option["label"] for option in TONE_OPTIONS)
    assert all(option["label_en"] == option["label"] for option in TONE_OPTIONS)
    assert all({"value", "label", "label_zh", "label_en"} <= set(option) for option in TONE_OPTIONS)


def test_create_app_exposes_shared_tone_options(tmp_path):
    client = TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")))

    response = client.get("/admin/tone")

    assert response.status_code == 200
    options = response.json()["options"]
    # Tone options are now admin-editable (persisted in runtime settings); with no
    # override the picker defaults to the built-in modes, passed through
    # normalize_tone_options (2-column format: display names have whitespace
    # collapsed to underscores and label_en mirrors the display name). Compare
    # against that normalized contract rather than the raw built-in list.
    expected = normalize_tone_options([dict(o) for o in TONE_OPTIONS])
    assert [(o["value"], o["label_zh"], o["label_en"]) for o in options] == [
        (o["value"], o["label_zh"], o["label_en"]) for o in expected
    ]


def test_read_runtime_settings_migrates_exact_previous_m365_default(tmp_path):
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": _previous_default_tone_options()}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert [(option["value"], option["label"]) for option in settings["tone_options"]] == EXPECTED_TONE_OPTIONS


def test_read_runtime_settings_preserves_reordered_previous_m365_default(tmp_path):
    custom_options = _previous_default_tone_options()
    custom_options[0], custom_options[1] = custom_options[1], custom_options[0]
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": custom_options}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == custom_options
