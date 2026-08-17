from __future__ import annotations

import time

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


def test_admin_stats_reports_what_the_caches_are_buying(tmp_path):
    """`incremental` is the number that says whether session reuse works."""
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    now = time.time()
    app.state.call_log = [
        {"ts": now, "incremental": True},
        {"ts": now, "incremental": True},
        {"ts": now, "incremental": False},
        {"ts": now},  # entries with no flag (errors, non-chat) must not count
    ]
    app.state.session_store.get("t:model:magic").reserve_turn()
    client = TestClient(app)

    cache = client.get("/admin/stats").json()["cache"]

    assert cache["incremental_hits"] == 2
    assert cache["fresh_starts"] == 1
    assert cache["incremental_hit_rate"] == round(2 / 3, 4)
    assert cache["sessions"]["sessions"] == 1
    assert cache["sessions"]["changes"] >= 2
    assert "flush_interval" in cache["sessions"]
    assert "entries" in cache["history_index"] and "hit_rate" in cache["history_index"]
    assert "hit_rate" in cache["cloud_token"]


def test_admin_stats_cache_block_has_no_rate_before_any_traffic(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))

    cache = TestClient(app).get("/admin/stats").json()["cache"]

    assert cache["incremental_hit_rate"] is None
    assert cache["incremental_hits"] == 0 and cache["fresh_starts"] == 0


def test_dashboard_renders_the_cache_block_from_cached_stats():
    """Two-stage per the template convention: loadStats fetches, render only reads."""
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    assert 'id="dash-cache"' in _ADMIN_HTML
    assert "window.__cacheStats=d.cache||null;" in _ADMIN_DASHBOARD_JS
    assert "function renderCacheStats()" in _ADMIN_DASHBOARD_JS
    assert "if(typeof renderCacheStats==='function')renderCacheStats()" in _ADMIN_HTML
    for key in ("dash_cache_title", "dash_cache_reuse", "dash_cache_saved", "dash_cache_detail"):
        assert _ADMIN_HTML.count(f"{key}:'") == 2
