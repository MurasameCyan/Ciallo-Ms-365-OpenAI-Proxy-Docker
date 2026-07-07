from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.image_proxy_events import append_image_proxy_event


def test_admin_image_proxy_events_return_version_and_short_circuit_unchanged_payload(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)

    initial = client.get("/admin/image-proxy/events").json()
    assert initial == {"version": 0, "count": 0, "events": []}

    append_image_proxy_event(app.state, "img_1", "direct_response", status_code=401, duration_ms=12)
    changed = client.get("/admin/image-proxy/events?version=0").json()
    assert changed["version"] == 1
    assert changed["count"] == 1
    assert changed["events"][0]["trace_id"] == "img_1"
    assert changed["events"][0]["phase"] == "direct_response"
    assert changed["events"][0]["status_code"] == 401

    unchanged = client.get(f"/admin/image-proxy/events?version={changed['version']}").json()
    assert unchanged == {"version": changed["version"], "unchanged": True, "count": 1, "events": []}


def test_admin_image_proxy_events_clear_bumps_version(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)
    append_image_proxy_event(app.state, "img_1", "ok")

    response = client.post("/admin/image-proxy/events/clear")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": 2}
    assert app.state.image_proxy_events == []
