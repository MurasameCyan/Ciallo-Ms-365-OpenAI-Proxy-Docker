from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy import account_crypto
from m365_copilot_openai_proxy.account_serializers import (
    account_public,
    user_account_public,
)
from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


AGENT_ID = "fake-title.fake-bot.gpt.default"
TENANT_A = "tenant-a"
OBJECT_A = "object-a"


def _jwt(*, tid: str = TENANT_A, oid: str = OBJECT_A) -> str:
    claims = {
        "aud": "https://substrate.office.com/",
        "exp": int(time.time()) + 3600,
        "tid": tid,
        "oid": oid,
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _admin_client(tmp_path) -> tuple[object, TestClient]:
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    client = TestClient(app)
    response = client.post("/admin/login", json={"password": "admin-key"})
    assert response.status_code == 200
    return app, client


def test_new_account_has_no_studio_agent_binding(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Unbound", token=_jwt())

    assert account.studio_agent_id == ""
    assert account.studio_agent_tenant_id == ""
    assert account.studio_agent_object_id == ""
    assert account.studio_agent_ready is False


@pytest.mark.skipif(
    not account_crypto._HAVE_CRYPTO,
    reason="cryptography not installed; encryption degrades to plaintext",
)
def test_valid_binding_persists_agent_and_subject_encrypted(tmp_path):
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist)
    account = store.add(name="Bound", token=_jwt())

    bound = store.set_studio_agent_id(account.id, AGENT_ID)

    assert bound is account
    assert account.studio_agent_id == AGENT_ID
    assert account.studio_agent_tenant_id == TENANT_A
    assert account.studio_agent_object_id == OBJECT_A
    assert account.studio_agent_ready is True

    record = json.loads(persist.read_text(encoding="utf-8"))[account.id]
    for field in (
        "studio_agent_id",
        "studio_agent_tenant_id",
        "studio_agent_object_id",
    ):
        assert record[field].get("__enc__") == 1
    blob = persist.read_text(encoding="utf-8")
    assert AGENT_ID not in blob
    assert TENANT_A not in blob
    assert OBJECT_A not in blob

    reloaded = AccountStore(persist).get(account.id)
    assert reloaded is not None
    assert reloaded.studio_agent_id == AGENT_ID
    assert reloaded.studio_agent_tenant_id == TENANT_A
    assert reloaded.studio_agent_object_id == OBJECT_A
    assert reloaded.studio_agent_ready is True


@pytest.mark.parametrize("agent_id", ["ab", "contains space", "bad/id", "x" * 513])
def test_invalid_studio_agent_id_is_rejected(tmp_path, agent_id):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Bound", token=_jwt())

    with pytest.raises(ValueError, match="Invalid Studio agent ID"):
        store.set_studio_agent_id(account.id, agent_id)

    assert account.studio_agent_id == ""


@pytest.mark.parametrize(
    "token",
    ["", _jwt(tid=""), _jwt(oid=""), "not-a-jwt"],
)
def test_binding_requires_a_valid_current_m365_subject(tmp_path, token):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="No Subject", token=token)

    with pytest.raises(ValueError, match="valid M365 subject"):
        store.set_studio_agent_id(account.id, AGENT_ID)

    assert account.studio_agent_id == ""


