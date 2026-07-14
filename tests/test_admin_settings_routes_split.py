from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_settings import register_admin_settings_routes


def test_admin_settings_routes_are_registered_by_settings_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_settings_routes)
    assert "/admin/tone" in paths
    assert "/admin/runtime-settings" in paths
    assert "/admin/tool-prompt" in paths
    assert "/admin/system-prompt" in paths


def test_runtime_settings_returns_default_media_suffixes(tmp_path):
    client = TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")))

    response = client.get("/admin/runtime-settings")

    assert response.status_code == 200
    suffixes = response.json()["settings"]["media_proxy_suffixes"]
    for suffix in ["png", "webp", "wav", "mkv", "pptx", "xlsx", "py", "tsx", "dockerfile"]:
        assert suffix in suffixes


def test_runtime_settings_saves_normalized_media_suffixes(tmp_path):
    client = TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")))

    response = client.post("/admin/runtime-settings", json={"media_proxy_suffixes": [".GLB", " wasm ", "bad/name", "", "py"]})

    assert response.status_code == 200
    suffixes = response.json()["settings"]["media_proxy_suffixes"]
    assert "glb" in suffixes
    assert "wasm" in suffixes
    assert "py" in suffixes
    assert "bad/name" not in suffixes
    reloaded = TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")))
    assert "glb" in reloaded.get("/admin/runtime-settings").json()["settings"]["media_proxy_suffixes"]


def test_user_log_flags_default_from_env(tmp_path):
    client = TestClient(create_app(Settings(
        TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="",
        LOG_USER_VERBOSE=False, LOG_USER_ERRORS=True,
    )))

    settings = client.get("/admin/runtime-settings").json()["settings"]

    assert settings["user_log_verbose"] is False
    assert settings["user_log_errors"] is True


def test_user_log_flags_web_override_persists_and_updates_flags(tmp_path):
    from m365_copilot_openai_proxy import runtime_flags

    client = TestClient(create_app(Settings(
        TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="",
        LOG_USER_VERBOSE=True, LOG_USER_ERRORS=True,
    )))

    response = client.post("/admin/runtime-settings", json={"user_log_verbose": False})

    assert response.status_code == 200
    assert response.json()["settings"]["user_log_verbose"] is False
    # Web override must update the live process-wide flag, not just persist.
    assert runtime_flags.VERBOSE_USER_LOGS is False
    # And it survives a restart (file overrides the .env default).
    reloaded = TestClient(create_app(Settings(
        TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="",
        LOG_USER_VERBOSE=True, LOG_USER_ERRORS=True,
    )))
    assert reloaded.get("/admin/runtime-settings").json()["settings"]["user_log_verbose"] is False

    runtime_flags.set_flags(verbose=True, errors=True)
