from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.call_log_store import append_call_log
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_observability import register_admin_observability_routes
from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
from m365_copilot_openai_proxy.template_admin_accounts import _ADMIN_ACCOUNTS_JS
from m365_copilot_openai_proxy.template_admin_copy import _ADMIN_COPY_JS
from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS
from m365_copilot_openai_proxy.template_admin_dialogs import _ADMIN_DIALOGS_JS
from m365_copilot_openai_proxy.template_admin_keys import _ADMIN_KEYS_JS
from m365_copilot_openai_proxy.template_admin_settings_js import _ADMIN_SETTINGS_JS
from m365_copilot_openai_proxy.template_admin_tables import _ADMIN_TABLES_JS


def test_admin_observability_routes_are_registered_by_observability_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_observability_routes)
    assert "/admin/call-log" in paths
    assert "/admin/call-log/clear" in paths
    assert "/admin/image-proxy/events" in paths
    assert "/admin/image-proxy/events/clear" in paths
    assert "/admin/metrics-history" in paths
    assert "/admin/metrics-history/clear" in paths
    assert "/admin/summary" in paths


def test_admin_call_log_returns_version_and_short_circuits_unchanged_payload(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)

    initial = client.get("/admin/call-log").json()
    assert initial["version"] == 0
    assert initial["logs"] == []

    append_call_log(app.state, {"time": "12:00:00", "ts": 1, "api": "chat"})
    changed = client.get("/admin/call-log?version=0").json()
    assert changed["version"] > 0
    assert changed["count"] == 1
    assert changed["logs"] == [{"time": "12:00:00", "ts": 1, "api": "chat"}]

    unchanged = client.get(f"/admin/call-log?version={changed['version']}").json()
    assert unchanged == {
        "version": changed["version"],
        "unchanged": True,
        "count": 1,
        "logs": [],
    }


def test_admin_trend_chart_uses_stable_polyline_rendering_with_breathing_glow():
    start = _ADMIN_HTML.index("function lineChart(points,series){")
    end = _ADMIN_HTML.index("async function loadSummary()", start)
    chart_code = _ADMIN_HTML[start:end]

    assert chart_code.count("<polyline") >= 2
    assert 'attributeName="opacity"' in chart_code
    assert "smoothPath" not in chart_code
    assert "<path" not in chart_code
    assert "drop-shadow" not in chart_code


def test_admin_tone_share_bars_use_breathing_fill_effect():
    start = _ADMIN_HTML.index("async function loadStats()")
    end = _ADMIN_HTML.index("// Expiry warnings", start)
    load_stats_code = _ADMIN_HTML[start:end]

    assert ".tone-share-fill" in _ADMIN_HTML
    assert "@keyframes toneShareBreath" in _ADMIN_HTML
    assert "animation:toneShareBreath" in _ADMIN_HTML
    assert 'class="tone-share-fill"' in load_stats_code


def test_admin_dashboard_javascript_is_split_into_dashboard_module():
    assert "function lineChart(points,series){" in _ADMIN_DASHBOARD_JS
    assert "async function loadStats()" in _ADMIN_DASHBOARD_JS
    assert "async function loadTrend()" in _ADMIN_DASHBOARD_JS
    assert _ADMIN_DASHBOARD_JS in _ADMIN_HTML


def test_admin_dialog_javascript_is_split_into_dialogs_module():
    assert "function adminDialog(message,okOnly)" in _ADMIN_DIALOGS_JS
    assert "const adminAlert=message=>adminDialog(message,true);" in _ADMIN_DIALOGS_JS
    assert "const adminConfirm=message=>adminDialog(message,false);" in _ADMIN_DIALOGS_JS
    assert _ADMIN_DIALOGS_JS in _ADMIN_HTML
    assert _ADMIN_HTML.index("function esc(s)") < _ADMIN_HTML.index(_ADMIN_DIALOGS_JS)
    assert _ADMIN_HTML.index(_ADMIN_DIALOGS_JS) < _ADMIN_HTML.index(_ADMIN_DASHBOARD_JS)


