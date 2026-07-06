from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_debug import register_admin_debug_routes


def test_admin_capture_payload_returns_version_and_short_circuits_unchanged_payload(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    app.state.capture_enabled = True
    client = TestClient(app)

    initial = client.get("/admin/capture-payload").json()
    assert initial["version"] == 0
    assert initial["payloads"] == []

    pushed = client.post("/admin/capture-payload", json={"payloads": [{"time": "12:00:00", "tone": "Magic"}]})
    assert pushed.status_code == 200

    changed = client.get("/admin/capture-payload?version=0").json()
    assert changed["version"] > 0
    assert changed["count"] == 1
    assert changed["payloads"] == [{"time": "12:00:00", "tone": "Magic"}]

    unchanged = client.get(f"/admin/capture-payload?version={changed['version']}").json()
    assert unchanged == {
        "version": changed["version"],
        "unchanged": True,
        "count": 1,
        "payloads": [],
    }


def test_admin_debug_routes_are_registered_by_debug_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_debug_routes)
    assert "/admin/stats" in paths
    assert "/admin/capture-payload" in paths
    assert "/admin/capture-payload/clear" in paths
    assert "/admin/capture-toggle" in paths
