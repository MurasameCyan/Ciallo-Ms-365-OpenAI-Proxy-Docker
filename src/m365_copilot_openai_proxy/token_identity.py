from __future__ import annotations

from typing import Any

from .token_store import decode_jwt_payload, write_username


def extract_username_from_token(token: str) -> str | None:
    try:
        claims = decode_jwt_payload(token)
    except Exception:
        return None
    name = claims.get("name") or claims.get("upn") or ""
    if isinstance(name, str):
        name = name.strip()
        if "@" in name and " " not in name:
            name = name.split("@")[0]
    if isinstance(name, str) and len(name) > 1:
        return name
    return None


def update_username_from_token(token: str, state: Any) -> None:
    if getattr(state, "username", None) and len(state.username) > 1:
        return
    name = extract_username_from_token(token)
    if name:
        state.username = name
        write_username(name)
