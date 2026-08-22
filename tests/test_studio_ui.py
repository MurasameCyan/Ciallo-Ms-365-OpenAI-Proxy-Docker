from __future__ import annotations

import re

from m365_copilot_openai_proxy.templates import _ADMIN_HTML, _USER_HTML


def _key(html: str, key: str) -> list[str]:
    return re.findall(rf"{key}:'([^']*)'", html)


def test_admin_and_user_expose_studio_label_and_hint_in_both_languages():
    for html in (_ADMIN_HTML, _USER_HTML):
        assert _key(html, "tool_planning_studio") == [
            "Studio Agent（实验）",
            "Studio Agent (experimental)",
        ]
        zh, en = _key(html, "tool_planning_hint_studio")
        assert zh and en
        for text in (zh, en):
            lowered = text.lower()
            assert "chat completions" in lowered
            assert "router" in lowered
            assert "messages" in lowered
            assert "responses" in lowered
            assert "ready" in lowered or "就绪" in text
            assert "first" in lowered or "首个" in text
            assert "retry" in lowered or "重试" in text


def test_admin_and_user_planning_selects_include_studio_and_keep_auto_default():
    assert '<option value="studio">' in _ADMIN_HTML
    assert "const opts=['auto','native','router','studio'];" in _USER_HTML
    assert "_defaultToolPlanning='auto'" in _USER_HTML
    assert "s.tool_planning_mode||'auto'" in _ADMIN_HTML


def test_admin_account_studio_control_is_secret_input_with_explicit_actions():
    assert "col_studio_agent" in _ADMIN_HTML
    assert 'colspan="8"' in _ADMIN_HTML
    assert 'class="studio-agent-control"' in _ADMIN_HTML
    assert 'data-studio-account-id="' in _ADMIN_HTML
    assert 'class="studio-agent-input" type="password"' in _ADMIN_HTML
    assert 'autocomplete="new-password"' in _ADMIN_HTML
    assert 'class="studio-agent-bind"' in _ADMIN_HTML
    assert 'class="studio-agent-clear"' in _ADMIN_HTML
    assert 'class="studio-agent-status"' in _ADMIN_HTML
    assert 'class="studio-agent-actions"' in _ADMIN_HTML
    assert 'class="studio-agent-primary"' in _ADMIN_HTML
    assert "msg.style.display=message?'block':'none'" in _ADMIN_HTML
    assert 'placeholder="\'+esc(t(\'studio_agent_id_placeholder\'))+\'"' in _ADMIN_HTML
    assert 'title="\'+esc(t(\'studio_agent_id_title\'))+\'"' in _ADMIN_HTML
    assert 'grid-template-columns:minmax(112px,1fr) auto auto' not in _ADMIN_HTML
    assert '\u7ed1\u5b9a/\u66f4\u65b0' in _ADMIN_HTML
    control = _ADMIN_HTML.split('class="studio-agent-control"', 1)[1].split('</div>', 1)[0]
    assert "onclick=" not in control
    assert "value=" not in control


def test_admin_account_studio_ready_flag_and_secret_handling_are_constrained():
    assert "a.studio_agent_ready===true" in _ADMIN_HTML
    assert "a.studio_agent_id" not in _ADMIN_HTML


def test_admin_account_studio_actions_use_encoded_account_url_json_and_text_messages():
    assert "encodeURIComponent(id)" in _ADMIN_HTML
    assert "'/studio-agent'" in _ADMIN_HTML
    assert "JSON.stringify({agent_id:agentId})" in _ADMIN_HTML
    assert "JSON.stringify({agent_id:''})" in _ADMIN_HTML
    assert "adminConfirm(t('confirm_clear_studio_agent'))" in _ADMIN_HTML
    assert ".textContent=" in _ADMIN_HTML
    assert "input.value=''" in _ADMIN_HTML
    assert "loadAccounts()" in _ADMIN_HTML
    assert ".studio-agent-bind" in _ADMIN_HTML
    assert ".studio-agent-clear" in _ADMIN_HTML


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


def test_admin_account_token_and_studio_columns_use_uniform_spacing_and_balanced_rows():
    # Every account cell contributes 7.5px on each side, making a 15px
    # visual gap between adjacent column contents.
    assert '.accounts-table th,.accounts-table td{padding:7.5px!important;box-sizing:border-box}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(2),.accounts-table td:nth-child(2){width:auto;min-width:216px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(7),.accounts-table td:nth-child(7){width:142px}' in _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:840px;max-width:none;table-layout:fixed}' in _ADMIN_HTML
    # Token controls are status-only on row one and three actions on row two.
    assert "const tokenCell='<div class=\"acct-token-control\"><div class=\"acct-token-primary\">'+badge+'</div><div class=\"acct-token-secondary\">" in _ADMIN_HTML
    assert '.acct-token-secondary{grid-template-columns:repeat(3,minmax(0,1fr))}' in _ADMIN_HTML
    # Studio top and bottom rows must have the same 127px content width.
    assert '.studio-agent-control{display:grid;grid-template-rows:auto auto;gap:4px;width:127px;min-width:127px' in _ADMIN_HTML
    assert '.studio-agent-primary{display:grid;grid-template-columns:58px 65px;gap:4px' in _ADMIN_HTML
    assert '.studio-agent-actions{display:grid;grid-template-columns:65px 58px;gap:4px' in _ADMIN_HTML


