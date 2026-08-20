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