def test_admin_accounts_javascript_is_split_into_accounts_module():
    assert "async function loadAccounts(localOnly=false)" in _ADMIN_ACCOUNTS_JS
    assert "function renderSelectedStatus()" in _ADMIN_ACCOUNTS_JS
    assert "async function submitAccount()" in _ADMIN_ACCOUNTS_JS
    assert "async function batchDeleteAccounts()" in _ADMIN_ACCOUNTS_JS
    assert "const __page={keys:1,accounts:1};" not in _ADMIN_ACCOUNTS_JS
    assert _ADMIN_ACCOUNTS_JS in _ADMIN_HTML


def test_admin_debug_page_includes_media_proxy_records_panel_with_trace_copy():
    assert "API 调用日志" in _ADMIN_HTML
    assert "API调用日志" not in _ADMIN_HTML
    assert "媒体代理日志" in _ADMIN_HTML
    assert "媒体代理记录" not in _ADMIN_HTML
    assert "图片代理诊断" not in _ADMIN_HTML
    assert "抓包调试日志" in _ADMIN_HTML
    assert "抓包调试记录" not in _ADMIN_HTML
    assert "模式抓包对比" not in _ADMIN_HTML
    assert "image-proxy-event-content" in _ADMIN_HTML
    assert "loadImageProxyEvents()" in _ADMIN_HTML
    assert "copyImageProxyTrace" in _ADMIN_HTML
    assert "onclick=\"copyImageProxyTrace" not in _ADMIN_HTML
    assert "data-image-trace" in _ADMIN_HTML
    assert "/admin/image-proxy/events" in _ADMIN_HTML


def test_admin_generated_javascript_passes_node_check(tmp_path):
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = _ADMIN_HTML.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    script_path = tmp_path / "admin.js"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run([node, "--check", str(script_path)], text=True, capture_output=True)

    assert result.returncode == 0, result.stdout + result.stderr


def test_admin_debug_logs_include_copy_all_buttons():
    assert "copyAllCallLog" in _ADMIN_HTML
    assert "copyAllImageProxyEvents" in _ADMIN_HTML
    assert "copyAllCapturePayloads" in _ADMIN_HTML
    assert _ADMIN_HTML.count('data-i18n="copy_all"') == 3
    assert "copy_all:'复制全部'" in _ADMIN_HTML
    assert "copy_all:'Copy all'" in _ADMIN_HTML
    assert '<div class="debug-actions"><button id="copy-call-log-all"' in _ADMIN_HTML
    assert '<div class="debug-actions"><button id="copy-image-proxy-all"' in _ADMIN_HTML
    assert '<div class="debug-actions"><button id="copy-capture-all"' in _ADMIN_HTML


def test_admin_accounts_table_keeps_header_fixed_and_scrolls_rows_without_scrollbar():
    assert ".accounts-main-card{position:relative;padding-bottom:64px;height:450px}" in _ADMIN_HTML
    assert ".accounts-main-card .accounts-table-scroll{height:260px;max-height:260px;overflow-y:auto;overflow-x:hidden;border-radius:8px;scrollbar-width:none;-ms-overflow-style:none;scrollbar-gutter:auto}" in _ADMIN_HTML
    assert ".accounts-main-card .accounts-table-scroll::-webkit-scrollbar{width:0;height:0;display:none}" in _ADMIN_HTML
    assert ".accounts-main-card .accounts-table thead th{position:sticky;top:0;z-index:5;background:var(--card)}" in _ADMIN_HTML
    assert '<div class="tbl-scroll accounts-table-scroll"><table class="admin-tbl accounts-table">' in _ADMIN_ACCOUNTS_JS


