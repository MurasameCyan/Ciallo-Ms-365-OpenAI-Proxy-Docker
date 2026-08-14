from __future__ import annotations

import json
import logging

import pytest

from m365_copilot_openai_proxy import runtime_settings


_DEFAULT_OPTIONS = [
    {"model": "copilot-reasoning", "mode": "reasoning", "status": "experimental"},
    {"model": "copilot-thinking", "mode": "reasoning", "status": "experimental"},
    {"model": "copilot-research", "mode": "research", "status": "experimental"},
    {"model": "copilot-coco", "mode": "coco", "status": "experimental"},
    {"model": "copilot-search", "mode": "search", "status": "experimental"},
    {"model": "copilot", "mode": "smart", "status": "stable"},
    {"model": "copilot-smart", "mode": "smart", "status": "stable"},
    {"model": "copilot-chat", "mode": "chat", "status": "experimental"},
    {"model": "copilot-study", "mode": "study", "status": "experimental"},
]

_PREVIOUS_DEFAULT_OPTIONS = [
    {"model": "copilot", "mode": "smart", "status": "stable"},
    {"model": "copilot-smart", "mode": "smart", "status": "stable"},
    {"model": "copilot-reasoning", "mode": "reasoning", "status": "experimental"},
    {"model": "copilot-thinking", "mode": "reasoning", "status": "experimental"},
    {"model": "copilot-search", "mode": "search", "status": "experimental"},
    {"model": "copilot-study", "mode": "study", "status": "experimental"},
    {"model": "copilot-chat", "mode": "chat", "status": "experimental"},
    {"model": "copilot-research", "mode": "research", "status": "experimental"},
    {"model": "copilot-coco", "mode": "coco", "status": "experimental"},
]

_LEGACY_DEFAULT_OPTIONS = [
    *_PREVIOUS_DEFAULT_OPTIONS[:7],
    {"model": "copilot-default", "mode": "default", "status": "experimental"},
    _PREVIOUS_DEFAULT_OPTIONS[7],
    {
        "model": "copilot-computer-use",
        "mode": "computer_use",
        "status": "experimental",
    },
    _PREVIOUS_DEFAULT_OPTIONS[8],
]


def test_consumer_mode_defaults_are_canonical():
    assert runtime_settings._RUNTIME_SETTINGS_DEFAULTS["consumer_mode_options"] == _DEFAULT_OPTIONS


def test_consumer_mode_normalizer_accepts_three_column_text_and_json():
    normalize = runtime_settings.normalize_consumer_mode_options

    assert normalize(" Alpha | custom-mode | STABLE\nBeta | reasoning | experimental ") == [
        {"model": "alpha", "mode": "custom-mode", "status": "stable"},
        {"model": "beta", "mode": "reasoning", "status": "experimental"},
    ]
    assert normalize([
        {
            "model": " Alpha ",
            "mode": " custom-mode ",
            "status": " STABLE ",
            "ignored": "compatibility",
        },
    ]) == [
        {"model": "alpha", "mode": "custom-mode", "status": "stable"},
    ]


def test_consumer_mode_normalizer_migrates_two_column_entries():
    normalize = runtime_settings.normalize_consumer_mode_options

    assert normalize(" Smart-Alias | smart\nDeep-Alias | reasoning") == [
        {"model": "smart-alias", "mode": "smart", "status": "stable"},
        {"model": "deep-alias", "mode": "reasoning", "status": "experimental"},
    ]
    assert normalize([
        {"model": "json-smart", "mode": "smart"},
        {"model": "json-chat", "mode": "chat"},
    ]) == [
        {"model": "json-smart", "mode": "smart", "status": "stable"},
        {"model": "json-chat", "mode": "chat", "status": "experimental"},
    ]


def test_consumer_mode_normalizer_normalizes_model_and_status_but_preserves_mode():
    assert runtime_settings.normalize_consumer_mode_options([
        {"model": " Mixed-Case ", "mode": " ReASoning ", "status": " EXPERIMENTAL "},
    ]) == [
        {"model": "mixed-case", "mode": "ReASoning", "status": "experimental"},
    ]


def test_consumer_mode_normalizer_allows_multiple_models_for_one_mode():
    assert runtime_settings.normalize_consumer_mode_options([
        {"model": "deep-one", "mode": "reasoning"},
        {"model": "deep-two", "mode": "reasoning"},
    ]) == [
        {"model": "deep-one", "mode": "reasoning", "status": "experimental"},
        {"model": "deep-two", "mode": "reasoning", "status": "experimental"},
    ]


def test_consumer_mode_normalizer_empty_list_restores_defaults():
    restored = runtime_settings.normalize_consumer_mode_options([])

    assert restored == _DEFAULT_OPTIONS
    assert restored is not runtime_settings._RUNTIME_SETTINGS_DEFAULTS["consumer_mode_options"]
    assert all(
        actual is not expected
        for actual, expected in zip(
            restored,
            runtime_settings._RUNTIME_SETTINGS_DEFAULTS["consumer_mode_options"],
        )
    )


@pytest.mark.parametrize("value", [None, 1, True, {"model": "x", "mode": "smart"}])
def test_consumer_mode_normalizer_rejects_invalid_top_level_types(value):
    with pytest.raises(ValueError, match="must be a string or list"):
        runtime_settings.normalize_consumer_mode_options(value)


