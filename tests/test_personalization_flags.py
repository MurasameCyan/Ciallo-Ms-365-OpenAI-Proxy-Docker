"""Account-level personalization: reading and writing M365's invisible input.

M365 keeps its "memory" on the *account*, not on a conversation, so something
stored in an earlier session can shape a brand-new one -- and nothing in this
bridge could see it. These tests pin the shape measured against the live account
on 2026-09-05 (`.probe/personalization_flags_probe.py` and
`.probe/personalization_write_probe.py`), because every part of it is something a
reasonable implementation gets wrong:

  * the write answers 200 with `result.value == "Success"` and echoes **no**
    flags, so only a read-back proves anything happened;
  * a *partial* write moves flags nobody sent -- posting `isMemoryEnabled: false`
    alone also turned `isInsightsFromConversationHistoryEnabled` off -- so the
    caller must be handed the re-read rather than its own request, and the POST
    must carry the whole set;
  * the endpoint needs `X-AnchorMailbox: Oid:{oid}@{tid}`, and the token's own
    claims are the only place those two ids come from;
  * a tenant may forbid personalization outright, which has to be said out loud
    instead of looking like a write that silently did nothing.

The endpoint, header set and flag names are protocol facts from
KilimcininKorOglu/M365Bridge, which carries no LICENSE: facts only, no code.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy import routes_admin_personalization
from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.personalization import (
    PERSONALIZATION_FLAGS,
    PersonalizationError,
    PersonalizationUnavailable,
    TenantForbidsPersonalization,
    read_flags,
    write_flags,
)

OID = "11111111-2222-3333-4444-555555555555"
TID = "66666666-7777-8888-9999-000000000000"


def _jwt(**claims) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _substrate_token(oid: str = OID, tid: str = TID) -> str:
    return _jwt(oid=oid, tid=tid, aud="https://substrate.office.com")


def _read_body(
    memory: bool = True,
    insights: bool = True,
    custom: bool = True,
    graph: bool = False,
    tenant: bool = True,
) -> dict:
    """A GET body shaped exactly like the measured one, `result` wrapper included."""
    return {
        "isMemoryEnabled": memory,
        "isInsightsFromConversationHistoryEnabled": insights,
        "isCustomInstructionEnabled": custom,
        "isM365GraphContentEnabled": graph,
        "isPersonalizationEnabledByTenant": tenant,
        "result": {"value": "Success", "renewCert": False, "serviceVersion": "1.0.03533.51407"},
    }


# What a real POST answers: a success envelope and not one flag. This is why the
# module re-reads instead of trusting the status code.
_WRITE_OK = {
    "result": {
        "value": "Success",
        "message": "Successfully updated personalization user flags.",
    }
}


class _Response:
    def __init__(self, status_code: int = 200, payload: object = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")
        self.headers: dict[str, str] = {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _install(monkeypatch, *responses: _Response) -> list[dict]:
    """Swap httpx for a queue of canned answers; return the log of calls made."""
    calls: list[dict] = []
    queue = list(responses)

    class _Client:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def _next(self, method, url, headers, body):
            calls.append({"method": method, "url": url, "headers": headers or {}, "json": body})
            if not queue:
                raise AssertionError(f"unexpected {method} {url}: no canned response left")
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        async def get(self, url, headers=None):
            return self._next("GET", url, headers, None)

        async def post(self, url, headers=None, json=None):
            return self._next("POST", url, headers, json)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return calls


def _account(tmp_path, token: str | None = None):
    store = AccountStore(persist_path=tmp_path / "accounts.json")
    account = store.add(name="Pool", token=_substrate_token() if token is None else token)
    return store, account


def test_read_reports_every_flag_and_the_tenant_gate(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    _install(monkeypatch, _Response(payload=_read_body(graph=False, tenant=True)))

    state = asyncio.run(read_flags(store, account.id))

    assert state["flags"] == {
        "isMemoryEnabled": True,
        "isInsightsFromConversationHistoryEnabled": True,
        "isCustomInstructionEnabled": True,
        "isM365GraphContentEnabled": False,
    }
    assert state["tenant_allowed"] is True


def test_read_sends_the_anchor_mailbox_built_from_the_token_claims(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    calls = _install(monkeypatch, _Response(payload=_read_body()))

    asyncio.run(read_flags(store, account.id))

    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "GET"
    assert call["url"].startswith(
        "https://substrate.office.com/m365Copilot/PersonalizationUserFlags"
    )
    assert "variants=feature.EnablePersonalization" in call["url"]
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert headers["authorization"] == f"Bearer {account.token}"
    assert headers["x-anchormailbox"] == f"Oid:{OID}@{TID}"
    assert headers["x-routingparameter-sessionkey"] == OID
    assert headers["x-scenario"] == "OfficeWebIncludedCopilot"
    assert headers["origin"] == "https://m365.cloud.microsoft"
    assert headers["accept-language"] == "en-us"
    assert headers["x-clientrequestid"]


def test_a_write_is_proven_by_the_read_back_not_by_the_success_envelope(tmp_path, monkeypatch):
    """The POST answers Success and echoes nothing, so a third call must happen."""
    store, account = _account(tmp_path)
    calls = _install(
        monkeypatch,
        _Response(payload=_read_body(memory=True)),
        _Response(payload=_WRITE_OK),
        _Response(payload=_read_body(memory=False, insights=False)),
    )

    state = asyncio.run(write_flags(store, account.id, {"isMemoryEnabled": False}))

    assert [c["method"] for c in calls] == ["GET", "POST", "GET"]
    assert state["flags"]["isMemoryEnabled"] is False


def test_a_write_reports_the_coupled_flag_the_caller_never_touched(tmp_path, monkeypatch):
    """Measured: turning memory off also turned insights off. Report what is true."""
    store, account = _account(tmp_path)
    _install(
        monkeypatch,
        _Response(payload=_read_body(memory=True, insights=True)),
        _Response(payload=_WRITE_OK),
        _Response(payload=_read_body(memory=False, insights=False)),
    )

    state = asyncio.run(write_flags(store, account.id, {"isMemoryEnabled": False}))

    assert state["flags"]["isInsightsFromConversationHistoryEnabled"] is False


def test_a_write_posts_the_whole_set_merged_over_a_fresh_read(tmp_path, monkeypatch):
    """A partial body moves flags nobody sent, so every flag goes out explicitly."""
    store, account = _account(tmp_path)
    calls = _install(
        monkeypatch,
        _Response(payload=_read_body(memory=True, insights=True, custom=True, graph=False)),
        _Response(payload=_WRITE_OK),
        _Response(payload=_read_body(memory=True, insights=True, custom=True, graph=True)),
    )

    asyncio.run(write_flags(store, account.id, {"isM365GraphContentEnabled": True}))

    body = calls[1]["json"]
    assert set(body) == set(PERSONALIZATION_FLAGS)
    assert body == {
        "isMemoryEnabled": True,
        "isInsightsFromConversationHistoryEnabled": True,
        "isCustomInstructionEnabled": True,
        "isM365GraphContentEnabled": True,
    }


def test_an_unknown_flag_is_refused_before_anything_is_sent(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    calls = _install(monkeypatch)

    with pytest.raises(ValueError):
        asyncio.run(write_flags(store, account.id, {"isMemoryEnabledd": False}))

    assert calls == []


def test_a_non_boolean_value_is_refused_before_anything_is_sent(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    calls = _install(monkeypatch)

    with pytest.raises(ValueError):
        asyncio.run(write_flags(store, account.id, {"isMemoryEnabled": "false"}))

    assert calls == []


def test_an_empty_change_set_never_writes(tmp_path, monkeypatch):
    """A no-op write is still a real write on the operator's account."""
    store, account = _account(tmp_path)
    calls = _install(monkeypatch)

    with pytest.raises(ValueError):
        asyncio.run(write_flags(store, account.id, {}))

    assert calls == []


