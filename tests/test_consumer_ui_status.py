from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.template_admin_accounts import _ADMIN_ACCOUNTS_JS
from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS
from m365_copilot_openai_proxy.template_admin_keys import _ADMIN_KEYS_JS
from m365_copilot_openai_proxy.template_user_account_js import _USER_ACCOUNT_JS


_NODE = shutil.which("node")


def _run_node(tmp_path: Path, script: str) -> None:
    if _NODE is None:
        pytest.skip("node is required for inline UI behavior tests")
    path = tmp_path / "ui-behavior.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (result.stderr or "") + (result.stdout or "")


def _extract_js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace = source.index("{", start)
    depth = 0
    quote = ""
    escaped = False
    i = brace
    while i < len(source):
        ch = source[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
        elif ch in {"'", '"', "`"}:
            quote = ch
        elif ch == "/" and i + 1 < len(source) and source[i + 1] == "/":
            newline = source.find("\n", i + 2)
            i = len(source) if newline < 0 else newline
            continue
        elif ch == "/" and i + 1 < len(source) and source[i + 1] == "*":
            end = source.find("*/", i + 2)
            i = len(source) if end < 0 else end + 2
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"unterminated JS function: {name}")


def _admin_status_helpers() -> str:
    return "\n".join(
        _extract_js_function(_ADMIN_DASHBOARD_JS, name)
        for name in ("fmtHMS", "fmtTs", "liveTokenStatus", "liveCookieValid")
    )


def _admin_accounts_render_script(assertions: str) -> str:
    return "\n".join(
        [
            "const assert=require('assert');",
            "const localStorage={getItem(){return ''},setItem(){}};",
            "const box={innerHTML:'',querySelectorAll(){return []}};",
            "const document={getElementById(id){return id==='accounts-content'?box:null},querySelectorAll(){return []}};",
            "const labels={valid_short:'OK',invalid_short:'Bad',cookie_valid_short:'OK',cookie_invalid_short:'Bad',refresh_auto:'Auto',refresh_manual:'Manual',refresh_unavailable:'Unavailable',provider_consumer:'Personal'};",
            "function t(key){return labels[key]||key}",
            "function esc(value){return String(value??'')}",
            "function _slicePage(items){return {items}}",
            "function _pageFoot(){return ''}",
            "function initGlassSelect(){}",
            "function renderDashboard(){}",
            _admin_status_helpers(),
            _ADMIN_ACCOUNTS_JS,
            "__accounts=[{id:'acct_consumer',name:'Personal Alice',email:'alice@example.com',provider:'consumer',token_source:'manual',cookie_valid:true,cookie_updated_at:0,cookie_expires_at:0,token_status:{valid:true,expires_at:null,seconds_remaining:0},bound_names:[],key_count:1,has_designer_auth:false,has_media_auth:false}];",
            "(async()=>{await loadAccounts(true);" + assertions + "})().catch(e=>{console.error(e);process.exit(1)});",
        ]
    )


def test_admin_consumer_token_omits_zero_countdown(tmp_path: Path):
    _run_node(
        tmp_path,
        _admin_accounts_render_script(
            "assert.ok(box.innerHTML.includes('Personal Alice'));"
            "assert.ok(!box.innerHTML.includes('00:00:00'),box.innerHTML);"
        ),
    )


def test_admin_consumer_refresh_mode_is_automatic(tmp_path: Path):
    _run_node(
        tmp_path,
        _admin_accounts_render_script(
            "assert.ok(box.innerHTML.includes('>Auto</span>'),box.innerHTML);"
            "assert.ok(!box.innerHTML.includes('>Manual</span>'),box.innerHTML);"
        ),
    )


def test_admin_live_token_status_parses_iso_expiry(tmp_path: Path):
    script = "\n".join(
        [
            "const assert=require('assert');",
            _extract_js_function(_ADMIN_DASHBOARD_JS, "liveTokenStatus"),
            "const expiresAt=new Date(Date.now()+120000).toISOString();",
            "const status=liveTokenStatus({valid:true,expires_at:expiresAt,seconds_remaining:0,_loaded_at:Date.now()/1000});",
            "assert.ok(status.seconds_remaining>=118&&status.seconds_remaining<=120,JSON.stringify(status));",
        ]
    )
    _run_node(tmp_path, script)


def _user_status_script(assertions: str) -> str:
    return "\n".join(
        [
            "const assert=require('assert');",
            "let userTimeZone='';",
            "const elements={'account-status-panel':{innerHTML:''},'account-info':{innerHTML:''},'account-console-actions':{innerHTML:''}};",
            "const document={getElementById(id){return elements[id]||null},querySelectorAll(){return []}};",
            "const labels={status_unknown:'Unknown',status_account:'Account',status_login:'Login',status_refresh:'Refresh',status_valid:'Valid',status_remaining:'Remaining',status_expire:'Expires',account_none:'None',account_none_token:'None (Token)',bound_account:'Bound',token_valid:'Valid',token_invalid:'Invalid',remaining:'Remaining',logout:'Logout',unbind_account:'Unbind',change_password:'Change password',console_logout:'Console logout'};",
            "function t(key){return labels[key]||key}",
            "function esc(value){return String(value??'')}",
            _USER_ACCOUNT_JS,
            "const account={id:'acct_consumer',name:'Personal Alice',email:'alice@example.com',provider:'consumer',token_source:'manual',binding_state:'cookie',cookie_valid:true,has_token:false,token_status:{valid:true,expires_at:null,seconds_remaining:0}};",
            assertions,
        ]
    )


