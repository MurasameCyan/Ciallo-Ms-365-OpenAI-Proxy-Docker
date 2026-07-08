from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.media_proxy_events import append_media_proxy_event


def test_admin_media_proxy_events_return_version_and_short_circuit_unchanged_payload(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)

    initial = client.get("/admin/media-proxy/events").json()
    assert initial == {"version": 0, "count": 0, "events": []}

    append_media_proxy_event(app.state, "med_1", "direct_response", status_code=401, duration_ms=12)
    changed = client.get("/admin/media-proxy/events?version=0").json()
    assert changed["version"] == 1
    assert changed["count"] == 1
    assert changed["events"][0]["trace_id"] == "med_1"
    assert changed["events"][0]["phase"] == "direct_response"
    assert changed["events"][0]["status_code"] == 401

    unchanged = client.get(f"/admin/media-proxy/events?version={changed['version']}").json()
    assert unchanged == {"version": changed["version"], "unchanged": True, "count": 1, "events": []}


def test_admin_media_proxy_events_clear_bumps_version(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)
    append_media_proxy_event(app.state, "med_1", "ok")

    response = client.post("/admin/media-proxy/events/clear")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": 2}
    assert app.state.media_proxy_events == []