@pytest.mark.parametrize(
    "value, message",
    [
        ("", "must contain at least one entry"),
        ("  \n\t", "must contain at least one entry"),
        ("model-only", "line 1: expected 2 or 3"),
        ("ok | smart\nbad | mode | stable | extra", "line 2: expected 2 or 3"),
    ],
)
def test_consumer_mode_normalizer_rejects_blank_text_and_bad_column_counts(value, message):
    with pytest.raises(ValueError, match=message):
        runtime_settings.normalize_consumer_mode_options(value)


@pytest.mark.parametrize(
    "value, message",
    [
        (["not-an-object"], "entry 1: must be an object"),
        ([{"mode": "smart"}], "entry 1: model is required"),
        ([{"model": "x"}], "entry 1: mode is required"),
        ([{"model": 1, "mode": "smart"}], "entry 1: model must be a string"),
        ([{"model": "x", "mode": False}], "entry 1: mode must be a string"),
        ([{"model": "x", "mode": "smart", "status": 1}], "entry 1: status must be a string"),
    ],
)
def test_consumer_mode_normalizer_rejects_invalid_entries_and_field_types(value, message):
    with pytest.raises(ValueError, match=message):
        runtime_settings.normalize_consumer_mode_options(value)


@pytest.mark.parametrize(
    "value, message",
    [
        (" | smart", "line 1: model must not be empty"),
        ("model | ", "line 1: mode must not be empty"),
        ("model | smart | preview", "line 1: status must be stable or experimental"),
        (
            [
                {"model": " Duplicate ", "mode": "smart"},
                {"model": "duplicate", "mode": "reasoning"},
            ],
            "entry 2: duplicate model 'duplicate'",
        ),
    ],
)
def test_consumer_mode_normalizer_rejects_blank_fields_invalid_status_and_duplicate_models(
    value, message,
):
    with pytest.raises(ValueError, match=message):
        runtime_settings.normalize_consumer_mode_options(value)


@pytest.mark.parametrize(
    "value, message",
    [
        ([{"model": "m" * 81, "mode": "smart"}], "entry 1: model must be at most 80 characters"),
        ([{"model": "model", "mode": "m" * 81}], "entry 1: mode must be at most 80 characters"),
        (
            [{"model": "model", "mode": "smart", "status": "s" * 81}],
            "entry 1: status must be at most 80 characters",
        ),
        (
            [{"model": f"model-{index}", "mode": "smart"} for index in range(41)],
            "maximum 40 entries",
        ),
    ],
)
def test_consumer_mode_normalizer_rejects_field_and_entry_limits(value, message):
    with pytest.raises(ValueError, match=message):
        runtime_settings.normalize_consumer_mode_options(value)


def test_read_runtime_settings_migrates_legacy_consumer_modes(tmp_path):
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({
            "consumer_mode_options": [
                {"model": "smart-alias", "mode": "smart"},
                {"model": "deep-alias", "mode": "reasoning"},
            ],
        }),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["consumer_mode_options"] == [
        {"model": "smart-alias", "mode": "smart", "status": "stable"},
        {"model": "deep-alias", "mode": "reasoning", "status": "experimental"},
    ]


def test_read_runtime_settings_migrates_exact_legacy_default_catalog(tmp_path):
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"consumer_mode_options": _LEGACY_DEFAULT_OPTIONS}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["consumer_mode_options"] == _DEFAULT_OPTIONS


def test_read_runtime_settings_migrates_exact_previous_default_catalog(tmp_path):
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"consumer_mode_options": _PREVIOUS_DEFAULT_OPTIONS}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["consumer_mode_options"] == _DEFAULT_OPTIONS


def test_read_runtime_settings_preserves_custom_catalog_with_legacy_model_ids(tmp_path):
    custom_options = [
        *_LEGACY_DEFAULT_OPTIONS,
        {"model": "private-preview", "mode": "preview", "status": "experimental"},
    ]
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"consumer_mode_options": custom_options}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["consumer_mode_options"] == custom_options


@pytest.mark.parametrize("base_options", [_LEGACY_DEFAULT_OPTIONS, _PREVIOUS_DEFAULT_OPTIONS])
def test_read_runtime_settings_preserves_reordered_default_catalog(tmp_path, base_options):
    custom_options = [*base_options]
    custom_options[0], custom_options[1] = custom_options[1], custom_options[0]
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"consumer_mode_options": custom_options}),
        encoding="utf-8",
    )

    settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["consumer_mode_options"] == custom_options


@pytest.mark.parametrize(
    "invalid_options",
    [
        {"model": "wrong-container", "mode": "smart"},
        [{"model": "blank-mode", "mode": ""}],
        [{"model": "bad-status", "mode": "smart", "status": "preview"}],
        [
            {"model": "would-have-survived", "mode": "smart"},
            {"model": "invalid", "mode": 1},
        ],
    ],
)
def test_read_runtime_settings_falls_back_whole_consumer_field_and_warns(
    tmp_path, caplog, invalid_options,
):
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({
            "model_alias": "preserved-alias",
            "consumer_mode_options": invalid_options,
        }),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        settings = runtime_settings._read_runtime_settings(str(tmp_path))

    assert settings["consumer_mode_options"] == _DEFAULT_OPTIONS
    assert settings["model_alias"] == "preserved-alias"
    assert "consumer_mode_options" in caplog.text
    assert "built-in defaults" in caplog.text