def test_public_serializers_only_expose_subject_checked_ready_boolean(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Bound", token=_jwt())
    store.set_studio_agent_id(account.id, AGENT_ID)

    for public in (account_public(account), user_account_public(account)):
        assert public is not None
        assert public["studio_agent_ready"] is True
        assert "studio_agent_id" not in public
        assert "studio_agent_tenant_id" not in public
        assert "studio_agent_object_id" not in public
        assert AGENT_ID not in json.dumps(public)

    account.token = _jwt(tid="tenant-b", oid="object-b")
    assert account_public(account)["studio_agent_ready"] is False


def test_matching_token_rotation_preserves_studio_binding(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Bound", token=_jwt())
    store.set_studio_agent_id(account.id, AGENT_ID)

    store.update_token(account.id, _jwt())

    assert account.studio_agent_id == AGENT_ID
    assert account.studio_agent_ready is True


def test_studio_client_snapshot_keeps_token_and_agent_from_one_locked_subject(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    original_token = _jwt()
    account = store.add(name="Bound", token=original_token)
    store.set_studio_agent_id(account.id, AGENT_ID)

    snapshot = store.studio_client_snapshot(account.id)
    store.update_token(account.id, _jwt(tid="tenant-b", oid="object-b"))

    assert snapshot == (original_token, AGENT_ID)
    assert store.studio_client_snapshot(account.id) is None


def test_token_subject_change_clears_studio_binding(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Bound", token=_jwt())
    store.set_studio_agent_id(account.id, AGENT_ID)

    store.update_token(account.id, _jwt(tid="tenant-b", oid="object-b"))

    assert account.studio_agent_id == ""
    assert account.studio_agent_tenant_id == ""
    assert account.studio_agent_object_id == ""
    assert account.studio_agent_ready is False


def test_refresh_token_subject_change_clears_studio_binding(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    original_token = _jwt()
    account = store.add(name="Bound", token=original_token)
    store.set_studio_agent_id(account.id, AGENT_ID)
    store.set_refresh_token(account.id, "refresh-a")

    refreshed = store.apply_refresh_token_result(
        account.id,
        expected_refresh_token="refresh-a",
        expected_access_token=original_token,
        access_token=_jwt(tid="tenant-b", oid="object-b"),
    )

    assert refreshed is account
    assert account.studio_agent_id == ""
    assert account.studio_agent_tenant_id == ""
    assert account.studio_agent_object_id == ""
    assert account.studio_agent_ready is False


def test_clear_credentials_clears_studio_binding(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Bound", token=_jwt())
    store.set_studio_agent_id(account.id, AGENT_ID)

    store.clear_credentials(account.id)

    assert account.studio_agent_id == ""
    assert account.studio_agent_tenant_id == ""
    assert account.studio_agent_object_id == ""
    assert account.studio_agent_ready is False


def test_switching_to_consumer_clears_studio_binding(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(name="Bound", token=_jwt())
    store.set_studio_agent_id(account.id, AGENT_ID)

    store.set_consumer_auth(
        account.id,
        [{"name": "cookie", "value": "fake"}],
        "fake-consumer-token",
        consumer_account_id="home:fake-account",
    )

    assert account.provider == "consumer"
    assert account.studio_agent_id == ""
    assert account.studio_agent_tenant_id == ""
    assert account.studio_agent_object_id == ""
    assert account.studio_agent_ready is False


def test_admin_explicitly_binds_and_unbinds_studio_agent(tmp_path):
    app, client = _admin_client(tmp_path)
    account = app.state.account_store.add(name="Bound", token=_jwt())

    bound = client.post(
        f"/admin/accounts/{account.id}/studio-agent",
        json={"agent_id": AGENT_ID},
    )

    assert bound.status_code == 200
    assert bound.json()["account"]["studio_agent_ready"] is True
    assert AGENT_ID not in bound.text
    stored = app.state.account_store.get(account.id)
    assert stored is not None and stored.studio_agent_id == AGENT_ID

    cleared = client.post(
        f"/admin/accounts/{account.id}/studio-agent",
        json={"agent_id": ""},
    )

    assert cleared.status_code == 200
    assert cleared.json()["account"]["studio_agent_ready"] is False
    assert stored.studio_agent_id == ""


def test_admin_rejects_invalid_binding_without_changing_existing_one(tmp_path):
    app, client = _admin_client(tmp_path)
    account = app.state.account_store.add(name="Bound", token=_jwt())
    app.state.account_store.set_studio_agent_id(account.id, AGENT_ID)

    response = client.post(
        f"/admin/accounts/{account.id}/studio-agent",
        json={"agent_id": "bad id"},
    )

    assert response.status_code == 400
    assert account.studio_agent_id == AGENT_ID


def test_admin_requires_agent_id_field_before_clearing_existing_binding(tmp_path):
    app, client = _admin_client(tmp_path)
    account = app.state.account_store.add(name="Bound", token=_jwt())
    app.state.account_store.set_studio_agent_id(account.id, AGENT_ID)

    response = client.post(f"/admin/accounts/{account.id}/studio-agent", json={})

    assert response.status_code == 400
    assert account.studio_agent_id == AGENT_ID


@pytest.mark.parametrize("body", [[], "agent", 7, None])
def test_admin_rejects_non_object_binding_body(tmp_path, body):
    app, client = _admin_client(tmp_path)
    account = app.state.account_store.add(name="Bound", token=_jwt())

    response = client.post(
        f"/admin/accounts/{account.id}/studio-agent",
        json=body,
    )

    assert response.status_code == 400