def test_admin_table_pagination_javascript_is_split_into_tables_module():
    assert "const __page={keys:1,accounts:1};" in _ADMIN_TABLES_JS
    assert "function _slicePage(arr,which)" in _ADMIN_TABLES_JS
    assert "function _setPage(which,p)" in _ADMIN_TABLES_JS
    assert "function _setPageSize(which,s)" in _ADMIN_TABLES_JS
    assert "function _pageFoot(which,pg)" in _ADMIN_TABLES_JS
    assert _ADMIN_TABLES_JS in _ADMIN_HTML
    assert _ADMIN_HTML.index(_ADMIN_TABLES_JS) < _ADMIN_HTML.index(_ADMIN_ACCOUNTS_JS)


def test_admin_keys_javascript_is_split_into_keys_module():
    assert "let __keys=[];" in _ADMIN_KEYS_JS
    assert "async function loadKeys()" in _ADMIN_KEYS_JS
    assert "function toggleKeyForm(show)" in _ADMIN_KEYS_JS
    assert "async function submitKey()" in _ADMIN_KEYS_JS
    assert "async function batchDeleteKeys()" in _ADMIN_KEYS_JS
    assert "function _fallbackCopy(text)" not in _ADMIN_KEYS_JS
    assert _ADMIN_KEYS_JS in _ADMIN_HTML
    assert _ADMIN_HTML.index(_ADMIN_ACCOUNTS_JS) < _ADMIN_HTML.index(_ADMIN_KEYS_JS)


def test_admin_copy_javascript_is_split_into_copy_module():
    assert "function _fallbackCopy(text)" in _ADMIN_COPY_JS
    assert "function copyText(text,cb)" in _ADMIN_COPY_JS
    assert "function _adminCopyFeedback(btn)" in _ADMIN_COPY_JS
    assert "function copyKey(id,btn)" in _ADMIN_COPY_JS
    assert "function copyPwd(id,btn)" in _ADMIN_COPY_JS
    assert _ADMIN_COPY_JS in _ADMIN_HTML
    assert _ADMIN_HTML.index(_ADMIN_COPY_JS) < _ADMIN_HTML.index(_ADMIN_KEYS_JS)


def test_admin_debug_polling_uses_backend_versions_instead_of_full_json_signatures():
    assert "JSON.stringify(logs)" not in _ADMIN_HTML
    assert "JSON.stringify(ps)" not in _ADMIN_HTML
    assert "__callLogVersion" in _ADMIN_HTML
    assert "__capVersion" in _ADMIN_HTML
    assert "/admin/call-log?version=" in _ADMIN_HTML
    assert "/admin/capture-payload?version=" in _ADMIN_HTML


def test_admin_settings_javascript_is_split_into_settings_module():
    assert "async function loadTone()" in _ADMIN_SETTINGS_JS
    assert "async function saveTone(tone)" in _ADMIN_SETTINGS_JS
    assert "async function loadRuntimeSettings()" in _ADMIN_SETTINGS_JS
    assert "async function saveRuntimeSettings(btnId)" in _ADMIN_SETTINGS_JS
    assert "async function loadToolPrompt()" in _ADMIN_SETTINGS_JS
    assert "async function saveToolPrompt()" in _ADMIN_SETTINGS_JS
    assert "async function resetToolPrompt()" in _ADMIN_SETTINGS_JS
    assert "let __systemPromptDefault='';" in _ADMIN_SETTINGS_JS
    assert "async function loadSystemPrompt()" in _ADMIN_SETTINGS_JS
    assert "async function unlockSystemPrompt()" in _ADMIN_SETTINGS_JS
    assert "async function saveSystemPrompt()" in _ADMIN_SETTINGS_JS
    assert "async function resetSystemPrompt()" in _ADMIN_SETTINGS_JS
    assert _ADMIN_SETTINGS_JS in _ADMIN_HTML
    assert _ADMIN_HTML.index("let __runtimeSettings={};") < _ADMIN_HTML.index(_ADMIN_SETTINGS_JS)
