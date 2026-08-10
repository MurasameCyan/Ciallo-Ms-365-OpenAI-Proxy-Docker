from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.template_user import _USER_HTML


def _extract_function(name: str) -> str:
    match = re.search(rf"function {name}\([^)]*\)\{{[\s\S]*?\n\}}", _USER_HTML)
    assert match, f"{name} helper is missing"
    return match.group(0)


def test_token_only_account_is_displayed_as_unbound_token_state():
    helper = _extract_function("boundAccountName")
    script = textwrap.dedent(
        f"""
        const assert = require('assert');
        const labels = {{status_unknown: '未知', account_none: '无', account_none_token: '无 (Token)'}};
        function t(key) {{ return labels[key] || key; }}
        {helper}

        assert.strictEqual(
          boundAccountName({{name: 'Microsoft User', email: 'user@example.com', id: 'acct1', binding_state: 'token_only', has_token: true, cookie_valid: false}}),
          '无 (Token)'
        );
        assert.strictEqual(
          boundAccountName({{name: 'Microsoft User', email: 'user@example.com', id: 'acct1', has_token: false, cookie_valid: false}}),
          '无'
        );
        assert.strictEqual(
          boundAccountName({{name: 'Microsoft User', email: 'user@example.com', id: 'acct1', has_token: true, cookie_valid: true}}),
          'Microsoft User'
        );
        """
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout


def test_bound_account_pill_uses_token_only_display_name():
    assert "boundAccountName(d.account)" in _USER_HTML
    assert "t('bound_account')+': '+esc(boundAccountName(d.account))" in _USER_HTML
    assert "t('bound_account')+': '+boundAccountName(d.account)" not in _USER_HTML
    assert "t('bound_account')+': '+(d.account.name||d.account.id)" not in _USER_HTML


def test_token_only_copy_does_not_describe_token_as_binding():
    assert "无 (Token)" in _USER_HTML
    assert "自动创建并绑定" not in _USER_HTML
    assert "created and bound automatically" not in _USER_HTML
