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


def test_runtime_settings_saves_live_consumer_mode_options(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)

    response = client.post(
        "/admin/runtime-settings",
        json={
            "consumer_mode_options": [
                {
                    "model": " Custom-Model ",
                    "mode": " custom-mode ",
                    "status": " STABLE ",
                },
                {
                    "model": "reasoning-alias",
                    "mode": "reasoning",
                    "status": "experimental",
                },
            ],
        },
    )

    expected = [
        {"model": "custom-model", "mode": "custom-mode", "status": "stable"},
        {
            "model": "reasoning-alias",
            "mode": "reasoning",
            "status": "experimental",
        },
    ]
    assert response.status_code == 200
    assert response.json()["settings"]["consumer_mode_options"] == expected
    assert app.state.runtime_settings["consumer_mode_options"] == expected
    assert app.state.consumer_mode_options == expected

    reloaded = TestClient(create_app(Settings(
        TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="",
    )))
    assert reloaded.get("/admin/runtime-settings").json()["settings"]["consumer_mode_options"] == expected


def test_runtime_settings_rejects_invalid_consumer_modes_without_side_effects(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)
    baseline = client.post(
        "/admin/runtime-settings",
        json={
            "model_alias": "baseline-alias",
            "consumer_mode_options": [
                {"model": "baseline", "mode": "smart", "status": "stable"},
            ],
        },
    )
    assert baseline.status_code == 200
    settings_path = tmp_path / "runtime_settings.json"
    before_bytes = settings_path.read_bytes()
    before_runtime_settings = app.state.runtime_settings
    before_consumer_options = app.state.consumer_mode_options

    response = client.post(
        "/admin/runtime-settings",
        json={
            "model_alias": "must-not-apply",
            "consumer_mode_options": (
                "ok | smart | stable\n"
                "bad | | experimental"
            ),
        },
    )

    assert response.status_code == 400
    assert "line 2" in response.json()["error"]["message"]
    assert "mode must not be empty" in response.json()["error"]["message"]
    assert settings_path.read_bytes() == before_bytes
    assert app.state.runtime_settings is before_runtime_settings
    assert app.state.consumer_mode_options is before_consumer_options
    assert app.state.model_alias == "baseline-alias"


def test_runtime_settings_reset_lists_are_independent(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)
    custom_tones = [{"value": "CustomTone", "label_zh": "Custom_Model"}]
    custom_consumer = [
        {"model": "custom-consumer", "mode": "reasoning", "status": "experimental"},
    ]

    saved = client.post(
        "/admin/runtime-settings",
        json={
            "tone_options": custom_tones,
            "consumer_mode_options": custom_consumer,
        },
    ).json()["settings"]
    normalized_custom_tones = saved["tone_options"]

    consumer_reset = client.post(
        "/admin/runtime-settings",
        json={"consumer_mode_options": []},
    )
    assert consumer_reset.status_code == 200
    consumer_reset_settings = consumer_reset.json()["settings"]
    assert [
        option["model"] for option in consumer_reset_settings["consumer_mode_options"]
    ] == [
        "copilot-reasoning",
        "copilot-thinking",
        "copilot-research",
        "copilot-coco",
        "copilot-search",
        "copilot",
        "copilot-smart",
        "copilot-chat",
        "copilot-study",
    ]
    assert consumer_reset_settings["tone_options"] == normalized_custom_tones

    client.post(
        "/admin/runtime-settings",
        json={"consumer_mode_options": custom_consumer},
    )
    tone_reset = client.post(
        "/admin/runtime-settings",
        json={"tone_options": []},
    )
    assert tone_reset.status_code == 200
    tone_reset_settings = tone_reset.json()["settings"]
    assert tone_reset_settings["consumer_mode_options"] == custom_consumer
    assert tone_reset_settings["tone_options"] != normalized_custom_tones


def test_suppress_access_log_default_from_env(tmp_path):
    client = TestClient(create_app(Settings(
        TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="",
        SUPPRESS_ACCESS_LOG=False,
    )))

    settings = client.get("/admin/runtime-settings").json()["settings"]

    assert settings["suppress_access_log"] is False


def test_suppress_access_log_web_override_persists_and_updates_flag(tmp_path):
    from m365_copilot_openai_proxy import runtime_flags

    client = TestClient(create_app(Settings(
        TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="",
        SUPPRESS_ACCESS_LOG=True,
    )))

    response = client.post("/admin/runtime-settings", json={"suppress_access_log": False})

    assert response.status_code == 200
    assert response.json()["settings"]["suppress_access_log"] is False
    # Web override must update the live process-wide flag, not just persist.
    assert runtime_flags.SUPPRESS_ACCESS_LOG is False
    # And it survives a restart (file overrides the .env default).
    reloaded = TestClient(create_app(Settings(
        TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="",
        SUPPRESS_ACCESS_LOG=True,
    )))
    assert reloaded.get("/admin/runtime-settings").json()["settings"]["suppress_access_log"] is False

    runtime_flags.set_flags(suppress_access_log=True)


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


def test_run_permission_web_override_applies_without_restart(tmp_path):
    from m365_copilot_openai_proxy.routes_api_common import effective_run_permission

    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)
    assert effective_run_permission(app, None) == "full"

    response = client.post("/admin/runtime-settings", json={"run_permission": "read_only"})

    assert response.status_code == 200
    # Asserted through the reader every turn actually calls: the saved value used
    # to reach runtime_settings while app.state kept the boot value, so a switch
    # to read_only persisted, displayed, and still executed writes until restart.
    assert effective_run_permission(app, None) == "read_only"

    rejected = client.post("/admin/runtime-settings", json={"run_permission": "read-only"})

    assert rejected.status_code == 400
    assert effective_run_permission(app, None) == "read_only"
