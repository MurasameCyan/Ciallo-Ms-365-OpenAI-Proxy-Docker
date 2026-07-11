from __future__ import annotations

import asyncio
import base64
import json
import time

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler


def _jwt(exp: int) -> str:
    """Build a decodable (unsigned) substrate-shaped JWT expiring at `exp`."""
    claims = {"aud": "https://substrate.office.com", "exp": exp}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _store(tmp_path) -> AccountStore:
    return AccountStore(persist_path=tmp_path / "accounts.json")


# --------------------------------------------------------------- push_token (fix A)

def test_push_token_preserves_cdp_for_account_with_valid_cookie(tmp_path):
    """A pushed token must NOT downgrade a live cdp+cookie account to manual.

    This is the regression: the Tampermonkey Auto Capture re-pushes a token to
    an account that cookie-inject already promoted to cdp; a hard "manual"
    write silently killed auto-refresh. push_token keeps it cdp.
    """
    store = _store(tmp_path)
    acc = store.add(name="a", token=_jwt(int(time.time()) + 9999))
    store.set_cookie_status(acc.id, True, token_source="cdp", expires_at=time.time() + 9999)

    store.push_token(acc.id, _jwt(int(time.time()) + 12345))

    assert store.get(acc.id).token_source == "cdp"


def test_push_token_keeps_manual_for_profileless_account(tmp_path):
    store = _store(tmp_path)
    acc = store.add(name="a", token=_jwt(int(time.time()) + 9999))  # manual, no cookie

    store.push_token(acc.id, _jwt(int(time.time()) + 12345))

    assert store.get(acc.id).token_source == "manual"


def test_push_token_downgrades_cdp_without_valid_cookie(tmp_path):
    """cdp source but the cookie session is already dead -> no profile to
    refresh from, so a pushed token legitimately falls back to manual."""
    store = _store(tmp_path)
    acc = store.add(name="a", token=_jwt(int(time.time()) + 9999))
    store.set_cookie_status(acc.id, True, token_source="cdp", expires_at=time.time() + 9999)
    store.set_cookie_status(acc.id, False)  # cookie invalidated

    store.push_token(acc.id, _jwt(int(time.time()) + 12345))

    assert store.get(acc.id).token_source == "manual"


# --------------------------------------------------------- ensure_fresh manual (fix B)

def test_ensure_fresh_returns_false_for_expired_manual_token(tmp_path):
    """Passive /v1 path: an expired manual token must yield False so the
    middleware returns 503 instead of forwarding a dead token silently."""
    store = _store(tmp_path)
    acc = store.add(name="a", token=_jwt(int(time.time()) - 10))  # already expired
    sched = RefreshScheduler(account_store=store, profile_root=tmp_path)

    assert asyncio.run(sched.ensure_fresh(acc.id)) is False


def test_ensure_fresh_returns_true_for_valid_manual_token(tmp_path):
    store = _store(tmp_path)
    acc = store.add(name="a", token=_jwt(int(time.time()) + 9999))
    sched = RefreshScheduler(account_store=store, profile_root=tmp_path)

    assert asyncio.run(sched.ensure_fresh(acc.id)) is True


def test_forced_refresh_on_manual_account_is_not_silent_noop(tmp_path):
    """Forced refresh (account Refresh button) on a manual account must attempt
    a real CDP capture via _refresh_one, not return early without acting."""
    store = _store(tmp_path)
    acc = store.add(name="a", token=_jwt(int(time.time()) + 9999))
    sched = RefreshScheduler(account_store=store, profile_root=tmp_path)

    called: list[str] = []

    async def _fake_refresh_one(account_id: str) -> bool:
        called.append(account_id)
        return True

    sched._refresh_one = _fake_refresh_one  # type: ignore[assignment]

    result = asyncio.run(sched.ensure_fresh(acc.id, force=True))

    assert called == [acc.id]
    assert result is True
