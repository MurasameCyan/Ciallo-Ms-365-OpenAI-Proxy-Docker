from __future__ import annotations

from .account_store import Account
from .key_store import ApiKey


def account_binding_state(acc: Account | None) -> str:
    if acc is None:
        return "none"
    if getattr(acc, "cookie_valid", False):
        return "cookie"
    if acc.token:
        return "token_only"
    return "none"


def user_account_public(acc: Account | None) -> dict | None:
    if acc is None:
        return None
    binding_state = account_binding_state(acc)
    return {
        "id": acc.id,
        "name": acc.name,
        "email": acc.email,
        "token_source": acc.token_source,
        "binding_state": binding_state,
        "updated_at": acc.updated_at,
        "has_token": bool(acc.token),
        "cookie_valid": bool(getattr(acc, "cookie_valid", False)),
        "cookie_updated_at": getattr(acc, "cookie_updated_at", 0.0),
        "cookie_expires_at": getattr(acc, "cookie_expires_at", 0.0),
        "token_status": acc.token_status(),
    }


def account_public(acc: Account, bound_keys: list[ApiKey] | None = None) -> dict:
    keys = bound_keys or []
    binding_state = account_binding_state(acc)
    return {
        "id": acc.id,
        "name": acc.name,
        "email": acc.email,
        "cdp_port": acc.cdp_port,
        "token_source": acc.token_source,
        "binding_state": binding_state,
        "cookie_valid": bool(getattr(acc, "cookie_valid", False)),
        "cookie_updated_at": getattr(acc, "cookie_updated_at", 0.0),
        "cookie_expires_at": getattr(acc, "cookie_expires_at", 0.0),
        "has_token": bool(acc.token),
        "token_status": acc.token_status(),
        "key_count": len(keys),
        "bound_names": [k.name or k.username or k.id for k in keys],
        "created_at": acc.created_at,
        "updated_at": acc.updated_at,
    }
