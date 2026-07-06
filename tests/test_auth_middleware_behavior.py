from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


def make_client(tmp_path, api_key: str = "admin-key") -> TestClient:
    return TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY=api_key, ADMIN_PASSWORD="admin-pass")))


def test_public_paths_bypass_api_key_auth(tmp_path):
    client = make_client(tmp_path)

    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/admin").status_code == 200
    assert client.get("/favicon.ico").status_code == 204


def test_v1_requires_api_key_when_legacy_key_is_configured(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/v1/models")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid API key"


def test_v1_accepts_legacy_api_key(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/v1/models", headers={"Authorization": "Bearer admin-key"})

    assert response.status_code == 200
    assert response.json()["object"] == "list"


def test_v1_is_open_when_no_legacy_or_registered_keys_exist(tmp_path):
    client = make_client(tmp_path, api_key="")

    response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json()["object"] == "list"


def test_v1_accepts_registered_enabled_key(tmp_path):
    client = make_client(tmp_path)
    key = client.app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 200
    assert response.json()["object"] == "list"


def test_v1_rejects_registered_disabled_key(tmp_path):
    client = make_client(tmp_path)
    key = client.app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")
    client.app.state.key_store.update(key.id, enabled=False)

    response = client.get("/v1/models", headers={"Authorization": f"Bearer {key.key}"})

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "API key is disabled"


def test_auth_error_preserves_allowed_cors_origin(tmp_path, monkeypatch):
    origin = "https://client.example"
    monkeypatch.setenv("ALLOWED_ORIGINS", origin)
    client = make_client(tmp_path)

    response = client.get("/v1/models", headers={"Origin": origin})

    assert response.status_code == 401
    assert response.headers.get("access-control-allow-origin") == origin


def test_v1_request_updates_last_request_time(tmp_path):
    client = make_client(tmp_path)

    assert client.app.state.last_request_time == 0

    response = client.get("/v1/models", headers={"Authorization": "Bearer admin-key"})

    assert response.status_code == 200
    assert client.app.state.last_request_time > 0