def test_user_consumer_unknown_expiry_never_renders_zero_countdown(tmp_path: Path):
    _run_node(
        tmp_path,
        _user_status_script(
            "renderAccountInfo({account});"
            "assert.ok(elements['account-status-panel'].innerHTML.includes('<span>Remaining</span><b>Unknown</b>'),elements['account-status-panel'].innerHTML);"
            "assert.ok(!elements['account-status-panel'].innerHTML.includes('00:00:00'),elements['account-status-panel'].innerHTML);"
            "assert.ok(!elements['account-info'].innerHTML.includes('00:00:00'),elements['account-info'].innerHTML);"
        ),
    )


def test_user_consumer_refresh_capability_uses_provider(tmp_path: Path):
    _run_node(
        tmp_path,
        _user_status_script(
            "renderAccountStatus({account});"
            "assert.ok(elements['account-status-panel'].innerHTML.includes('<span>Refresh</span><b><span class=\"status-mark ok\"></span></b>'),elements['account-status-panel'].innerHTML);"
        ),
    )


def test_manual_source_key_keeps_bound_account_name(tmp_path: Path):
    script = "\n".join(
        [
            "const assert=require('assert');",
            "const box={innerHTML:''};",
            "const document={getElementById(id){return id==='keys-content'?box:null}};",
            "const labels={acct_token_only:'Token',unbound:'Unbound',no_login:'No login',not_set:'Not set'};",
            "function t(key){return labels[key]||key}",
            "function esc(value){return String(value??'')}",
            "function _slicePage(items){return {items}}",
            "function _pageFoot(){return ''}",
            "function initGlassSelect(){}",
            "function renderDashboard(){}",
            _ADMIN_KEYS_JS,
            "__keys=[{id:'key_1',key:'sk-1234567890',name:'Alice',account_id:'acct_consumer',account_name:'Personal Alice',account_source:'manual',enabled:true,role:'user',username:'',password:'',rate_limit_rpm:0,default_rate_limit_rpm:0}];",
            "(async()=>{await loadKeys(true);assert.ok(box.innerHTML.includes('Personal Alice'),box.innerHTML)})().catch(e=>{console.error(e);process.exit(1)});",
        ]
    )
    _run_node(tmp_path, script)


def _admin_refresh_script(fetch_impl: str, call: str, expected: str) -> str:
    return "\n".join(
        [
            "const assert=require('assert');",
            "const localStorage={getItem(){return ''},setItem(){}};",
            "const alerts=[];",
            "const labels={network_error:'Network error',auto_capture_failed:'Refresh failed',btn_cookie_refresh:'Cookie refresh',cookie_invalid_short:'Invalid'};",
            "function t(key){return labels[key]||key}",
            "async function adminAlert(message){alerts.push(message)}",
            fetch_impl,
            _ADMIN_ACCOUNTS_JS,
            "loadAccounts=()=>{};",
            f"(async()=>{{await {call};assert.deepStrictEqual(alerts,[{expected!r}])}})().catch(e=>{{console.error(e);process.exit(1)}});",
        ]
    )


@pytest.mark.parametrize(
    ("fetch_impl", "call", "expected"),
    [
        (
            "async function fetch(){return {ok:false,status:503,json:async()=>({})}}",
            "refreshAccount('acct_consumer')",
            "Refresh failed (HTTP 503)",
        ),
        (
            "async function fetch(){return {ok:true,status:200,json:async()=>({status:'ok',refreshed:false,account:{}})}}",
            "refreshAccount('acct_consumer')",
            "Refresh failed",
        ),
        (
            "async function fetch(){return {ok:true,status:200,json:async()=>({status:'ok',injected:0,total:1,cookie_valid:false,account:{}})}}",
            "refreshAccountCookie('acct_consumer')",
            "Cookie refresh: Invalid",
        ),
        (
            "async function fetch(){throw new Error('offline')}",
            "refreshAccount('acct_consumer')",
            "Network error",
        ),
    ],
    ids=["http-error", "not-refreshed", "cookie-invalid", "network-error"],
)
def test_admin_refresh_surfaces_failures(
    tmp_path: Path,
    fetch_impl: str,
    call: str,
    expected: str,
):
    _run_node(tmp_path, _admin_refresh_script(fetch_impl, call, expected))


def test_admin_stats_excludes_unknown_consumer_expiry(tmp_path: Path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    consumer = app.state.account_store.add(name="Personal Alice", token="")
    app.state.account_store.set_consumer_auth(
        consumer.id,
        [{"name": "__Host-MSAAUTHP", "value": "cookie"}],
        "opaque-consumer-token",
        "MSA",
    )
    known = app.state.account_store.add(name="Known Expiry", token="")
    known.token_status = lambda: {  # type: ignore[method-assign]
        "valid": True,
        "expires_at": "2026-08-10T12:00:00+00:00",
        "seconds_remaining": 120,
    }

    response = TestClient(app).get("/admin/stats")

    assert response.status_code == 200
    assert response.json()["expiring_accounts"] == [
        {"name": "Known Expiry", "email": "", "seconds_remaining": 120}
    ]
