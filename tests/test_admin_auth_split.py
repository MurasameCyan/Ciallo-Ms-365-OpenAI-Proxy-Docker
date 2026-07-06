from __future__ import annotations

import json
from types import SimpleNamespace

from m365_copilot_openai_proxy.admin_auth import create_admin_auth
from m365_copilot_openai_proxy.config import Settings


def test_create_admin_auth_uses_admin_password_and_validates_cookie():
    auth = create_admin_auth(Settings(API_KEY="api-key", ADMIN_PASSWORD="admin-pass"))

    valid_request = SimpleNamespace(cookies={"admin_auth": auth.admin_session_token})
    invalid_request = SimpleNamespace(cookies={})

    assert auth.admin_secret == "admin-pass"
    assert auth.admin_session_token
    assert auth.is_admin_authenticated(valid_request) is True
    assert auth.is_admin_authenticated(invalid_request) is False


def test_create_admin_auth_require_admin_returns_json_error_when_unauthenticated():
    auth = create_admin_auth(Settings(API_KEY="api-key", ADMIN_PASSWORD="admin-pass"))

    response = auth.require_admin(SimpleNamespace(cookies={}))

    assert response is not None
    assert response.status_code == 401
    assert json.loads(response.body) == {"error": {"message": "Admin authentication required", "type": "auth_error"}}


def test_create_admin_auth_allows_open_admin_when_no_secret_is_configured():
    auth = create_admin_auth(Settings(API_KEY="", ADMIN_PASSWORD=""))

    request = SimpleNamespace(cookies={})

    assert auth.admin_secret == ""
    assert auth.admin_session_token is None
    assert auth.is_admin_authenticated(request) is True
    assert auth.require_admin(request) is None
