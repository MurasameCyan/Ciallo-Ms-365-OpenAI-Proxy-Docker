from __future__ import annotations

import re

from m365_copilot_openai_proxy.templates import _USER_HTML

# 默认配置 / 会话管理 / 提示词增强 / 系统提示词 used to be three separate cards, so the
# page was a column of near-empty rounded boxes. They are one card now, split by the
# same divider the two prompt sections already used.

_SECTIONS = (
    ("mode-profile-details", "mode_profile_title"),
    ("my-sessions-details", "my_sessions_title"),
    ("tool-prompt-details", "tool_prompt_title"),
    ("sys-prompt-details", "sys_prompt_title"),
)
_DIVIDER = '<hr style="border:none;border-top:1px solid #334155;margin:1.1rem 0">'


def _settings_card(html: str) -> str:
    start = html.index('<div class="card mode-profile-card">')
    return html[start : html.index('data-i18n="sys_prompt_hint"', start)]


def test_all_four_sections_share_one_card():
    card = _settings_card(_USER_HTML)
    assert '<div class="card' not in card[len('<div class="card mode-profile-card">') :], (
        "a section still opens its own card"
    )
    for element_id, title_key in _SECTIONS:
        assert f'id="{element_id}"' in card, f"#{element_id} is outside the merged card"
        assert f'data-i18n="{title_key}"' in card


def test_sections_are_separated_by_dividers():
    card = _settings_card(_USER_HTML)
    assert card.count(_DIVIDER) == len(_SECTIONS) - 1, (
        f"expected {len(_SECTIONS) - 1} dividers between {len(_SECTIONS)} sections, "
        f"got {card.count(_DIVIDER)}"
    )
    order = [card.index(f'id="{i}"') for i, _k in _SECTIONS]
    assert order == sorted(order), "the sections were reordered"
    for (before, _k1), (after, _k2) in zip(_SECTIONS, _SECTIONS[1:]):
        between = card[card.index(f'id="{before}"') : card.index(f'id="{after}"')]
        assert _DIVIDER in between, f"no divider between #{before} and #{after}"


def test_merged_card_keeps_the_class_its_dropdowns_need():
    # .mode-profile-card is what lets an open glass-select escape overflow:hidden
    # and what pins the menu to the field width -- losing it clips every dropdown
    # in 默认配置 to the card edge.
    assert re.search(
        r"\.mode-profile-card:has\(\.glass-select\.open\)\{[^}]*overflow:visible", _USER_HTML
    )
    assert '<div class="card mode-profile-card">' in _USER_HTML


def test_session_section_is_titled_session_management():
    keys = re.findall(r"my_sessions_title:'([^']*)'", _USER_HTML)
    assert keys == ["会话管理", "Session management"], f"/user session title: {keys}"
    assert "我的会话" not in _USER_HTML, "the old title is still rendered somewhere"
