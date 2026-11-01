from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy import runtime_settings
from m365_copilot_openai_proxy.runtime_settings import normalize_tone_options
from m365_copilot_openai_proxy.tone_options import TONE_OPTIONS


DEFAULT_TONE_OPTIONS_BEFORE_ISSUE9 = [
    ("Magic", "Copilot_自动"),
    ("Chat", "Copilot_快速答复"),
    ("Reasoning", "Copilot_深度思考"),
    ("Claude_Sonnet", "claude-sonnet-4-6"),
    ("Claude_Sonnet_Reasoning", "claude-sonnet-4-5"),
    ("Claude_Fable", "claude-fable-5"),
    ("Claude_Opus", "claude-opus"),
    ("Gpt_6_Astra", "gpt-6_Chat"),
    ("Gpt_6_Reasoning", "gpt-6"),
    ("Gpt_5_6_Chat", "gpt-5.6_Chat"),
    ("Gpt_5_6_Reasoning", "gpt-5.6"),
    ("Gpt_5_5_Chat", "gpt-5.5_Chat"),
    ("Gpt_5_5_Reasoning", "gpt-5.5"),
    ("Gpt_5_4_Chat", "gpt-5.4_Chat"),
    ("Gpt_5_4_Reasoning", "gpt-5.4"),
    ("Gpt_5_3_Chat", "gpt-5.3_Chat"),
    ("Gpt_5_3_Reasoning", "gpt-5.3"),
    ("Gpt_5_2_Chat", "gpt-5.2_Chat"),
    ("Gpt_5_2_Reasoning", "gpt-5.2"),
    ("Grok_4_5", "grok-4.5"),
]

PREVIOUS_DEFAULT_LABELS = {
    "Claude_Sonnet_Reasoning": "claude-sonnet-4-5_Reasoning",
    "Gpt_5_6_Reasoning": "gpt-5.6_Reasoning",
    "Gpt_5_5_Reasoning": "gpt-5.5_Reasoning",
    "Gpt_5_4_Reasoning": "gpt-5.4_Reasoning",
    "Gpt_5_2_Reasoning": "gpt-5.2_Reasoning",
}

# The historical on-disk default, pinned by value+order. This must NOT be
# derived from the live TONE_OPTIONS: the migration in
# runtime_settings fires only on an *exact* match against the bytes an older
# release persisted, so adding a tone to the current catalogue must leave this
# list untouched. Rebuilding it here (rather than importing
# _PREVIOUS_BUILTIN_TONE_OPTIONS) keeps the double-entry check that would catch
# a typo in that production constant.
PREVIOUS_DEFAULT_VALUES = [
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
]


def _previous_default_tone_options():
    by_value = {option["value"]: option for option in TONE_OPTIONS}
    options = []
    for value in PREVIOUS_DEFAULT_VALUES:
        old = dict(by_value[value])
        label = PREVIOUS_DEFAULT_LABELS.get(value, old["label"])
        old.update(label=label, label_zh=label, label_en=label)
        options.append(old)
    return options


def test_read_runtime_settings_migrates_exact_previous_m365_default(tmp_path):
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": _previous_default_tone_options()}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == normalize_tone_options(TONE_OPTIONS)


def test_read_runtime_settings_preserves_reordered_previous_m365_default(tmp_path):
    custom_options = _previous_default_tone_options()
    custom_options[0], custom_options[1] = custom_options[1], custom_options[0]
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": custom_options}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == custom_options


# The defaults shipped between the label rename and today, pinned by value+order
# for the same double-entry reason as PREVIOUS_DEFAULT_VALUES: the production
# constant derives these from TONE_OPTIONS, so a test that derived them the same
# way would pass even if both were wrong together. Labels are the current ones --
# only the tone set differs from today's default.
DEFAULT_VALUES_BEFORE_ISSUE9 = [value for value, _label in DEFAULT_TONE_OPTIONS_BEFORE_ISSUE9]
DEFAULT_VALUES_BEFORE_GPT_6_ASTRA = [
    "Magic",
    "Chat",
    "Reasoning",
    "Claude_Sonnet",
    "Claude_Sonnet_Reasoning",
    "Claude_Fable",
    "Claude_Opus",
    "Gpt_5_6_Chat",
    "Gpt_5_6_Reasoning",
    "Gpt_5_5_Chat",
    "Gpt_5_5_Reasoning",
    "Gpt_5_4_Chat",
    "Gpt_5_4_Reasoning",
    "Gpt_5_3_Chat",
    "Gpt_5_3_Reasoning",
    "Gpt_5_2_Chat",
    "Gpt_5_2_Reasoning",
]
DEFAULT_VALUES_BEFORE_GPT_6_REASONING = [
    *DEFAULT_VALUES_BEFORE_GPT_6_ASTRA[:7],
    "Gpt_6_Astra",
    *DEFAULT_VALUES_BEFORE_GPT_6_ASTRA[7:],
]
DEFAULT_VALUES_BEFORE_GPT_5_6_CHAT = [
    v for v in DEFAULT_VALUES_BEFORE_GPT_6_ASTRA if v != "Gpt_5_6_Chat"
]
DEFAULT_VALUES_BEFORE_GPT_5_3_REASONING = [
    v for v in DEFAULT_VALUES_BEFORE_GPT_5_6_CHAT if v != "Gpt_5_3_Reasoning"
]


DEFAULT_VALUES_BEFORE_GROK_4_5 = [
    value for value in DEFAULT_VALUES_BEFORE_ISSUE9 if value != "Grok_4_5"
]

