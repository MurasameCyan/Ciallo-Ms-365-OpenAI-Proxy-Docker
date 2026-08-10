from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.account_serializers import (
    account_binding_state,
    account_public,
    user_account_public,
)
from m365_copilot_openai_proxy.account_store import Account
from m365_copilot_openai_proxy.key_store import ApiKey


def test_account_binding_state_matches_cookie_token_precedence():
    assert account_binding_state(None) == "none"
    assert account_binding_state(Account(name="No Binding", token="")) == "none"
    assert account_binding_state(Account(name="Token Only", token="token-value")) == "token_only"
    assert account_binding_state(Account(name="Cookie Bound", token="", cookie_valid=True)) == "cookie"
    assert account_binding_state(Account(name="Cookie Wins", token="token-value", cookie_valid=True)) == "cookie"


def test_user_account_public_matches_user_me_account_shape():
    account = Account(
        name="Microsoft User",
        email="user@example.com",
        token="token-value",
        token_source="manual",
        media_auth_token="media-token",
        designer_auth_token="designer-token",
    )

    data = user_account_public(account)

    assert data["id"] == account.id
    assert data["name"] == "Microsoft User"
    assert data["email"] == "user@example.com"
    assert data["token_source"] == "manual"
    assert data["binding_state"] == "token_only"
    assert data["has_token"] is True
    assert data["has_media_auth"] is True
    assert data["has_designer_auth"] is True
    assert data["cookie_valid"] is False
    assert "token_status" in data
    assert "media_auth_token" not in data
    assert "designer_auth_token" not in data


def test_account_public_matches_admin_account_shape_without_raw_token():
    account = Account(
        name="Cookie Bound",
        email="user@example.com",
        token="secret-token",
        token_source="cdp",
        cookie_valid=True,
        media_auth_token="media-secret-token",
        designer_auth_token="designer-secret-token",
    )
    key = ApiKey(name="Proxy User", username="proxyuser")

    data = account_public(account, [key])

    assert data["id"] == account.id
    assert data["name"] == "Cookie Bound"
    assert data["email"] == "user@example.com"
    assert data["token_source"] == "cdp"
    assert data["binding_state"] == "cookie"
    assert data["has_token"] is True
    assert data["has_media_auth"] is True
    assert data["has_designer_auth"] is True
    assert data["cookie_valid"] is True
    assert data["key_count"] == 1
    assert data["bound_names"] == ["proxyuser"]
    assert "token" not in data
    assert "media_auth_token" not in data
    assert "designer_auth_token" not in data
