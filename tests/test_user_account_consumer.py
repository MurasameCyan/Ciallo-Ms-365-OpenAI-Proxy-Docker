from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


class ExplodingRefreshScheduler:
    """A consumer push must stay out of the M365 machinery, so inject_cookies
    blows up if it is ever reached. ensure_fresh only records: it is the shared
    entry point that dispatches a consumer account to its own Camoufox gate
    instead of the substrate paths, which is what the post-push re-mint wants."""

    def __init__(self):
        self.ensure_fresh_calls: list[tuple[str, bool]] = []

    async def inject_cookies(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        raise AssertionError("consumer push must not inject cookies into Chromium")

    async def ensure_fresh(self, account_id: str, force: bool = False) -> bool:
        self.ensure_fresh_calls.append((account_id, force))
        return True


def make_test_app(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    app.state.refresh_scheduler = ExplodingRefreshScheduler()
    return app


def make_real_app(tmp_path):
    """A real app+scheduler whose consumer gate never launches a browser.

    A consumer push queues a Camoufox re-mint, which tests can neither run nor
    wait for. Stubbing the scheduler's own gate factory is enough to keep the
    browser out while leaving the rest of the scheduler (profile dirs, locking,
    persistence) real, which is why these tests build the real app at all.
    """
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    async def _no_browser():
        raise RuntimeError("no browser under test")

    app.state.refresh_scheduler._consumer_gate_factory = lambda account_id: _no_browser
    return app


TOKEN = "consumer-chatai-token-" + "x" * 30
COOKIES = [{"name": "_C_Auth", "value": "abc", "domain": ".copilot.microsoft.com"}]


def test_consumer_push_creates_account_flips_provider_and_binds_key(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "username": "Personal User",
            "cookies": COOKIES,
            "access_token": TOKEN,
            "identity_type": "MSA",
            "consumer_account_id": "HOME:Personal.Account-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "consumer", "cookies": 1}
    updated_key = app.state.key_store.get(key.id)
    account = app.state.account_store.get(updated_key.account_id)
    assert account.provider == "consumer"
    assert account.consumer_token == TOKEN
    assert account.consumer_identity_type == "MSA"
    assert account.consumer_account_id == "home:personal.account-1"
    assert account.cookies == COOKIES
    assert account.cookie_valid is True
    assert account.name == "Personal User"


def test_consumer_push_normalizes_and_stores_email_without_changing_response(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "identity_type": "MSA",
            "email": "  Person.Account@Example.COM  ",
            "consumer_account_id": "home:account-a",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "consumer", "cookies": 1}
    account_id = app.state.key_store.get(key.id).account_id
    assert app.state.account_store.get(account_id).email == "person.account@example.com"


def test_consumer_push_replaces_a_stale_name_with_valid_email_when_name_is_blank(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="deng")
    key = app.state.key_store.add(name="Proxy User", account_id=account.id)

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "username": "",
            "email": "ouyouakira@hotmail.com",
            "cookies": COOKIES,
            "access_token": TOKEN,
            "consumer_account_id": "home:account-a",
        },
    )

    assert response.status_code == 200
    updated = app.state.account_store.get(account.id)
    assert updated.email == "ouyouakira@hotmail.com"
    assert updated.name == "ouyouakira@hotmail.com"


def test_consumer_push_blank_email_does_not_overwrite_stored_email(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Personal User")
    account.email = "kept@example.com"
    key = app.state.key_store.add(
        name="Proxy User",
        account_id=account.id,
        username="proxyuser",
        password="password1",
    )

    client = TestClient(app)
    first_response = client.post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "email": "replacement@example.com",
            "consumer_account_id": "home:account-a",
        },
    )
    assert first_response.status_code == 200

    response = client.post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "email": "   ",
            "consumer_account_id": "home:account-a",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "consumer", "cookies": 1}
    assert app.state.account_store.get(account.id).email == "replacement@example.com"


def test_consumer_push_invalid_email_does_not_overwrite_stored_email(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Personal User")
    app.state.account_store.set_consumer_auth(
        account.id,
        COOKIES,
        TOKEN + "-old",
        "MSA",
        email="kept@example.com",
        consumer_account_id="home:account-a",
    )
    key = app.state.key_store.add(name="Proxy User", account_id=account.id)

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "email": "not an email",
            "consumer_account_id": "home:account-a",
        },
    )

    assert response.status_code == 200
    assert app.state.account_store.get(account.id).email == "kept@example.com"