def test_admin_studio_agent_uses_short_placeholder_and_narrow_input_with_hover_hint():
    assert "studio_agent_id_placeholder:'输入 SA ID'" in _ADMIN_HTML
    assert "studio_agent_id_title:'输入完整 Studio Agent ID'" in _ADMIN_HTML
    assert "studio_agent_id_placeholder:'Enter SA ID'" in _ADMIN_HTML
    assert "studio_agent_id_title:'Enter the full Studio Agent ID'" in _ADMIN_HTML
    assert '.studio-agent-control{display:grid;grid-template-rows:auto auto;gap:4px;width:127px;min-width:127px' in _ADMIN_HTML


def test_admin_cookie_and_studio_columns_use_balanced_spacing():
    assert 'class="cookie-meta"' in _ADMIN_HTML
    assert 'class="cookie-status-tag"' in _ADMIN_HTML
    assert 'class="cookie-refresh-btn"' in _ADMIN_HTML
    assert '.cookie-meta{display:grid;grid-template-rows:auto auto;gap:4px;width:65px' in _ADMIN_HTML
    assert 'class="media-status-list"' in _ADMIN_HTML
    assert 'class="refresh-mode-tag"' in _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:840px;max-width:none;table-layout:fixed}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(4),.accounts-table td:nth-child(4){width:80px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(5),.accounts-table td:nth-child(5){width:74px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(6),.accounts-table td:nth-child(6){width:78px;white-space:nowrap}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(7),.accounts-table td:nth-child(7){width:142px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(8),.accounts-table td:nth-child(8){width:72px}' in _ADMIN_HTML
    assert '.studio-agent-control{display:grid;grid-template-rows:auto auto;gap:4px;width:127px;min-width:127px' in _ADMIN_HTML
    assert '.studio-agent-primary{display:grid;grid-template-columns:58px 65px' in _ADMIN_HTML
    assert '.studio-agent-input{box-sizing:border-box;width:65px' in _ADMIN_HTML
    assert '.studio-agent-actions{display:grid;grid-template-columns:65px 58px' in _ADMIN_HTML


def test_accounts_table_fills_the_view_and_name_absorbs_extra_width():
    """Keep utility columns stable while the name column fills wide screens."""
    css = _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:840px;max-width:none;table-layout:fixed}' in css
    assert css.index('.accounts-table{width:100%') < css.index(
        '.admin-tbl{width:100%;border-collapse:collapse'
    )
    assert '.accounts-table th:nth-child(2),.accounts-table td:nth-child(2){width:auto;min-width:216px}' in css
    assert '.accounts-table th:nth-child(4),.accounts-table td:nth-child(4){width:80px}' in css


def test_admin_account_layout_uses_15px_gaps_and_gives_extra_width_to_name():
    css = _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:840px;max-width:none;table-layout:fixed}' in css
    assert '.accounts-table th:nth-child(2),.accounts-table td:nth-child(2){width:auto;min-width:216px}' in css
    assert '.accounts-table th:nth-child(4),.accounts-table td:nth-child(4){width:80px}' in css
    assert '.cookie-meta{display:grid;grid-template-rows:auto auto;gap:4px;width:65px' in css
    assert '.cookie-refresh-btn{box-sizing:border-box;width:65px' in css
    assert '.acct-token-status{display:inline-flex;width:100%;box-sizing:border-box' in css
    assert '.acct-token-control{display:grid;grid-template-rows:auto auto;gap:4px;width:131px;min-width:131px' in css
    assert '.studio-agent-primary{display:grid;grid-template-columns:58px 65px;gap:4px' in css
    assert '.studio-agent-actions{display:grid;grid-template-columns:65px 58px;gap:4px' in css


def test_admin_users_table_does_not_reserve_a_right_scrollbar_gap():
    # The generic table reserves a 15px stable scrollbar gutter even when the
    # users list has no vertical overflow, leaving a visible strip after 操作.
    assert '.view-users .tbl-scroll{max-height:605px;scrollbar-gutter:auto}' in _ADMIN_HTML
