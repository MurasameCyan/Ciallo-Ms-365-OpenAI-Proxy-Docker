"""/admin/sessions* and /user/sessions* contract.

Cloud calls are stubbed: what matters here is the wiring around them -- that a
broken cloud account still yields the local rows plus a warning, that a user is
confined to their own sessions on a shared account, and that cleanup protects the
conversations live sessions still point at.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy import routes_sessions
from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.m365_cloud_client import CloudSessionError


def _chat(conversation_id: str, name: str = "Chat", updated_ms: float | None = None) -> dict:
    stamp = updated_ms if updated_ms is not None else time.time() * 1000
    return {
        "conversationId": conversation_id,
        "chatName": name,
        "createTimeUtc": stamp,
        "updateTimeUtc": stamp,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """App + admin client + one account with two users bound to it."""
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    admin = TestClient(app)
    assert admin.post("/admin/login", json={"password": "admin-key"}).status_code == 200
    account = app.state.account_store.add(name="Pool", token="")
    alice = app.state.key_store.add(name="alice", account_id=account.id)
    bob = app.state.key_store.add(name="bob", account_id=account.id)

    calls: dict[str, list] = {"list": [], "delete": [], "cleanup": []}
    cloud: dict[str, list[dict]] = {account.id: []}

    async def fake_list(accounts, account_id):
        calls["list"].append(account_id)
        listing = cloud.get(account_id)
        if listing is None:
            raise CloudSessionError("no refresh token stored for this account")
        return listing

    async def fake_delete(accounts, account_id, conversation_id):
        calls["delete"].append((account_id, conversation_id))
        cloud[account_id] = [c for c in cloud.get(account_id, []) if c["conversationId"] != conversation_id]

    async def fake_cleanup(accounts, account_id, older_than=0.0, keep_newest=0, protected=None):
        calls["cleanup"].append((account_id, older_than, keep_newest, set(protected or set())))
        return 0, []

    monkeypatch.setattr(routes_sessions, "list_conversations", fake_list)
    monkeypatch.setattr(routes_sessions, "delete_conversation", fake_delete)
    monkeypatch.setattr(routes_sessions, "cleanup_conversations", fake_cleanup)

    def user_client(key):
        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {key.key}"
        return client

    return {
        "app": app, "admin": admin, "account": account, "alice": alice, "bob": bob,
        "cloud": cloud, "calls": calls, "user_client": user_client,
    }


def _session(app, store_key: str, conversation_id: str, last_accessed: float | None = None):
    session = app.state.session_store.get(store_key)
    session.conversation_id = conversation_id
    if last_accessed is not None:
        session.last_accessed = last_accessed
    return session


def test_admin_list_merges_local_sessions_with_cloud_conversations(env):
    app, cloud = env["app"], env["cloud"]
    _session(app, f"{env['alice'].id}:auto:conv_x", "cid-local")
    cloud[env["account"].id] = [_chat("cid-local", "Named upstream"), _chat("cid-orphan", "Orphan")]

    body = env["admin"].get("/admin/sessions").json()

    rows = {row["conversation_id"]: row for row in body["data"]}
    assert body["count"] == 2
    assert rows["cid-local"]["source"] == "both"
    assert rows["cid-local"]["chat_name"] == "Named upstream"
    assert rows["cid-local"]["username"] == env["alice"].username
    assert rows["cid-orphan"]["source"] == "cloud"
    assert rows["cid-orphan"]["store_key"] == ""


def test_admin_list_filters_by_user(env):
    app = env["app"]
    _session(app, f"{env['alice'].id}:auto:a", "cid-a")
    _session(app, f"{env['bob'].id}:auto:b", "cid-b")

    body = env["admin"].get(f"/admin/sessions?key_id={env['alice'].id}").json()

    assert [row["conversation_id"] for row in body["data"]] == ["cid-a"]
    assert env["admin"].get("/admin/sessions?key_id=nope").status_code == 404


def test_unavailable_cloud_reports_a_warning_and_still_lists_local_sessions(env):
    app = env["app"]
    env["cloud"].pop(env["account"].id)  # account without a usable refresh token
    _session(app, f"{env['alice'].id}:auto:a", "cid-a")

    body = env["admin"].get("/admin/sessions").json()

    assert [row["conversation_id"] for row in body["data"]] == ["cid-a"]
    assert body["warnings"] and "refresh token" in body["warnings"][0]


def test_user_sees_only_own_sessions_and_no_foreign_cloud_rows(env):
    app, cloud = env["app"], env["cloud"]
    _session(app, f"{env['alice'].id}:auto:a", "cid-a")
    _session(app, f"{env['bob'].id}:auto:b", "cid-b")
    cloud[env["account"].id] = [_chat("cid-a"), _chat("cid-b"), _chat("cid-other")]

    body = env["user_client"](env["alice"]).get("/user/sessions").json()

    assert [row["conversation_id"] for row in body["data"]] == ["cid-a"]
    assert body["data"][0]["source"] == "both"


def test_user_delete_uses_its_own_conversation_id_and_clears_the_local_binding(env):
    app = env["app"]
    _session(app, f"{env['alice'].id}:auto:a", "cid-a")
    env["cloud"][env["account"].id] = [_chat("cid-a"), _chat("cid-b")]

    response = env["user_client"](env["alice"]).post(
        "/user/sessions/delete",
        json={"store_key": f"{env['alice'].id}:auto:a", "conversation_id": "cid-b", "cloud": True},
    )

    assert response.status_code == 200
    assert response.json()["deleted_cloud"] is True
    # Body-supplied ids are ignored: only the caller's own conversation goes.
    assert env["calls"]["delete"] == [(env["account"].id, "cid-a")]
    assert app.state.session_store.get_existing(f"{env['alice'].id}:auto:a") is None


def test_user_cannot_touch_another_users_session(env):
    app = env["app"]
    _session(app, f"{env['bob'].id}:auto:b", "cid-b")

    response = env["user_client"](env["alice"]).post(
        "/user/sessions/delete", json={"store_key": f"{env['bob'].id}:auto:b"}
    )

    assert response.status_code == 404
    assert app.state.session_store.get_existing(f"{env['bob'].id}:auto:b") is not None
    assert env["calls"]["delete"] == []


def test_admin_cleanup_keeps_the_newest_and_protects_live_conversations(env):
    app = env["app"]
    now = time.time()
    _session(app, f"{env['alice'].id}:auto:old", "cid-old", last_accessed=now - 7200)
    _session(app, f"{env['alice'].id}:auto:new", "cid-new", last_accessed=now)

    body = env["admin"].post(
        "/admin/sessions/cleanup",
        json={"key_id": env["alice"].id, "keep": 1, "ttl_hours": 1, "cloud": True},
    ).json()

    assert body["removed_local"] == [f"{env['alice'].id}:auto:old"]
    assert app.state.session_store.get_existing(f"{env['alice'].id}:auto:new") is not None
    _account, older_than, keep_newest, protected = env["calls"]["cleanup"][0]
    assert (older_than, keep_newest) == (3600.0, 1)
    assert "cid-new" in protected  # a session still using it must survive upstream


def test_cleanup_whitelist_pins_a_session(env):
    app = env["app"]
    _session(app, f"{env['alice'].id}:auto:pinned", "cid-pinned", last_accessed=time.time() - 99999)

    body = env["admin"].post(
        "/admin/sessions/cleanup",
        json={
            "key_id": env["alice"].id,
            "ttl_hours": 1,
            "keep_ids": [f"{env['alice'].id}:auto:pinned"],
            "cloud": False,
        },
    ).json()

    assert body["removed_local"] == []
    assert app.state.session_store.get_existing(f"{env['alice'].id}:auto:pinned") is not None


def test_user_cleanup_only_deletes_cloud_conversations_it_dropped(env):
    app = env["app"]
    now = time.time()
    _session(app, f"{env['alice'].id}:auto:old", "cid-old", last_accessed=now - 7200)
    _session(app, f"{env['alice'].id}:auto:new", "cid-new", last_accessed=now)
    _session(app, f"{env['bob'].id}:auto:old", "cid-bob", last_accessed=now - 7200)
    env["cloud"][env["account"].id] = [_chat("cid-old"), _chat("cid-new"), _chat("cid-bob")]

    body = env["user_client"](env["alice"]).post(
        "/user/sessions/cleanup", json={"ttl_hours": 1, "cloud": True}
    ).json()

    assert body["removed_local"] == [f"{env['alice'].id}:auto:old"]
    assert body["deleted_cloud"] == ["cid-old"]
    # Never the account-wide sweep: another user's history on the shared account
    # is untouched, and so is this user's live session.
    assert env["calls"]["cleanup"] == []
    assert app.state.session_store.get_existing(f"{env['bob'].id}:auto:old") is not None


def test_admin_delete_of_a_cloud_only_row_clears_matching_local_bindings(env):
    app = env["app"]
    _session(app, f"{env['bob'].id}:auto:b", "cid-shared")
    env["cloud"][env["account"].id] = [_chat("cid-shared")]

    response = env["admin"].post(
        "/admin/sessions/delete",
        json={"conversation_id": "cid-shared", "account_id": env["account"].id, "cloud": True},
    )

    assert response.json()["removed_local"] == [f"{env['bob'].id}:auto:b"]
    assert app.state.session_store.get_existing(f"{env['bob'].id}:auto:b") is None


def test_session_routes_require_authentication(env):
    anonymous = TestClient(env["app"])

    assert anonymous.get("/user/sessions").status_code == 401
    assert anonymous.post("/user/sessions/delete", json={}).status_code == 401
    assert anonymous.get("/admin/sessions").status_code in (401, 403)
