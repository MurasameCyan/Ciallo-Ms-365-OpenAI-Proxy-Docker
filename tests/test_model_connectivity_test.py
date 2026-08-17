"""/admin/model-test contract: one real turn, four actionable verdicts.

The upstream client is faked -- what matters here is that the probe rides the same
client factory real traffic uses (so a pass means something), that it starts no
session, and that each upstream outcome maps to the verdict an operator acts on
differently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.consumer_client import AccountThrottled
from m365_copilot_openai_proxy.routes_admin_modeltest import classify_probe
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError


class _FakeClient:
    """Stands in for SubstrateCopilotClient; `outcome` drives the probe result."""

    outcome: object = "pong"
    seen: list[tuple] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def chat(self, prompt, additional_context, session=None, images=None):
        _FakeClient.seen.append((prompt, additional_context, session, images, self.kwargs))
        if isinstance(_FakeClient.outcome, Exception):
            raise _FakeClient.outcome
        return _FakeClient.outcome


@pytest.fixture
def env(tmp_path):
    _FakeClient.outcome = "pong"
    _FakeClient.seen = []
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"),
        copilot_client_factory=lambda **kwargs: _FakeClient(**kwargs),
    )
    admin = TestClient(app)
    assert admin.post("/admin/login", json={"password": "admin-key"}).status_code == 200
    account = app.state.account_store.add(name="Pool", token="header.body.sig")
    tone = app.state.tone_options[0]
    return app, admin, account, str(tone.get("label") or tone.get("value"))


def test_classify_probe_maps_each_outcome():
    assert classify_probe("pong") == "ok"
    assert classify_probe("   ") == "empty"
    assert classify_probe("", "M365 refused this turn") == "refused"
    assert classify_probe("", "empty response twice in a row") == "refused"
    assert classify_probe("", "websocket closed") == "error"
    # Quota is not availability: the mode may be perfectly fine.
    assert classify_probe("", "over quota", throttled=True) == "throttled"


def test_probe_answers_ok_and_reports_the_selector(env):
    app, admin, account, tone = env
    r = admin.post("/admin/model-test", json={"account_id": account.id, "model": tone})

    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "ok"
    assert body["reply"] == "pong"
    assert body["reply_len"] == 4
    assert body["provider"] == "m365"
    assert body["upstream_selector"]
    assert body["latency_ms"] >= 0
    # No session: a probe must not continue (or reset) a live conversation, and
    # the account's own token must reach the client the same way /v1 does.
    prompt, context, session, images, kwargs = _FakeClient.seen[-1]
    assert session is None and images is None and context == []
    assert kwargs["token"] == "header.body.sig"
    assert app.state.session_store.items() == []


def test_probe_reports_empty_reply_as_mode_unavailable(env):
    _app, admin, account, tone = env
    _FakeClient.outcome = ""

    body = admin.post("/admin/model-test", json={"account_id": account.id, "model": tone}).json()

    assert body["verdict"] == "empty"
    assert body["reply"] == ""


def test_probe_separates_refusal_from_transport_failure(env):
    _app, admin, account, tone = env
    _FakeClient.outcome = SubstrateCopilotError("M365 refused this turn (tone=Balanced)")
    refused = admin.post("/admin/model-test", json={"account_id": account.id, "model": tone}).json()

    _FakeClient.outcome = SubstrateCopilotError("websocket closed before any reply")
    broken = admin.post("/admin/model-test", json={"account_id": account.id, "model": tone}).json()

    assert refused["verdict"] == "refused"
    assert "refused this turn" in refused["error"]
    assert broken["verdict"] == "error"


def test_probe_reports_quota_as_throttled(env):
    _app, admin, account, tone = env
    _FakeClient.outcome = AccountThrottled("daily limit reached")

    body = admin.post("/admin/model-test", json={"account_id": account.id, "model": tone}).json()

    assert body["verdict"] == "throttled"


def test_probe_uses_a_custom_prompt_when_given(env):
    _app, admin, account, tone = env

    admin.post(
        "/admin/model-test",
        json={"account_id": account.id, "model": tone, "prompt": "draw me a cat"},
    )

    assert _FakeClient.seen[-1][0] == "draw me a cat"


def test_probe_rejects_missing_arguments_and_unknown_accounts(env):
    _app, admin, account, tone = env

    assert admin.post("/admin/model-test", json={"model": tone}).status_code == 400
    assert admin.post("/admin/model-test", json={"account_id": account.id}).status_code == 400
    assert admin.post("/admin/model-test", content=b"not json").status_code == 400
    assert admin.post(
        "/admin/model-test", json={"account_id": "nope", "model": tone}
    ).status_code == 404


def test_probe_requires_admin(env):
    app, _admin, account, tone = env
    anon = TestClient(app)

    r = anon.post("/admin/model-test", json={"account_id": account.id, "model": tone})

    assert r.status_code in (401, 403)
    assert not _FakeClient.seen


def test_admin_page_wires_the_probe_into_the_debug_view():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_modeltest import _ADMIN_MODELTEST_JS

    assert _ADMIN_MODELTEST_JS in _ADMIN_HTML
    for element_id in ("model-test-account", "model-test-model", "model-test-prompt", "model-test-result"):
        assert f'id="{element_id}"' in _ADMIN_HTML
    # Opening the view must populate the selectors, and a language switch must
    # re-render from cache instead of firing more upstream turns.
    assert "if(view==='debug'){loadCaptureToggle();loadRuntimeSettings();loadModelTest();" in _ADMIN_HTML
    assert "if(typeof renderModelTest==='function')renderModelTest()" in _ADMIN_HTML
    # Both languages label every verdict the endpoint can return.
    for verdict in ("ok", "empty", "refused", "throttled", "error", "running"):
        assert _ADMIN_HTML.count(f"mt_v_{verdict}:'") == 2


def test_probe_ui_sends_one_model_at_a_time():
    """Concurrent probes on one account look like a burst and can trip the quota."""
    from m365_copilot_openai_proxy.template_admin_modeltest import _ADMIN_MODELTEST_JS

    run = _ADMIN_MODELTEST_JS.split("async function runModelTest(all)", 1)[1]
    assert "for(const model of targets){" in run
    assert "await _mtProbe(" in run
    assert "Promise.all" not in run
