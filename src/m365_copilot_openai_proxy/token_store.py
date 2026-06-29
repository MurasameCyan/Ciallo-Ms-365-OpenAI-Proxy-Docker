from __future__ import annotations

import base64
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUBSTRATE_AUDIENCE_PREFIX = "https://substrate.office.com/"


def decode_jwt_payload(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def is_substrate_token_claims(claims: dict[str, Any]) -> bool:
    return str(claims.get("aud", "")).startswith(SUBSTRATE_AUDIENCE_PREFIX)


class AccessTokenStore:
    def __init__(self, token: str, env_path: Path | str = ".env"):
        self._token = token
        self._env_path = Path(env_path)
        self._mtime_ns = self._read_mtime()
        self._lock = threading.RLock()

    def get(self) -> str:
        with self._lock:
            self._reload_if_changed()
            return self._token

    def status(self) -> dict[str, Any]:
        token = self.get()
        now = time.time()
        try:
            claims = decode_jwt_payload(token)
            if not is_substrate_token_claims(claims):
                return {
                    "valid": False,
                    "error": "Access token is not a substrate.office.com token.",
                    "expires_at": None,
                    "seconds_remaining": 0,
                }
            expires_at = int(claims["exp"])
        except Exception as exc:
            return {
                "valid": False,
                "error": f"Cannot decode access token: {exc}",
                "expires_at": None,
                "seconds_remaining": 0,
            }

        seconds_remaining = max(0, expires_at - int(now))
        return {
            "valid": seconds_remaining > 0,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
            "seconds_remaining": seconds_remaining,
        }

    def _reload_if_changed(self) -> None:
        mtime_ns = self._read_mtime()
        if mtime_ns is None or mtime_ns == self._mtime_ns:
            return
        token = _read_env_token(self._env_path)
        if token:
            self._token = token
            self._mtime_ns = mtime_ns

    def _read_mtime(self) -> int | None:
        try:
            return self._env_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None


def _read_env_token(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if sep and key.strip() == "M365_ACCESS_TOKEN":
            return _clean_env_value(value)
    return None


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