def test_consumer_subject_change_requires_explicit_logout(tmp_path):
    app = make_real_app(tmp_path)
    account = app.state.account_store.add(name="Personal User")
    key = app.state.key_store.add(name="Proxy User", account_id=account.id)
    client = TestClient(app)

    first = client.post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "email": "a@example.com",
            "consumer_account_id": "home:account-a",
        },
    )
    second = client.post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN + "-b",
            "consumer_account_id": "home:account-b",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 409
    current = app.state.account_store.get(account.id)
    assert current.consumer_account_id == "home:account-a"
    assert current.email == "a@example.com"

    logout = client.post(
        "/user/account/logout",
        headers={"Authorization": f"Bearer {key.key}"},
    )
    switched = client.post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN + "-b",
            "consumer_account_id": "home:account-b",
        },
    )

    assert logout.status_code == 200
    assert switched.status_code == 200
    current = app.state.account_store.get(account.id)
    assert current.consumer_account_id == "home:account-b"
    assert current.email == ""


def test_consumer_push_clears_a_stale_m365_cookie_expiry(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Converted Work Account")
    account.cookie_expires_at = 123.0
    key = app.state.key_store.add(name="Proxy User", account_id=account.id)

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "consumer_account_id": "home:account-a",
        },
    )

    assert response.status_code == 200
    converted = app.state.account_store.get(account.id)
    assert converted.provider == "consumer"
    assert converted.cookie_expires_at == 0.0


def test_consumer_logout_fully_signs_out_a_consumer_account(tmp_path):
    """logout promises to wipe credential state, but a consumer account is not
    signed out until provider/consumer_token are cleared too: leaving them makes
    request dispatch keep streaming through the consumer client on stale cookies
    while binding_state reads 'none'. After logout the account must look like a
    blank m365 account -- no consumer routing, no stored token."""
    app = make_real_app(tmp_path)
    client = TestClient(app)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    push = client.post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "identity_type": "MSA",
            "consumer_account_id": "home:account-a",
        },
    )
    assert push.status_code == 200
    account_id = app.state.key_store.get(key.id).account_id
    assert app.state.account_store.get(account_id).provider == "consumer"
    current_profile = app.state.refresh_scheduler._consumer_profile_dir(
        account_id, "home:account-a"
    )
    legacy_profile = tmp_path / "profiles" / f"{account_id}-consumer"
    for profile in (current_profile, legacy_profile):
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "session-state").write_text("secret", encoding="utf-8")

    logout = client.post(
        "/user/account/logout",
        headers={"Authorization": f"Bearer {key.key}"},
    )
    assert logout.status_code == 200

    account = app.state.account_store.get(account_id)
    assert account.provider == "m365"
    assert account.consumer_token == ""
    assert account.consumer_identity_type == ""
    assert account.cookies == []
    assert account.cookie_valid is False
    assert account.token_status()["valid"] is False
    assert not current_profile.exists()
    assert not legacy_profile.exists()


def test_consumer_unbind_removes_persisted_browser_profiles(tmp_path):
    app = make_real_app(tmp_path)
    client = TestClient(app)
    key = app.state.key_store.add(name="Proxy User")
    push = client.post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "consumer_account_id": "home:account-a",
        },
    )
    assert push.status_code == 200
    account_id = app.state.key_store.get(key.id).account_id
    profile = app.state.refresh_scheduler._consumer_profile_dir(
        account_id, "home:account-a"
    )
    profile.mkdir(parents=True)
    (profile / "session-state").write_text("secret", encoding="utf-8")

    response = client.post(
        "/user/account/unbind",
        headers={"Authorization": f"Bearer {key.key}"},
    )

    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert app.state.account_store.get(account_id) is None
    assert not profile.exists()


def test_consumer_push_rejects_short_token(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"cookies": COOKIES, "access_token": "short"},
    )

    assert response.status_code == 400
    assert "token" in response.json()["error"]["message"].lower()


def test_consumer_push_rejects_empty_cookie_list(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"cookies": [], "access_token": TOKEN},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "No cookies provided"


def test_consumer_push_rejects_a_token_without_a_pinned_microsoft_subject(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"cookies": COOKIES, "access_token": TOKEN},
    )

    assert response.status_code == 400
    assert "identity" in response.json()["error"]["message"].lower()


def test_consumer_push_queues_a_forced_remint(tmp_path, monkeypatch):
    """A push alone can land an account that is authenticated yet unusable.

    The pushed cf_clearance is minted against the user's own browser fingerprint,
    which the Firefox-impersonating consumer transport cannot reuse, so the very
    first turn can still die on Cloudflare's challenge. Queue the Camoufox re-mint
    with the push instead of leaving the account broken until keepalive notices an
    hour later. force=True because ensure_fresh only re-mints a consumer
    credential when forced. Asserted on the spawn helper: the endpoint fires it
    detached, so the HTTP-layer timing is not deterministic under TestClient.
    """
    from m365_copilot_openai_proxy import routes_user

    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")
    spawned = []

    def _record(scheduler, account_id, *, force=False):
        # The gate seeds from the stored credential, so the re-mint has to be
        # queued after the push is persisted -- never before.
        stored = app.state.account_store.get(account_id)
        spawned.append((account_id, force, stored.consumer_token))

    monkeypatch.setattr(routes_user, "_spawn_post_push_refresh", _record)

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "cookies": COOKIES,
            "access_token": TOKEN,
            "identity_type": "MSA",
            "consumer_account_id": "home:account-a",
        },
    )

    assert response.status_code == 200
    account_id = app.state.key_store.get(key.id).account_id
    assert spawned == [(account_id, True, TOKEN)]


