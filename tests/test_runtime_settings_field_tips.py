from __future__ import annotations

import re

from m365_copilot_openai_proxy.templates import _ADMIN_HTML

# The long caveats in "Runtime Settings (Global Template)" used to render as
# paragraphs under their inputs (the cloud-reclaim one ran five lines), which made
# the column they sat in taller than the other three and knocked every row of the
# grid out of alignment. They are now amber (!) icons at the right end of their own
# label row, text on hover -- same pattern as the session cleanup warning. The tool
# planning row joined them once its three option labels lost their parentheticals.

_TIPS = (
    ("runtime-cloud-cleanup-idle-hours", "cloud_cleanup_idle_hours_label", ("auto_cleanup_hint",)),
    ("runtime-proxy-url", "proxy_url_label", ("proxy_url_hint",)),
    (
        "runtime-tool-planning-mode",
        "tool_planning_label",
        (
            "tool_planning_hint_auto",
            "tool_planning_hint_native",
            "tool_planning_hint_router",
            "tool_planning_hint_studio",
        ),
    ),
)


def _field(html: str, control_id: str) -> str:
    marker = '<label class="runtime-field-label"'
    for chunk in html.split(marker):
        if f'id="{control_id}"' in chunk:
            return marker + chunk.split("</label>")[0]
    raise AssertionError(f"#{control_id} is not inside a .runtime-field-label")


def test_long_hints_live_only_in_a_hover_bubble():
    for control_id, _label_key, hint_keys in _TIPS:
        field = _field(_ADMIN_HTML, control_id)
        bubble_at = field.index('class="field-tip-bubble"')
        for hint_key in hint_keys:
            holders = re.findall(rf'data-i18n="{hint_key}"', _ADMIN_HTML)
            assert len(holders) == 1, f"{hint_key} is rendered {len(holders)} times"
            assert field.index(f'data-i18n="{hint_key}"') > bubble_at, (
                f"{hint_key} is shown as body text instead of inside the hover bubble"
            )
    # The copy itself is untouched in both languages -- it moved, it was not cut.
    assert "请谨慎开启。" in _ADMIN_HTML
    assert "so enable it deliberately." in _ADMIN_HTML
    assert "本地 CDP 始终直连，不走代理。" in _ADMIN_HTML
    assert "Local CDP always bypasses the proxy." in _ADMIN_HTML


def test_icon_sits_at_the_right_end_of_the_label_row():
    for control_id, label_key, hint_keys in _TIPS:
        field = _field(_ADMIN_HTML, control_id)
        assert 'class="field-row"' in field, f"{control_id}: label and icon are not one row"
        label_at = field.index(f'data-i18n="{label_key}"')
        tip_at = field.index('class="field-tip')
        control = re.search(r"<(input|select)", field)
        assert control, f"{control_id}: field has no control"
        assert label_at < tip_at < control.start(), (
            f"{control_id}: the (!) icon left the label row (expected after the label "
            f"text, before the input)"
        )
        for hint_key in hint_keys:
            assert field.index(hint_key) > tip_at, (
                f"{control_id}: the bubble is not inside the icon"
            )


def test_tip_icon_is_amber_hoverable_and_reachable_without_a_pointer():
    assert re.search(r"\.field-tip\{[^}]*margin-left:auto", _ADMIN_HTML), (
        ".field-tip is no longer pinned to the right end of its row"
    )
    assert re.search(r"\.field-tip\{[^}]*#fbbf24", _ADMIN_HTML), ".field-tip icon is not amber"
    assert re.search(r"\.field-tip\{[^}]*cursor:help", _ADMIN_HTML), (
        ".field-tip does not advertise its hover tooltip"
    )
    assert '.field-tip:before{content:"!"}' in _ADMIN_HTML, "the icon is not an exclamation mark"
    # Keyboard users get the same text: every trigger is focusable and :focus reveals.
    triggers = re.findall(r'<span class="field-tip(?: [^"]*)?"[^>]*>', _ADMIN_HTML)
    assert len(triggers) == len(_TIPS), f"expected {len(_TIPS)} tip triggers, got {triggers}"
    for trigger in triggers:
        assert 'tabindex="0"' in trigger, f"tip trigger is not focusable: {trigger}"
    assert ".field-tip:focus .field-tip-bubble" in _ADMIN_HTML


def test_bubble_is_hidden_until_hover_and_not_clipped_by_the_card():
    bubble = re.search(r"\.field-tip-bubble\{([^}]*)\}", _ADMIN_HTML)
    assert bubble, ".field-tip-bubble has no rule"
    assert "position:absolute" in bubble.group(1), "the bubble takes layout space when idle"
    assert "opacity:0" in bubble.group(1), "the bubble is visible without hovering"
    # Hidden by opacity, not visibility/display, so screen readers still read it.
    assert "visibility:hidden" not in bubble.group(1)
    assert "display:none" not in bubble.group(1)
    assert ".field-tip:hover .field-tip-bubble" in _ADMIN_HTML
    assert ".card:has(.field-tip:hover)" in _ADMIN_HTML, (
        "the card still clips the bubble at its rounded edge"
    )


def test_bubble_is_anchored_to_its_field_so_it_cannot_hang_off_the_card():
    # Anchored to the icon it was 320px wide and opened to one side, which put it
    # ~35px past the card edge whenever its field wrapped into the first column
    # (right-anchored) -- and mirroring the anchor just moved the problem to the
    # last column. Spanning its own grid cell fits at every column count.
    assert re.search(
        r"\.runtime-settings-grid \.runtime-field-label\{[^}]*position:relative", _ADMIN_HTML
    ), "the bubble has no field to anchor to"
    assert not re.search(r"\.field-tip\{[^}]*position:relative", _ADMIN_HTML), (
        "the icon is the containing block again, so the bubble sizes to the icon"
    )
    bubble = re.search(r"\.field-tip-bubble\{([^}]*)\}", _ADMIN_HTML).group(1)
    assert "left:0" in bubble and "right:0" in bubble, "the bubble no longer spans its cell"
    # Tool planning is the last row of the tallest column, so down would leave the card.
    assert ".field-tip.tip-up .field-tip-bubble{top:auto;bottom:calc(100% + 8px)}" in _ADMIN_HTML
    assert 'class="field-tip tip-up"' in _field(_ADMIN_HTML, "runtime-tool-planning-mode")


def test_runtime_grid_flows_all_four_groups_instead_of_pinning_three_columns():
    grid = re.search(r"\.runtime-settings-grid\{([^}]*)\}", _ADMIN_HTML)
    assert grid, ".runtime-settings-grid has no rule"
    assert "repeat(auto-fit,minmax(" in grid.group(1), (
        "the grid pins a fixed column count again -- the fourth group of fields then "
        "wraps into a single narrow column under the first"
    )
    assert "repeat(3," not in grid.group(1)
    markup = re.search(r'<div class="runtime-settings-grid"[^>]*>', _ADMIN_HTML)
    assert markup and "repeat(auto-fit,minmax(" in markup.group(0), (
        "the inline fallback style still disagrees with the stylesheet"
    )


def test_save_button_of_the_card_localizes():
    # data-i18n="save" was in the markup with no `save` key in either admin
    # dictionary, so both admin save buttons stayed Chinese in English mode
    # (applyLang leaves an element alone when its key is missing).
    assert 'data-i18n="save"' in _ADMIN_HTML
    keys = re.findall(r"[^a-z_](save:'[^']*')", _ADMIN_HTML)
    assert keys == ["save:'保存'", "save:'Save'"], f"admin `save` key: {keys}"
