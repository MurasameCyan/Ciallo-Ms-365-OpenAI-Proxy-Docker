from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.refresh_cookie_inject import _apply_opportunistic_token


def _jwt(claims: dict) -> str:
    """Build a decodable (unsigned) JWT whose payload carries the given claims."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _store(tmp_path):
    return create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")).state.account_store


def test_opportunistic_token_written_when_identity_matches(tmp_path):
    # A CDP-captured token whose identity matches the account may be written,
    # giving the account a real token + positive expiry so keepalive is armed.
    store = _store(tmp_path)
    token = _jwt({"email": "Gayhub@office.bo.edu.kg", "aud": "https://substrate.office.com"})
    acc = store.add(name="Gayhub", token=token, token_source="cdp")

    wrote = _apply_opportunistic_token(store, acc.id, "gayhub@office.bo.edu.kg", token)

    assert wrote is True
    updated = store.get(acc.id)
    assert updated.token == token
    assert updated.token_source == "cdp"
    assert updated.cookie_valid is True
    # A positive expiry is what arms keepalive; it must be ~12h in the future.
    assert updated.cookie_expires_at > time.time() + 11 * 60 * 60


def test_opportunistic_token_rejected_on_identity_mismatch(tmp_path):
    # The identity guard is mandatory: a shared profile can retain another
    # tenant's session, so a mismatched token must never be written.
    store = _store(tmp_path)
    acc = store.add(name="Gayhub", token="", token_source="cdp")
    other = _jwt({"email": "someone-else@office.bo.edu.kg"})

    wrote = _apply_opportunistic_token(store, acc.id, "gayhub@office.bo.edu.kg", other)

    assert wrote is False
    updated = store.get(acc.id)
    assert updated.token == ""
    assert updated.cookie_expires_at == 0.0


def test_opportunistic_token_noop_when_nothing_grabbed(tmp_path):
    # No token captured (the common no-nudge miss): leave the account untouched
    # for the background ensure_fresh to handle.
    store = _store(tmp_path)
    acc = store.add(name="Gayhub", token="", token_source="cdp")

    wrote = _apply_opportunistic_token(store, acc.id, "gayhub@office.bo.edu.kg", None)

    assert wrote is False
    assert store.get(acc.id).token == ""
