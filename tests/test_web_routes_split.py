from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.build_info import resolve_build_info
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
    assert "/favicon.ico" in paths
    assert "/healthz" in paths


def test_admin_page_injects_git_hash_badge(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "1234567890abcdef")
    resolve_build_info.cache_clear()
    try:
        # Empty admin secret => /admin shell is served without login cookie.
        app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
        client = TestClient(app)
        response = client.get("/admin")
    finally:
        resolve_build_info.cache_clear()

    assert response.status_code == 200
    body = response.text
    assert 'id="side-version"' in body
    assert "1234567" in body
    assert "__APP_GIT_HASH__" not in body
    assert "/commit/1234567890abcdef" in body
