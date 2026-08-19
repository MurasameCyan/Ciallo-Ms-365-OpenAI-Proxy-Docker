"""The global run permission is an admin ceiling, not a default a user may raise.

``read_only`` exists to keep the proxy from ever handing a client a mutating tool
call. The per-key value is written by exactly one UI -- the user's own /user page
-- so resolving it as a plain "key wins over global" override let the user undo an
admin policy: POST /user/tone with ``run_permission=full`` and the guard is off.

It did not even take intent. The picker offered only read_only/full with no
"inherit" choice and defaulted to full, so every save of the mode card pinned a
concrete value on the key; a global later tightened to read_only then applied to
nobody who had ever touched that card.

So the ceiling is enforced where it is read (one resolver, shared by the two
pages that display it and the three routes that enforce it), and the picker can
express inheriting again.
"""

from __future__ import annotations

import inspect
import re

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.key_store import ApiKey
from m365_copilot_openai_proxy.routes_api_common import effective_run_permission
from m365_copilot_openai_proxy.templates import _USER_HTML

VERIFIED_MODEL = "claude-sonnet-4-6"  # tone Claude_Sonnet, honours the native contract

WRITE_CALL = (
    '```tool_call\n{"name": "Write", "arguments": {"file_path": "/tmp/a.txt", '
    '"content": "x"}}\n```'
)
WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "Write",
        "description": "Write a file",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["file_path", "content"],
        },
    },
}


class FakeClient:
    def __init__(self, reply: str):
        self.reply = reply

    async def chat(self, prompt, context=None, session=None, images=None):
        return self.reply

    async def chat_stream(self, prompt, context=None, session=None, images=None):
        yield self.reply


@pytest.fixture
def app(tmp_path):
    return create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kw: FakeClient(WRITE_CALL),
    )


@pytest.fixture
def user_client(app):
    # Unbound on purpose: binding an account sends the turn through the token
    # refresh gate, and a fixture account has no token to refresh (503).
    key = app.state.key_store.add(name="Test Key")
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key.key}"
    return client, key


# --- the resolver ------------------------------------------------------------

def test_a_key_pinned_to_full_cannot_outrank_a_read_only_global(app):
    app.state.run_permission = "read_only"

    assert effective_run_permission(app, ApiKey(run_permission="full")) == "read_only"


def test_a_key_may_still_tighten_below_a_full_global(app):
    app.state.run_permission = "full"

    assert effective_run_permission(app, ApiKey(run_permission="read_only")) == "read_only"
    assert effective_run_permission(app, ApiKey(run_permission="full")) == "full"


@pytest.mark.parametrize("global_value", ["read_only", "full"])
def test_an_unset_or_unreadable_key_inherits_the_global(app, global_value):
    app.state.run_permission = global_value

    assert effective_run_permission(app, None) == global_value
    assert effective_run_permission(app, ApiKey(run_permission="")) == global_value
    # A hand-edited keys.json must not read as a grant either.
    assert effective_run_permission(app, ApiKey(run_permission="nonsense")) == global_value


def test_one_resolver_serves_the_display_sites_too():
    # /admin and /user each used to carry their own copy, so the number a user was
    # shown could disagree with the one the turn enforced.
    from m365_copilot_openai_proxy import routes_admin, routes_user

    for module in (routes_admin, routes_user):
        source = inspect.getsource(module)
        assert "def _effective_run_permission" not in source, (
            f"{module.__name__} resolves run_permission on its own again"
        )
        assert "effective_run_permission" in source


# --- the /user boundary ------------------------------------------------------

def test_a_user_cannot_widen_past_a_read_only_global(app, user_client):
    client, key = user_client
    app.state.run_permission = "read_only"

    saved = client.post("/user/tone", json={"tone": "Magic", "run_permission": "full"})

    assert saved.status_code == 200
    assert saved.json()["effective_run_permission"] == "read_only"
    assert client.get("/user/me").json()["effective_run_permission"] == "read_only"


def test_a_mutating_call_is_dropped_for_a_key_that_pinned_full(app, user_client):
    client, key = user_client
    app.state.run_permission = "read_only"
    app.state.key_store.update(key.id, run_permission="full")

    r = client.post(
        "/v1/chat/completions",
        json={
            "model": VERIFIED_MODEL,
            "messages": [{"role": "user", "content": "写一下 /tmp/a.txt"}],
            "tools": [WRITE_TOOL],
        },
    )

    assert r.status_code == 200
    assert r.json()["choices"][0]["message"].get("tool_calls") in (None, [])
    assert app.state.call_log[-1]["run_permission"] == "read_only"


# --- the picker --------------------------------------------------------------

def test_the_user_picker_can_express_inheriting_the_global():
    # Without the inherit option every save of the mode card pins a value, which
    # is how a later global read_only ended up applying to nobody.
    assert "run_permission_inherit" in _USER_HTML
    assert "_defaultRunPermission" in _USER_HTML
    assert "<option value=\"\">'+t('run_permission_inherit')+'</option>'" in _USER_HTML
    assert "id=\"user-run-permission-default\"" in _USER_HTML
    # The ceiling is invisible otherwise: the picker offers "full" under a
    # read_only global and silently resolves it to read_only.
    for key in ("run_permission_hint_ceiling", "run_permission_hint_read_only"):
        assert len(re.findall(rf"{key}:'([^']*)'", _USER_HTML)) == 2, f"{key} lacks zh+en"
        assert f'data-i18n="{key}"' in _USER_HTML


def test_the_picker_never_defaults_a_blank_value_to_full():
    # `||'full'` on the save path is the escalation in one character: an unloaded
    # or absent control posted a concrete grant.
    assert "user-run-permission')?.value||'full'" not in _USER_HTML
    assert "d.run_permission||d.effective_run_permission||'full'" not in _USER_HTML