def test_rejected_consumer_push_queues_no_remint(tmp_path, monkeypatch):
    """A push that stored nothing leaves the gate nothing to seed from."""
    from m365_copilot_openai_proxy import routes_user

    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")
    spawned = []
    monkeypatch.setattr(
        routes_user,
        "_spawn_post_push_refresh",
        lambda *args, **kwargs: spawned.append(args),
    )

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"cookies": COOKIES, "access_token": "too-short"},
    )

    assert response.status_code == 400
    assert spawned == []


def test_post_push_refresh_forwards_force_to_the_shared_refresh_entry_point(tmp_path):
    """ensure_fresh is the one entry point that routes a consumer account to its
    Camoufox gate, and it re-mints only when forced -- a force that silently got
    dropped here would make the post-push re-mint a no-op."""
    from m365_copilot_openai_proxy import routes_user

    app = make_test_app(tmp_path)
    scheduler = app.state.refresh_scheduler

    async def _drive() -> None:
        routes_user._spawn_post_push_refresh(scheduler, "acc-1", force=True)
        # Let the detached task run to completion within this loop.
        await asyncio.sleep(0)
        pending = list(routes_user._BACKGROUND_TASKS)
        if pending:
            await asyncio.gather(*pending)

    asyncio.run(_drive())

    assert scheduler.ensure_fresh_calls == [("acc-1", True)]


def test_consumer_account_excluded_from_refresh_scheduler(tmp_path):
    """A forced consumer refresh may try its own gate, but must never enter the
    M365 machinery; if that opportunity fails, usability still follows the
    credential already stored."""
    from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler

    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    store = app.state.account_store
    account = store.add(name="Personal User")
    store.set_consumer_auth(
        account.id,
        COOKIES,
        TOKEN,
        "MSA",
        consumer_account_id="home:account-a",
    )

    calls = []

    async def failed_consumer_gate():
        calls.append(account.id)
        raise RuntimeError("browser unavailable")

    scheduler = RefreshScheduler(store, tmp_path)
    scheduler._consumer_gate_factory = lambda account_id: failed_consumer_gate
    assert asyncio.run(scheduler.ensure_fresh(account.id, force=True)) is True

    # A consumer account with no token is unusable, still without touching M365.
    store.set_consumer_auth(
        account.id,
        COOKIES,
        "",
        "",
        consumer_account_id="home:account-a",
    )
    assert asyncio.run(scheduler.ensure_fresh(account.id, force=True)) is False
    assert calls == [account.id, account.id]


def test_consumer_provider_surfaces_in_public_serializer_without_leaking_token(tmp_path):
    from m365_copilot_openai_proxy.account_serializers import user_account_public

    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    store = app.state.account_store
    account = store.add(name="Personal User")
    store.set_consumer_auth(
        account.id,
        COOKIES,
        TOKEN,
        "MSA",
        consumer_account_id="home:account-a",
    )

    public = user_account_public(store.get(account.id))
    assert public["provider"] == "consumer"
    assert public["has_consumer_token"] is True
    assert TOKEN not in str(public)


def test_consumer_token_is_encrypted_at_rest_and_survives_reload(tmp_path):
    """The ChatAI token is a live credential, so it must be in SENSITIVE_FIELDS:
    absent from the plaintext of accounts.json, yet identical after a reload."""
    from m365_copilot_openai_proxy.account_store import AccountStore

    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    account = store.add(name="Personal User")
    store.set_consumer_auth(
        account.id,
        COOKIES,
        TOKEN,
        "MSA",
        consumer_account_id="home:account-a",
    )

    on_disk = persist.read_text(encoding="utf-8")
    # Only meaningful when cryptography is installed; degrade like account_crypto.
    from m365_copilot_openai_proxy.account_crypto import _HAVE_CRYPTO

    if _HAVE_CRYPTO:
        assert TOKEN not in on_disk
        assert "home:account-a" not in on_disk

    reloaded = AccountStore(persist_path=persist).get(account.id)
    assert reloaded.provider == "consumer"
    assert reloaded.consumer_token == TOKEN
    assert reloaded.consumer_identity_type == "MSA"
    assert reloaded.consumer_account_id == "home:account-a"
