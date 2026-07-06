from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="api-key", ADMIN_PASSWORD="admin-pass")))


def test_admin_api_requires_login(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/admin/summary")

    assert response.status_code == 401
    assert response.json() == {"error": {"message": "Admin authentication required", "type": "auth_error"}}


def test_admin_api_allows_logged_in_session(tmp_path):
    client = make_client(tmp_path)

    login = client.post("/admin/login", json={"password": "admin-pass"})
    response = client.get("/admin/summary")

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["accounts_total"] == 0


def test_admin_page_shows_login_form_before_login(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/admin")

    assert response.status_code == 200
    assert 'id="pw" type="password"' in response.text


def test_admin_logout_clears_session_for_admin_api(tmp_path):
    client = make_client(tmp_path)

    assert client.post("/admin/login", json={"password": "admin-pass"}).status_code == 200
    assert client.get("/admin/summary").status_code == 200

    logout = client.post("/admin/logout")
    response = client.get("/admin/summary")

    assert logout.status_code == 200
    assert response.status_code == 401
