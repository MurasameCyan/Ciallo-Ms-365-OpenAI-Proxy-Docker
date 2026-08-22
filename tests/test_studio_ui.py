from __future__ import annotations

import re

from m365_copilot_openai_proxy.templates import _ADMIN_HTML, _USER_HTML


def _key(html: str, key: str) -> list[str]:
    return re.findall(rf"{key}:'([^']*)'", html)


def test_admin_and_user_expose_studio_label_and_hint_in_both_languages():
    expected_zh = (
        "m365账户使用自己的 Studio Agent，未就绪或首个输出前不可用时回退Router。"
        "首个文本或工具增量发出后若失败，不再重试。"
    )
    expected_en = (
        "M365 accounts use their own Studio Agent. When it is not ready or unavailable "
        "before the first output, it falls back to Router. After the first text or tool "
        "delta, it does not retry."
    )
    for html in (_ADMIN_HTML, _USER_HTML):
        assert _key(html, "tool_planning_studio") == [
            "Studio Agent",
            "Studio Agent",
        ]
        assert _key(html, "tool_planning_hint_studio") == [expected_zh, expected_en]


def test_admin_and_user_planning_selects_include_studio_and_keep_auto_default():
    assert '<option value="studio">' in _ADMIN_HTML
    assert "const opts=['auto','native','router','studio'];" in _USER_HTML
    assert "_defaultToolPlanning='auto'" in _USER_HTML
    assert "s.tool_planning_mode||'auto'" in _ADMIN_HTML


def test_admin_account_table_hides_studio_binding_column_after_auto_discovery():
    assert "col_studio_agent" not in _ADMIN_HTML
    assert 'class="studio-agent-control"' not in _ADMIN_HTML
    assert 'class="studio-agent-input"' not in _ADMIN_HTML
    assert 'class="studio-agent-bind"' not in _ADMIN_HTML
    assert 'class="studio-agent-clear"' not in _ADMIN_HTML
    assert 'data-studio-account-id="' not in _ADMIN_HTML
    assert '<td colspan="7"' in _ADMIN_HTML


def test_admin_account_table_does_not_render_studio_agent_credentials():
    assert "a.studio_agent_id" not in _ADMIN_HTML
    assert "a.studio_agent_ready" not in _ADMIN_HTML


def test_admin_account_table_keeps_account_actions_without_studio_controls():
    assert "loadAccounts()" in _ADMIN_HTML
    assert "class=\"acct-actions-cell\"" in _ADMIN_HTML


def test_admin_account_media_uses_status_colored_tags_without_label_rows():
    assert "class=\"media-status-tag\"" in _ADMIN_HTML
    assert "mkMedia" not in _ADMIN_HTML
    assert "media_image" in _ADMIN_HTML
    assert "media_attach" in _ADMIN_HTML


def test_admin_account_token_controls_are_two_fixed_rows():
    assert 'class="acct-token-control"' in _ADMIN_HTML
    assert 'class="acct-token-primary"' in _ADMIN_HTML
    assert 'class="acct-token-secondary"' in _ADMIN_HTML
    assert 'class="acct-token-actions"' not in _ADMIN_HTML


def test_admin_account_columns_use_uniform_spacing_and_balanced_rows():
    # Every account cell contributes 7.5px on each side, making a 15px
    # visual gap between adjacent column contents.
    assert '.accounts-table th,.accounts-table td{padding:7.5px!important;box-sizing:border-box}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(2),.accounts-table td:nth-child(2){width:auto;min-width:216px}' in _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:698px;max-width:none;table-layout:fixed}' in _ADMIN_HTML
    # Token controls are status-only on row one and three actions on row two.
    assert "const tokenCell='<div class=\"acct-token-control\"><div class=\"acct-token-primary\">'+badge+'</div><div class=\"acct-token-secondary\">" in _ADMIN_HTML
    assert '.acct-token-secondary{grid-template-columns:repeat(3,minmax(0,1fr))}' in _ADMIN_HTML


def test_admin_cookie_and_account_columns_use_balanced_spacing():
    assert 'class="cookie-meta"' in _ADMIN_HTML
    assert 'class="cookie-status-tag"' in _ADMIN_HTML
    assert 'class="cookie-refresh-btn"' in _ADMIN_HTML
    assert '.cookie-meta{display:grid;grid-template-rows:auto auto;gap:4px;width:65px' in _ADMIN_HTML
    assert 'class="media-status-list"' in _ADMIN_HTML
    assert 'class="refresh-mode-tag"' in _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:698px;max-width:none;table-layout:fixed}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(4),.accounts-table td:nth-child(4){width:80px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(5),.accounts-table td:nth-child(5){width:74px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(6),.accounts-table td:nth-child(6){width:78px;white-space:nowrap}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(7),.accounts-table td:nth-child(7){width:72px}' in _ADMIN_HTML


def test_accounts_table_fills_the_view_and_name_absorbs_extra_width():
    """Keep utility columns stable while the name column fills wide screens."""
    css = _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:698px;max-width:none;table-layout:fixed}' in css
    assert css.index('.accounts-table{width:100%') < css.index(
        '.admin-tbl{width:100%;border-collapse:collapse'
    )
    assert '.accounts-table th:nth-child(2),.accounts-table td:nth-child(2){width:auto;min-width:216px}' in css
    assert '.accounts-table th:nth-child(4),.accounts-table td:nth-child(4){width:80px}' in css


def test_admin_account_layout_uses_15px_gaps_and_gives_extra_width_to_name():
    css = _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:698px;max-width:none;table-layout:fixed}' in css
    assert '.accounts-table th:nth-child(2),.accounts-table td:nth-child(2){width:auto;min-width:216px}' in css
    assert '.accounts-table th:nth-child(4),.accounts-table td:nth-child(4){width:80px}' in css
    assert '.cookie-meta{display:grid;grid-template-rows:auto auto;gap:4px;width:65px' in css
    assert '.cookie-refresh-btn{box-sizing:border-box;width:65px' in css
    assert '.acct-token-status{display:inline-flex;width:100%;box-sizing:border-box' in css
    assert '.acct-token-control{display:grid;grid-template-rows:auto auto;gap:4px;width:131px;min-width:131px' in css


def test_admin_users_table_does_not_reserve_a_right_scrollbar_gap():
    # The generic table reserves a 15px stable scrollbar gutter even when the
    # users list has no vertical overflow, leaving a visible strip after 操作.
    assert '.view-users .tbl-scroll{max-height:605px;scrollbar-gutter:auto}' in _ADMIN_HTML
