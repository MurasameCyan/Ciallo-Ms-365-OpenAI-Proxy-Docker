from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.runtime_settings import normalize_tone_options
from m365_copilot_openai_proxy.tone_options import TONE_OPTIONS, TONE_VALUES


EXPECTED_TONE_VALUES = {
    "Magic",
    "Chat",
    "Reasoning",
    "Gpt_5_5_Chat",
    "Gpt_5_5_Reasoning",
    "Gpt_5_2_Chat",
    "Gpt_5_2_Reasoning",
}


def test_tone_options_define_supported_modes():
    assert {option["value"] for option in TONE_OPTIONS} == EXPECTED_TONE_VALUES
    assert TONE_VALUES == EXPECTED_TONE_VALUES
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
