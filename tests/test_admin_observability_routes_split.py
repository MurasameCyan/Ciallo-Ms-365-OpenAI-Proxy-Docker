from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_observability import register_admin_observability_routes
from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS


def test_admin_observability_routes_are_registered_by_observability_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_observability_routes)
    assert "/admin/call-log" in paths
    assert "/admin/call-log/clear" in paths
    assert "/admin/metrics-history" in paths
    assert "/admin/metrics-history/clear" in paths
    assert "/admin/summary" in paths


def test_admin_trend_chart_uses_stable_polyline_rendering_with_breathing_glow():
    start = _ADMIN_HTML.index("function lineChart(points,series){")
    end = _ADMIN_HTML.index("async function loadSummary()", start)
    chart_code = _ADMIN_HTML[start:end]

    assert chart_code.count("<polyline") >= 2
    assert 'attributeName="opacity"' in chart_code
    assert "smoothPath" not in chart_code
    assert "<path" not in chart_code
    assert "drop-shadow" not in chart_code


def test_admin_tone_share_bars_use_breathing_fill_effect():
    start = _ADMIN_HTML.index("async function loadStats()")
    end = _ADMIN_HTML.index("// Expiry warnings", start)
    load_stats_code = _ADMIN_HTML[start:end]

    assert ".tone-share-fill" in _ADMIN_HTML
    assert "@keyframes toneShareBreath" in _ADMIN_HTML
    assert "animation:toneShareBreath" in _ADMIN_HTML
    assert 'class="tone-share-fill"' in load_stats_code


def test_admin_dashboard_javascript_is_split_into_dashboard_module():
    assert "function lineChart(points,series){" in _ADMIN_DASHBOARD_JS
    assert "async function loadStats()" in _ADMIN_DASHBOARD_JS
    assert "async function loadTrend()" in _ADMIN_DASHBOARD_JS
    assert _ADMIN_DASHBOARD_JS in _ADMIN_HTML
