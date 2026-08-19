from __future__ import annotations

import re

from m365_copilot_openai_proxy.templates import _ADMIN_HTML
from m365_copilot_openai_proxy.tone_options import TOOL_PLANNING_MODES

# The three "Tool planning" options each carried their explanation in parentheses,
# which made the closed select wider than its grid column and unreadable at a
# glance. The explanations now live in one hover bubble on the row, and the router
# option is named 路由模式 (it selects a mode, not a single extra turn).


def _key(html: str, key: str) -> list[str]:
    return re.findall(rf"{key}:'([^']*)'", html)


def test_option_labels_are_bare_names():
    assert _key(_ADMIN_HTML, "tool_planning_auto") == ["自动", "Auto"]
    assert _key(_ADMIN_HTML, "tool_planning_native") == ["内联契约", "Inline contract"]
    assert _key(_ADMIN_HTML, "tool_planning_router") == ["路由模式", "Router"]


def test_the_old_router_turn_wording_is_gone_everywhere():
    # Including the wrench tooltips, which pointed users at the setting by name.
    assert "路由轮" not in _ADMIN_HTML, "a label still calls the mode 路由轮"
    assert "路由模式" in _key(_ADMIN_HTML, "tc_tip_flaky")[0], (
        "the flaky-tool tooltip no longer names the setting it tells users to change"
    )


def test_hint_gives_each_mode_its_own_line_in_both_languages():
    # One paragraph holding all three explanations was a wall of text in a bubble
    # this narrow, so every mode is its own block, introduced by its option label.
    for mode in ("auto", "native", "router"):
        zh, en = _key(_ADMIN_HTML, f"tool_planning_hint_{mode}")
        assert zh and en, f"tool_planning_hint_{mode} is missing a translation"
        for name in ("自动", "内联契约", "路由模式", "Auto", "Inline contract", "Router"):
            assert not zh.startswith(name) and not en.startswith(name), (
                f"tool_planning_hint_{mode} repeats the mode name that the bold "
                f"<b data-i18n=tool_planning_{mode}> in front of it already shows"
            )
        line = (
            f'<span class="tip-line"><b data-i18n="tool_planning_{mode}">'
        )
        assert line in _ADMIN_HTML, f"{mode} has no line of its own in the bubble"
        assert _ADMIN_HTML.index(line) < _ADMIN_HTML.index(f'data-i18n="tool_planning_hint_{mode}"')
    assert ".field-tip-bubble .tip-line{display:block}" in _ADMIN_HTML, (
        "the mode lines run together as one paragraph again"
    )
    # Every mode the backend accepts is described, so the select cannot outgrow it.
    assert len(TOOL_PLANNING_MODES) == 3, (
        f"a new planning mode ({sorted(TOOL_PLANNING_MODES)}) needs a line in the hint"
    )


def test_model_alias_field_is_gone_from_the_runtime_card():
    # The alias is still stored and still honoured; it just has no global input any
    # more (saveRuntimeSettings spreads the loaded settings, so dropping the input
    # keeps whatever value was saved instead of blanking it).
    assert "model_alias" not in _ADMIN_HTML, "the global model alias field came back"
    assert "runtime-model-alias" not in _ADMIN_HTML
    assert "__runtimeSettings" in _ADMIN_HTML, (
        "the save payload no longer starts from the loaded settings, so fields "
        "without an input would be wiped"
    )