def test_a_tenant_that_forbids_personalization_blocks_the_write(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    calls = _install(monkeypatch, _Response(payload=_read_body(tenant=False)))

    with pytest.raises(TenantForbidsPersonalization):
        asyncio.run(write_flags(store, account.id, {"isMemoryEnabled": False}))

    assert [c["method"] for c in calls] == ["GET"]


def test_a_tenant_that_forbids_personalization_can_still_be_read(tmp_path, monkeypatch):
    """The flags still shape every turn, so hiding them would hide the input."""
    store, account = _account(tmp_path)
    _install(monkeypatch, _Response(payload=_read_body(tenant=False)))

    state = asyncio.run(read_flags(store, account.id))

    assert state["tenant_allowed"] is False
    assert state["flags"]["isMemoryEnabled"] is True


def test_an_expired_token_is_reported_as_something_to_refresh(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    _install(monkeypatch, _Response(status_code=401, text="expired"))

    with pytest.raises(PersonalizationError) as caught:
        asyncio.run(read_flags(store, account.id))

    assert "401" in str(caught.value)
    assert "刷新" in str(caught.value)


def test_an_upstream_failure_keeps_its_status_in_the_message(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    _install(monkeypatch, _Response(status_code=503, text="unavailable"))

    with pytest.raises(PersonalizationError) as caught:
        asyncio.run(read_flags(store, account.id))

    assert "503" in str(caught.value)


def test_a_consumer_account_is_told_it_has_no_such_setting(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    store.set_consumer_auth(account.id, cookies=[], access_token="consumer-token")
    calls = _install(monkeypatch)

    with pytest.raises(PersonalizationUnavailable):
        asyncio.run(read_flags(store, account.id))

    assert calls == []


def test_an_account_without_a_token_says_so_without_a_request(tmp_path, monkeypatch):
    store, account = _account(tmp_path, token="")
    calls = _install(monkeypatch)

    with pytest.raises(PersonalizationUnavailable):
        asyncio.run(read_flags(store, account.id))

    assert calls == []


def test_a_token_without_oid_or_tid_cannot_anchor_the_mailbox(tmp_path, monkeypatch):
    """No oid/tid means no X-AnchorMailbox, and the endpoint routes on it."""
    store, account = _account(tmp_path, token=_jwt(aud="https://substrate.office.com"))
    calls = _install(monkeypatch)

    with pytest.raises(PersonalizationUnavailable):
        asyncio.run(read_flags(store, account.id))

    assert calls == []


def test_a_missing_account_is_an_error_not_an_empty_answer(tmp_path, monkeypatch):
    store, _ = _account(tmp_path)
    _install(monkeypatch)

    with pytest.raises(PersonalizationError):
        asyncio.run(read_flags(store, "acct_does_not_exist"))


def test_a_non_json_body_is_reported_as_upstream_trouble(tmp_path, monkeypatch):
    """Cloudflare/login HTML answers 200 too."""
    store, account = _account(tmp_path)
    _install(monkeypatch, _Response(status_code=200, payload=None, text="<html>login</html>"))

    with pytest.raises(PersonalizationError):
        asyncio.run(read_flags(store, account.id))


def test_a_body_missing_a_flag_is_a_protocol_change_not_a_false(tmp_path, monkeypatch):
    """Defaulting a missing flag to False would write that False back on the next save."""
    store, account = _account(tmp_path)
    partial = _read_body()
    partial.pop("isM365GraphContentEnabled")
    _install(monkeypatch, _Response(payload=partial))

    with pytest.raises(PersonalizationError) as caught:
        asyncio.run(read_flags(store, account.id))

    assert "isM365GraphContentEnabled" in str(caught.value)


def test_a_transport_error_is_wrapped_rather_than_raised_raw(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    _install(monkeypatch, httpx.ConnectError("no route to host"))

    with pytest.raises(PersonalizationError):
        asyncio.run(read_flags(store, account.id))


def test_a_failed_write_never_pretends_the_read_back_succeeded(tmp_path, monkeypatch):
    store, account = _account(tmp_path)
    calls = _install(
        monkeypatch,
        _Response(payload=_read_body()),
        _Response(status_code=500, text="boom"),
    )

    with pytest.raises(PersonalizationError):
        asyncio.run(write_flags(store, account.id, {"isMemoryEnabled": False}))

    assert [c["method"] for c in calls] == ["GET", "POST"]


@pytest.fixture
def env(tmp_path):
    """App + logged-in admin client + one M365 account."""
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    admin = TestClient(app)
    assert admin.post("/admin/login", json={"password": "admin-key"}).status_code == 200
    account = app.state.account_store.add(name="Pool", token=_substrate_token())
    return {"app": app, "admin": admin, "account": account}


def _state(memory=True, insights=True, custom=True, graph=False, tenant=True) -> dict:
    return {
        "flags": {
            "isMemoryEnabled": memory,
            "isInsightsFromConversationHistoryEnabled": insights,
            "isCustomInstructionEnabled": custom,
            "isM365GraphContentEnabled": graph,
        },
        "tenant_allowed": tenant,
    }


def test_the_routes_are_registered_on_the_app(env):
    paths = {r.path for r in env["app"].routes}
    assert "/admin/accounts/{acc_id}/personalization" in paths


def test_reading_returns_the_flags_and_the_tenant_gate(env, monkeypatch):
    seen: list[str] = []

    async def fake_read(accounts, account_id):
        seen.append(account_id)
        return _state(graph=True, tenant=False)

    monkeypatch.setattr(routes_admin_personalization, "read_flags", fake_read)

    r = env["admin"].get(f"/admin/accounts/{env['account'].id}/personalization")

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "flags": _state(graph=True)["flags"],
        "tenant_allowed": False,
    }
    assert seen == [env["account"].id]


def test_writing_answers_with_the_read_back_state(env, monkeypatch):
    seen: list[dict] = []

    async def fake_write(accounts, account_id, changes):
        seen.append(changes)
        # The upstream coupling: insights follows memory down.
        return _state(memory=False, insights=False)

    monkeypatch.setattr(routes_admin_personalization, "write_flags", fake_write)

    r = env["admin"].post(
        f"/admin/accounts/{env['account'].id}/personalization",
        json={"isMemoryEnabled": False},
    )

    assert r.status_code == 200
    assert r.json()["flags"] == _state(memory=False, insights=False)["flags"]
    assert seen == [{"isMemoryEnabled": False}]


def test_both_routes_require_an_admin_session(env, monkeypatch):
    async def fake(*args, **kwargs):
        raise AssertionError("must not reach the upstream without a session")

    monkeypatch.setattr(routes_admin_personalization, "read_flags", fake)
    monkeypatch.setattr(routes_admin_personalization, "write_flags", fake)
    anon = TestClient(env["app"])
    path = f"/admin/accounts/{env['account'].id}/personalization"

    assert anon.get(path).status_code == 401
    assert anon.post(path, json={"isMemoryEnabled": False}).status_code == 401


def test_an_unknown_account_is_404_without_calling_upstream(env, monkeypatch):
    async def fake(*args, **kwargs):
        raise AssertionError("must not call upstream for an account we do not have")

    monkeypatch.setattr(routes_admin_personalization, "read_flags", fake)

    r = env["admin"].get("/admin/accounts/acct_nope/personalization")

    assert r.status_code == 404


def test_an_unknown_flag_is_a_400(env, monkeypatch):
    async def fake_write(accounts, account_id, changes):
        raise ValueError("未知的个性化开关：isMemoryEnabledd")

    monkeypatch.setattr(routes_admin_personalization, "write_flags", fake_write)

    r = env["admin"].post(
        f"/admin/accounts/{env['account'].id}/personalization",
        json={"isMemoryEnabledd": False},
    )

    assert r.status_code == 400


def test_a_tenant_that_forbids_it_is_a_409_with_the_reason(env, monkeypatch):
    async def fake_write(accounts, account_id, changes):
        raise TenantForbidsPersonalization("该租户禁用了个性化设置")

    monkeypatch.setattr(routes_admin_personalization, "write_flags", fake_write)

    r = env["admin"].post(
        f"/admin/accounts/{env['account'].id}/personalization",
        json={"isMemoryEnabled": False},
    )

    assert r.status_code == 409
    assert "租户" in r.json()["error"]["message"]


def test_an_account_that_cannot_do_it_is_a_400(env, monkeypatch):
    async def fake_read(accounts, account_id):
        raise PersonalizationUnavailable("该账户没有可用的令牌")

    monkeypatch.setattr(routes_admin_personalization, "read_flags", fake_read)

    r = env["admin"].get(f"/admin/accounts/{env['account'].id}/personalization")

    assert r.status_code == 400


def test_an_upstream_failure_is_a_502_carrying_the_message(env, monkeypatch):
    async def fake_read(accounts, account_id):
        raise PersonalizationError("读取个性化设置失败：HTTP 503")

    monkeypatch.setattr(routes_admin_personalization, "read_flags", fake_read)

    r = env["admin"].get(f"/admin/accounts/{env['account'].id}/personalization")

    assert r.status_code == 502
    assert "503" in r.json()["error"]["message"]


def test_a_body_that_is_not_an_object_is_a_400(env, monkeypatch):
    async def fake_write(accounts, account_id, changes):
        raise AssertionError("must not reach the upstream with a malformed body")

    monkeypatch.setattr(routes_admin_personalization, "write_flags", fake_write)

    r = env["admin"].post(
        f"/admin/accounts/{env['account'].id}/personalization",
        content=b"[]",
        headers={"Content-Type": "application/json"},
    )

    assert r.status_code == 400


def test_the_panel_is_offered_only_for_m365_accounts_and_repaints_from_a_cache():
    """The accounts table is rebuilt every 30s, so the panel must not hold state.

    It also must not fetch per row: one GET here is one real call to substrate,
    and doing that for every account on every poll would be a self-inflicted
    flood -- so the panel loads when its drawer opens and renders from a map.
    """
    from m365_copilot_openai_proxy.template_admin_accounts import _ADMIN_ACCOUNTS_JS
    from m365_copilot_openai_proxy.template_admin_personalization import (
        _ADMIN_PERSONALIZATION_JS,
    )

    js = _ADMIN_PERSONALIZATION_JS
    assert "function _personalizationPanel(a){" in js
    # Consumer accounts have no such endpoint: the same guard the PKCE panel uses.
    assert "!=='m365')return ''" in js
    assert "let __personalization={}" in js
    assert "/personalization" in js
    # The drawer is where the panel is mounted, and it loads when opened.
    assert "_personalizationPanel(a)" in _ADMIN_ACCOUNTS_JS
    assert "loadPersonalization(id)" in _ADMIN_ACCOUNTS_JS


def test_every_label_the_panel_uses_exists_in_both_languages():
    import re

    from m365_copilot_openai_proxy.template_admin_i18n import _ADMIN_I18N_JS
    from m365_copilot_openai_proxy.template_admin_personalization import (
        _ADMIN_PERSONALIZATION_JS,
    )

    keys = set(re.findall(r"t\('([a-z0-9_]+)'\)", _ADMIN_PERSONALIZATION_JS))
    assert "pers_title" in keys, "the panel needs a heading of its own"
    zh, en = _ADMIN_I18N_JS.split("en:{", 1)
    for key in sorted(keys):
        assert f"{key}:" in zh, f"missing zh label: {key}"
        assert f"{key}:" in en, f"missing en label: {key}"


def test_the_panel_warns_that_this_is_the_operators_real_microsoft_account():
    """Not our setting: it changes their own web and phone Copilot too."""
    from m365_copilot_openai_proxy.template_admin_i18n import _ADMIN_I18N_JS
    from m365_copilot_openai_proxy.template_admin_personalization import (
        _ADMIN_PERSONALIZATION_JS,
    )

    assert "t('pers_warning')" in _ADMIN_PERSONALIZATION_JS
    zh, en = _ADMIN_I18N_JS.split("en:{", 1)
    assert "微软账号" in zh
    assert "pers_warning:" in en


# ---- the panel's own behaviour, run in node against the shipped JS ----------

_NODE = shutil.which("node")


def _panel_script(steps: str, answers: str) -> str:
    """The panel JS with a stub DOM and a queue of fetch answers."""
    from m365_copilot_openai_proxy.template_admin_personalization import (
        _ADMIN_PERSONALIZATION_JS,
    )

    return "\n".join([
        "const assert=require('assert');",
        "const box={innerHTML:''};",
        "const document={getElementById(id){return id==='pers-acct1'?box:null}};",
        "function t(key){return key}",
        "function esc(value){return String(value==null?'':value)}",
        f"const answers={answers};",
        "const calls=[];",
        "global.fetch=async(url,init)=>{"
        "calls.push({url:url,method:(init&&init.method)||'GET',body:init&&init.body});"
        "const a=answers.shift();"
        "if(!a)throw new Error('unexpected fetch: '+url);"
        "return {ok:a.ok!==false,status:a.status||200,json:async()=>a.body}};",
        _ADMIN_PERSONALIZATION_JS,
        "(async()=>{" + steps + "})().catch(e=>{console.error(e);process.exit(1)});",
    ])


def _run_node(tmp_path: Path, script: str) -> None:
    if _NODE is None:
        pytest.skip("node is required for inline UI behavior tests")
    path = tmp_path / "personalization-behavior.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    assert result.returncode == 0, (result.stderr or "") + (result.stdout or "")


def _ok(memory=True, insights=True, custom=True, graph=False, tenant=True) -> dict:
    return {
        "body": {
            "status": "ok",
            "flags": {
                "isMemoryEnabled": memory,
                "isInsightsFromConversationHistoryEnabled": insights,
                "isCustomInstructionEnabled": custom,
                "isM365GraphContentEnabled": graph,
            },
            "tenant_allowed": tenant,
        }
    }


def _fail(status: int, message: str) -> dict:
    return {"ok": False, "status": status, "body": {"error": {"message": message}}}


def test_panel_caches_the_read_and_repaints_the_whole_set_from_a_write(tmp_path):
    """One drawer, one upstream read; and a one-flag POST repaints all four."""
    steps = """
      await loadPersonalization('acct1');
      assert.strictEqual(calls.length,1,'opening the drawer must spend exactly one call');
      assert.strictEqual(calls[0].method,'GET');
      assert.ok(box.innerHTML.includes('data-pers-flag="isMemoryEnabled" checked'),box.innerHTML);
      assert.ok(!box.innerHTML.includes('data-pers-flag="isM365GraphContentEnabled" checked'),box.innerHTML);
      // The accounts table rebuilds itself every 30s: the panel comes back from
      // the map, with no second read, and reopening the drawer buys nothing.
      const rebuilt=_personalizationPanel({id:'acct1',provider:'m365'});
      assert.ok(rebuilt.includes('data-pers-flag="isMemoryEnabled" checked'),rebuilt);
      await loadPersonalization('acct1');
      assert.strictEqual(calls.length,1,'a reopen re-fetched');
      // Upstream couples the flags: memory off also came back with insights off.
      await savePersonalization('acct1','isMemoryEnabled',false);
      assert.strictEqual(calls.length,2);
      assert.strictEqual(calls[1].method,'POST');
      assert.strictEqual(calls[1].body,'{"isMemoryEnabled":false}');
      assert.ok(!box.innerHTML.includes('data-pers-flag="isMemoryEnabled" checked'),box.innerHTML);
      assert.ok(!box.innerHTML.includes('data-pers-flag="isInsightsFromConversationHistoryEnabled" checked'),box.innerHTML);
      assert.ok(box.innerHTML.includes('data-pers-flag="isCustomInstructionEnabled" checked'),box.innerHTML);
      assert.ok(box.innerHTML.includes('pers_saved'),box.innerHTML);
    """
    answers = json.dumps([_ok(), _ok(memory=False, insights=False)])
    _run_node(tmp_path, _panel_script(steps, answers))


def test_panel_locks_every_flag_when_the_tenant_forbids_personalization(tmp_path):
    steps = """
      await loadPersonalization('acct1');
      assert.strictEqual((box.innerHTML.match(/disabled/g)||[]).length,4,box.innerHTML);
      assert.ok(box.innerHTML.includes('pers_tenant_off'),box.innerHTML);
      assert.ok(!box.innerHTML.includes('pers_coupling_hint'),box.innerHTML);
    """
    _run_node(tmp_path, _panel_script(steps, json.dumps([_ok(tenant=False)])))


def test_a_failed_read_offers_a_retry_and_blocks_writing_blind(tmp_path):
    steps = """
      await loadPersonalization('acct1');
      assert.ok(box.innerHTML.includes('凭据已失效'),box.innerHTML);
      assert.ok(box.innerHTML.includes('pers_retry'),box.innerHTML);
      assert.ok(!box.innerHTML.includes('data-pers-flag'),box.innerHTML);
      // Nothing was read, so nothing may be written: a POST here would send the
      // other three flags' values from a state that does not exist.
      await savePersonalization('acct1','isMemoryEnabled',false);
      assert.strictEqual(calls.length,1,'saved without ever reading');
      await loadPersonalization('acct1');
      assert.strictEqual(calls.length,2,'a failure is not a cached value');
      assert.ok(box.innerHTML.includes('data-pers-flag="isCustomInstructionEnabled" checked'),box.innerHTML);
    """
    answers = json.dumps([_fail(401, "凭据已失效 (401)，请先刷新账户"), _ok()])
    _run_node(tmp_path, _panel_script(steps, answers))


def test_a_failed_write_keeps_the_checkboxes_on_what_the_account_still_says(tmp_path):
    steps = """
      await loadPersonalization('acct1');
      await savePersonalization('acct1','isMemoryEnabled',false);
      assert.ok(box.innerHTML.includes('data-pers-flag="isMemoryEnabled" checked'),box.innerHTML);
      assert.ok(box.innerHTML.includes('租户'),box.innerHTML);
      assert.ok(!box.innerHTML.includes('pers_saved'),box.innerHTML);
    """
    answers = json.dumps([_ok(), _fail(409, "租户已关闭个性化")])
    _run_node(tmp_path, _panel_script(steps, answers))
