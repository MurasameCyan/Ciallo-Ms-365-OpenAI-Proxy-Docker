from __future__ import annotations

import base64
import json
import os
import stat
import time

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.protocol_profile import ProtocolProfileStore
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotClient


def _store(path):
    return ProtocolProfileStore(path, ["feature.Builtin"], ["builtin_set"])


def _jwt(tid: str) -> str:
    claims = {
        "aud": "https://substrate.office.com/",
        "exp": int(time.time()) + 3600,
        "tid": tid,
        "oid": "object-a",
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _candidate(name: str) -> dict:
    return {
        "variants": [f"feature.{name}"],
        "options_sets": [f"{name.lower()}_set"],
    }


def test_protocol_profile_persists_scopes_and_resolves_account_before_tenant(tmp_path):
    path = tmp_path / "protocol_profile.json"
    store = _store(path)

    store.apply(_candidate("Tenant"), scope="tenant", scope_id="tenant-a")
    store.apply(_candidate("Account"), scope="account", scope_id="account-a")
    reloaded = _store(path)

    assert reloaded.active(account_id="account-a", tenant_id="tenant-a") == {
        "source": "captured",
        "scope": "account",
        "variants": ["feature.Account"],
        "options_sets": ["account_set"],
    }
    assert reloaded.active(account_id="account-b", tenant_id="tenant-a")["scope"] == "tenant"
    assert reloaded.active(account_id="account-b", tenant_id="tenant-b")["scope"] == "builtin"

    reloaded.rollback(scope="account", scope_id="account-a")
    assert reloaded.active(account_id="account-a", tenant_id="tenant-a")["scope"] == "tenant"
    reloaded.rollback(scope="tenant", scope_id="tenant-a")
    assert reloaded.active(account_id="account-a", tenant_id="tenant-a")["scope"] == "builtin"


def test_protocol_profile_ignores_legacy_unscoped_file(tmp_path):
    path = tmp_path / "protocol_profile.json"
    path.write_text(json.dumps({"source": "captured", **_candidate("Legacy")}), encoding="utf-8")

    active = _store(path).active(account_id="account-a", tenant_id="tenant-a")

    assert active["scope"] == "builtin"
    assert active["variants"] == ["feature.Builtin"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not authoritative on Windows")
def test_protocol_profile_file_is_owner_only(tmp_path):
    path = tmp_path / "protocol_profile.json"

    _store(path).apply(_candidate("Captured"), scope="account", scope_id="account-a")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_new_clients_use_the_active_profile_on_both_wire_fields(tmp_path):
    made = []

    class FakeWireClient(SubstrateCopilotClient):
        def __init__(self, **kwargs):
            self._token = "token"
            self._oid = "oid"
            self._tid = "tid"
            self._tone = kwargs.get("tone") or "Magic"
            self._extra_tool_prompt = ""
            self._time_zone = "Asia/Shanghai"
            self._studio_agent_id = ""
            made.append(self)

        async def chat(self, prompt, additional_context, session=None, images=None):
            return "ok"

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="key"),
        copilot_client_factory=lambda **kwargs: FakeWireClient(**kwargs),
    )
    account = app.state.account_store.add(token=_jwt("tenant-a"))
    key = app.state.key_store.add(name="Scoped", account_id=account.id)
    app.state.protocol_profile_store.apply(
        {"variants": ["feature.Captured"], "options_sets": ["captured_set"]},
        scope="account",
        scope_id=account.id,
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "gpt-5.6", "messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 200
    client = made[-1]
    assert "&variants=feature.Captured" in client._ws_url("c", "s", "r")
    argument = json.loads(client._chat_invoke("ping", "c", "s", "r", True).rstrip("\x1e"))[
        "arguments"
    ][0]
    assert argument["optionsSets"] == ["captured_set"]


def test_protocol_profile_candidate_handles_deep_payload_and_ignores_raw_case_insensitively():
    node = {"variants": ["feature.Valid"], "Raw": {"variants": ["feature.Leak"]}}
    for _ in range(1200):
        node = {"nested": node}

    from m365_copilot_openai_proxy.protocol_profile import protocol_profile_candidate

    candidate = protocol_profile_candidate([node])

    assert candidate["variants"] == ["feature.Valid"]
    assert candidate["source_records"] == 1


def test_protocol_profile_candidate_stops_at_node_budget(monkeypatch):
    from m365_copilot_openai_proxy import protocol_profile

    monkeypatch.setattr(protocol_profile, "_MAX_CAPTURE_NODES", 1)
    candidate = protocol_profile.protocol_profile_candidate(
        [{"variants": ["feature.Valid"], "nested": {"optionsSets": ["too_deep"]}}]
    )

    assert candidate["variants"] == ["feature.Valid"]
    assert candidate["options_sets"] == []
    assert candidate["rejected"] == 1


def test_protocol_profile_apply_does_not_change_live_state_when_save_fails(tmp_path, monkeypatch):
    store = _store(tmp_path / "protocol_profile.json")
    monkeypatch.setattr(
        store,
        "_save",
        lambda profile=None: (_ for _ in ()).throw(OSError("full")),
    )

    with pytest.raises(OSError):
        store.apply(_candidate("Captured"), scope="account", scope_id="account-a")

    assert store.active(account_id="account-a")["source"] == "builtin"


def test_protocol_profile_rollback_does_not_change_live_state_when_save_fails(
    tmp_path, monkeypatch
):
    store = _store(tmp_path / "protocol_profile.json")
    store.apply(_candidate("Captured"), scope="account", scope_id="account-a")
    monkeypatch.setattr(
        store,
        "_save",
        lambda profile=None: (_ for _ in ()).throw(OSError("full")),
    )

    with pytest.raises(OSError):
        store.rollback(scope="account", scope_id="account-a")

    assert store.active(account_id="account-a") == {
        "source": "captured",
        "scope": "account",
        "variants": ["feature.Captured"],
        "options_sets": ["captured_set"],
    }


def test_the_dependency_reads_the_tenant_from_the_account_token(tmp_path):
    """A tenant-scoped profile only applies if the tid is decoded off the token.

    The decode sits inside ``except Exception: tenant_id = ""``, so a broken
    lookup there does not raise -- it silently downgrades every tenant-scoped
    profile to builtin, on every account. Nothing else in the suite would notice.
    """
    from types import SimpleNamespace

    from fastapi import FastAPI

    from m365_copilot_openai_proxy.dependencies import create_api_dependencies

    app = FastAPI()
    app.state.settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    app.state.copilot_client_factory = lambda **kw: SimpleNamespace()
    store = _store(tmp_path / "protocol_profile.json")
    store.apply(_candidate("Tenant"), scope="tenant", scope_id="tenant-a")
    app.state.protocol_profile_store = store

    _, get_copilot_client = create_api_dependencies(app)
    account = SimpleNamespace(id="account-b", provider="m365", token=_jwt("tenant-a"))
    request = SimpleNamespace(state=SimpleNamespace(account=account, api_key_obj=None))

    client = get_copilot_client(request)

    assert client._variants == "feature.Tenant"
    assert client._options_sets == ["tenant_set"]
