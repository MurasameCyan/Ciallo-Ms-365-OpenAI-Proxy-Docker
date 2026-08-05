from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.build_info import current_build_id, resolve_build_info
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_web import register_web_routes


def test_web_routes_are_registered_by_web_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_web_routes)
    assert "/" in paths
    assert "/admin" in paths
    assert "/admin/login" in paths
    assert "/admin/logout" in paths
    assert "/admin/system/version" in paths
    assert "/admin/system/update-check" in paths
    assert "/favicon.ico" in paths
    assert "/healthz" in paths


def test_healthz_reuses_its_result_within_the_cache_window(tmp_path, monkeypatch):
    # /healthz is unauthenticated and stats the token file plus JWT-decodes once
    # per account, so repeated anonymous polling must not redo that work.
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    client = TestClient(app)
    calls = []
    original = app.state.token_store.status
    monkeypatch.setattr(
        app.state.token_store, "status", lambda: (calls.append(1), original())[1]
    )

    first = client.get("/healthz").json()
    second = client.get("/healthz").json()

    assert first == second
    assert len(calls) == 1, "second /healthz within the TTL recomputed the status"


def test_healthz_recomputes_after_the_cache_window(tmp_path, monkeypatch):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    client = TestClient(app)
    client.get("/healthz")
    # Age the cached entry past the TTL rather than sleeping.
    stamp, body = app.state._healthz_cache
    app.state._healthz_cache = (stamp - 3600, body)
    calls = []
    original = app.state.token_store.status
    monkeypatch.setattr(
        app.state.token_store, "status", lambda: (calls.append(1), original())[1]
    )

    assert client.get("/healthz").status_code == 200
    assert len(calls) == 1, "a stale cache entry must be refreshed"


def test_admin_page_injects_git_hash_badge(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "1234567890abcdef")
    resolve_build_info.cache_clear()
    current_build_id.cache_clear()
    try:
        app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
        client = TestClient(app)
        response = client.get("/admin")
    finally:
        resolve_build_info.cache_clear()
        current_build_id.cache_clear()

    assert response.status_code == 200
    body = response.text
    assert 'id="side-build-chip"' in body
    assert 'id="side-update-btn"' in body
    assert 'id="side-repo-btn"' in body
    assert "1234567" in body
    assert "__APP_GIT_HASH__" not in body
    assert "github.com" in body


def test_admin_system_version_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "aabbccddeeff0011")
    resolve_build_info.cache_clear()
    current_build_id.cache_clear()
    try:
        app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
        client = TestClient(app)
        response = client.get("/admin/system/version")
    finally:
        resolve_build_info.cache_clear()
        current_build_id.cache_clear()

    assert response.status_code == 200
    data = response.json()
    assert data["buildId"] == "aabbccd"
    assert data["current"] == "aabbccd"