def _default_tone_options_limited_to(values):
    by_value = {option["value"]: option for option in TONE_OPTIONS}
    return [dict(by_value[value]) for value in values]


@pytest.mark.parametrize("version", [
    2,
    runtime_settings._TONE_OPTIONS_SCHEMA_VERSION,
    runtime_settings._TONE_OPTIONS_SCHEMA_VERSION + 1,
])
def test_read_runtime_settings_preserves_removed_grok_after_catalogue_is_versioned(tmp_path, version):
    options = _default_tone_options_limited_to(DEFAULT_VALUES_BEFORE_GROK_4_5)
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({
            "tone_options": options,
            "tone_options_schema_version": version,
        }),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == options


@pytest.mark.parametrize("values, removed_model", [
    (DEFAULT_VALUES_BEFORE_GROK_4_5, "grok-4.5"),
    (DEFAULT_VALUES_BEFORE_ISSUE9, "muse-spark"),
])
def test_admin_removed_tone_stays_removed_after_saving_and_restarting(tmp_path, values, removed_model):
    options = _default_tone_options_limited_to(values)
    config = Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")
    client = TestClient(create_app(config))

    response = client.post("/admin/runtime-settings", json={
        "tone_options": options,
        # This is a server-owned migration marker, not an editable setting.
        "tone_options_schema_version": 0,
    })

    assert response.status_code == 200
    persisted = json.loads((tmp_path / "runtime_settings.json").read_text(encoding="utf-8"))
    assert persisted["tone_options_schema_version"] == runtime_settings._TONE_OPTIONS_SCHEMA_VERSION
    restarted = create_app(config)
    assert restarted.state.tone_options == options
    models = TestClient(restarted).get("/v1/models").json()["data"]
    assert removed_model not in {model["id"] for model in models}


@pytest.mark.parametrize("version", [0, 1, 2])
def test_read_runtime_settings_migrates_exact_pre_issue9_default(tmp_path, version):
    options = _default_tone_options_limited_to(DEFAULT_VALUES_BEFORE_ISSUE9)
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": options, "tone_options_schema_version": version}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == normalize_tone_options(TONE_OPTIONS)
    assert {"Muse_Spark", "Grok_Auto", "Grok_Reasoning", "Gpt_6_Sol_Reasoning", "Critique"} <= {
        option["value"] for option in settings["tone_options"]
    }


@pytest.mark.parametrize("customization", ["rename", "reorder"])
def test_read_runtime_settings_preserves_custom_pre_issue9_catalogue(tmp_path, customization):
    options = _default_tone_options_limited_to(DEFAULT_VALUES_BEFORE_ISSUE9)
    if customization == "rename":
        options[0].update(label="My_Copilot", label_zh="My_Copilot", label_en="My_Copilot")
    else:
        options[0], options[1] = options[1], options[0]
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": options, "tone_options_schema_version": 2}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == options


def test_read_runtime_settings_migrates_defaults_that_predate_each_added_tone(tmp_path):
    # Production sat on the second of these for two releases: the rename
    # migration had already rewritten its labels, so it matched neither the
    # old-label literal nor the current default, and every tone added afterwards
    # was locked out of the picker until someone wrote the list by hand.
    for pinned in (
        DEFAULT_VALUES_BEFORE_GROK_4_5,
        DEFAULT_VALUES_BEFORE_GPT_6_REASONING,
        DEFAULT_VALUES_BEFORE_GPT_6_ASTRA,
        DEFAULT_VALUES_BEFORE_GPT_5_6_CHAT,
        DEFAULT_VALUES_BEFORE_GPT_5_3_REASONING,
    ):
        (tmp_path / "runtime_settings.json").write_text(
            json.dumps({"tone_options": _default_tone_options_limited_to(pinned)}),
            encoding="utf-8",
        )

        settings = runtime_settings._read_runtime_settings(str(tmp_path))

        assert settings["tone_options"] == normalize_tone_options(TONE_OPTIONS), pinned


def test_read_runtime_settings_keeps_a_list_an_operator_actually_edited(tmp_path):
    # The guard on widening the migration: "default minus a tone" must only be
    # treated as untouched when that tone postdates the persisted list. A tone
    # the operator deliberately removed has to stay removed, or the upgrade
    # silently hands their users back a model they withdrew.
    custom_options = _default_tone_options_limited_to(
        [v for v in DEFAULT_VALUES_BEFORE_ISSUE9 if v != "Claude_Opus"]
    )
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": custom_options}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == custom_options
    assert "Claude_Opus" not in [o["value"] for o in settings["tone_options"]]


def test_partial_issue9_additions_are_not_a_historical_default(tmp_path):
    options = [dict(option) for option in TONE_OPTIONS if option["value"] != "Muse_Spark"]
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": options}), encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == options


DEFAULT_VALUES_SCHEMA3 = [option["value"] for option in TONE_OPTIONS if option["value"] != "Gpt_61_Sol_Reasoning"]


@pytest.mark.parametrize("version", [0, 2, 3])
def test_read_runtime_settings_adds_gpt61_sol_to_an_untouched_schema3_default(tmp_path, version):
    options = _default_tone_options_limited_to(DEFAULT_VALUES_SCHEMA3)
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": options, "tone_options_schema_version": version}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == normalize_tone_options(TONE_OPTIONS)
    assert settings["tone_options_schema_version"] == 4


def test_read_runtime_settings_keeps_gpt61_sol_removed_once_saved_at_schema4(tmp_path):
    options = _default_tone_options_limited_to(DEFAULT_VALUES_SCHEMA3)
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"tone_options": options, "tone_options_schema_version": 4}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["tone_options"] == options
