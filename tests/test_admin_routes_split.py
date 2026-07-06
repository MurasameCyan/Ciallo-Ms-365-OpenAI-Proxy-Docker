from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin import register_admin_account_key_routes


def test_admin_account_and_key_routes_are_registered_by_admin_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_account_key_routes)
    assert "/admin/accounts" in paths
    assert "/admin/accounts/{acc_id}/token" in paths
    assert "/admin/accounts/{acc_id}/token/clear" in paths
    assert "/admin/accounts/{acc_id}/rename" in paths
    assert "/admin/accounts/{acc_id}/refresh" in paths
    assert "/admin/accounts/{acc_id}/cookie-refresh" in paths
    assert "/admin/keys" in paths
    assert "/admin/keys/{key_id}" in paths
    assert "/admin/keys/{key_id}/regenerate" in paths
