"""RefreshScheduler's unattended consumer re-mint path.

The real gate launches a browser, so every test here injects a fake through
_consumer_gate_factory. What is under test is the scheduler's side of the
contract: which accounts it touches, how it writes the result back, and that a
gate failure degrades to False instead of propagating.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.consumer_camoufox import CamoufoxUnavailable
from m365_copilot_openai_proxy.consumer_gate import _pick_cookies
from m365_copilot_openai_proxy import refresh_scheduler as refresh_scheduler_module
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler


def _store(tmp_path) -> AccountStore:
    return AccountStore(persist_path=tmp_path / "accounts.json")


def _consumer_account(store: AccountStore) -> str:
    """An account already bound to consumer Copilot, as a userscript push leaves it."""
    acc = store.add(name="personal", token="")
    store.set_consumer_auth(
        acc.id,
        [
            {
                "name": "__Host-MSAAUTHP",
                "value": "old",
                "domain": ".live.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "None",
            }
        ],
        "old-token",
        "MSA",
        consumer_account_id="home:account-a",
    )
    return acc.id


def _sched(store: AccountStore, tmp_path, gate) -> RefreshScheduler:
    sched = RefreshScheduler(account_store=store, profile_root=tmp_path / "profiles")
    sched._consumer_gate_factory = lambda account_id: gate
    return sched


def test_default_gate_is_seeded_from_the_pushed_account_snapshot(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    scheduler = RefreshScheduler(account_store=store, profile_root=tmp_path / "profiles")

    gate = scheduler._build_consumer_gate(acct_id)

    assert gate._seed_cookies == store.get(acct_id).cookies
    assert gate._previous_token == "old-token"
    assert gate._profile_dir == scheduler._consumer_profile_dir(
        acct_id, "home:account-a"
    )


def test_refresh_consumer_stores_the_reminted_credential(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": [
                {
                    "name": "__Host-MSAAUTHP",
                    "value": "new",
                    "domain": ".live.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "None",
                },
                {
                    "name": "WLSSC",
                    "value": "fresh",
                    "domain": ".live.com",
                    "path": "/",
                },
            ],
            "access_token": "new-token",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is True

    acc = store.get(acct_id)
    assert acc.consumer_token == "new-token"
    assert {c["name"] for c in acc.cookies} == {"__Host-MSAAUTHP", "WLSSC"}
    assert all(cookie.get("domain") == ".live.com" for cookie in acc.cookies)
    assert _pick_cookies(acc.cookies) == {"__Host-MSAAUTHP": "new", "WLSSC": "fresh"}
    assert acc.cookie_valid is True


def test_refresh_consumer_logs_before_waiting_for_the_browser_gate(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    entered = asyncio.Event()
    release = asyncio.Event()
    logs: list[str] = []

    async def gate():
        entered.set()
        await release.wait()
        return {
            "cookies": [
                {"name": "WLSSC", "value": "new", "domain": ".live.com", "path": "/"}
            ],
            "access_token": "new-token",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    monkeypatch.setattr(refresh_scheduler_module, "ulog", logs.append)
    sched = _sched(store, tmp_path, gate)

    async def scenario():
        task = asyncio.create_task(sched.refresh_consumer(acct_id))
        await entered.wait()
        assert any("Consumer refresh requested" in line for line in logs)
        release.set()
        assert await task is True

    asyncio.run(scenario())


def test_refresh_consumer_keeps_the_known_identity_type(tmp_path):
    """MSAL mints the token without an X-UserIdentityType, so the gate returns
    "". That must not erase a value the userscript already captured."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "x", "domain": ".live.com", "path": "/"}],
            "access_token": "new",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is True
    assert store.get(acct_id).consumer_identity_type == "MSA"


def test_refresh_consumer_is_false_when_camoufox_is_absent(tmp_path):
    """Camoufox is an optional dependency; without it the caller falls back to a
    userscript re-push rather than seeing an exception."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        raise CamoufoxUnavailable("not installed")

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    # The stored credential is untouched: it may well still work.
    assert store.get(acct_id).consumer_token == "old-token"


def test_refresh_consumer_swallows_a_browser_failure(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        raise RuntimeError("launch timed out")

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    assert store.get(acct_id).consumer_token == "old-token"


def test_refresh_consumer_rejects_an_empty_token(tmp_path):
    """A lapsed MSA session yields no token; that is a failure, not a write."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "x", "domain": ".live.com", "path": "/"}],
            "access_token": "",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    assert store.get(acct_id).consumer_token == "old-token"


def test_refresh_consumer_ignores_m365_accounts(tmp_path):
    """Guards the reverse direction of ensure_fresh's provider split: an M365
    account must never be pushed through the consumer browser."""
    store = _store(tmp_path)
    acc = store.add(name="work", token="jwt")
    calls = []

    async def gate():
        calls.append(1)
        return {"cookies": {}, "access_token": "x", "identity_type": ""}

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acc.id)) is False
    assert calls == []


def test_refresh_consumer_records_the_attempt_for_backoff(tmp_path):
    """Even a failed attempt must arm the backoff, or a dead session relaunches
    a browser on every keepalive tick."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        raise RuntimeError("nope")

    sched = _sched(store, tmp_path, gate)
    asyncio.run(sched.refresh_consumer(acct_id))
    assert sched._consumer_attempted_at[acct_id] >= time.time() - 5


def test_forced_ensure_fresh_remints_a_consumer_account(tmp_path):
    """The admin Refresh button and keepalive both arrive through ensure_fresh."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "x", "domain": ".live.com", "path": "/"}],
            "access_token": "forced",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.ensure_fresh(acct_id, force=True)) is True
    assert store.get(acct_id).consumer_token == "forced"


def test_passive_ensure_fresh_does_not_launch_a_browser(tmp_path):
    """A /v1 request must not pay a ~7s launch on a token we have no reason to
    believe is dead; expiry surfaces upstream as ClearanceRequired instead."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    calls = []

    async def gate():
        calls.append(1)
        return {"cookies": {}, "access_token": "x", "identity_type": ""}

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.ensure_fresh(acct_id)) is True
    assert calls == []


def test_forced_ensure_fresh_still_reports_true_on_a_failed_remint(tmp_path):
    """A failed re-mint is a missed opportunity, not a dead account: the stored
    credential is still there to try."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        raise RuntimeError("nope")

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.ensure_fresh(acct_id, force=True)) is True


def test_refresh_consumer_rejects_the_previous_token(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    captured_at = store.get(acct_id).consumer_updated_at

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "x", "domain": ".live.com", "path": "/"}],
            "access_token": "old-token",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    account = store.get(acct_id)
    assert account.consumer_token == "old-token"
    assert account.consumer_updated_at == captured_at


def test_refresh_consumer_rejects_cookies_without_replay_metadata(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "x"}],
            "access_token": "new-token",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    assert _pick_cookies(store.get(acct_id).cookies) == {"__Host-MSAAUTHP": "old"}


def test_refresh_consumer_rejects_a_different_microsoft_subject(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    store.get(acct_id).consumer_account_id = "home:account-a"

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "b", "domain": ".live.com", "path": "/"}],
            "access_token": "token-b",
            "identity_type": "",
            "account_id": "home:account-b",
        }

    sched = _sched(store, tmp_path, gate)
    profile = sched._consumer_profile_dir(acct_id, "home:account-a")
    profile.mkdir(parents=True)
    (profile / "cookies.sqlite").write_text("wrong account")
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    assert store.get(acct_id).consumer_token == "old-token"
    assert not profile.exists()


def test_refresh_consumer_rejects_an_unidentified_mint_for_a_pinned_account(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    store.get(acct_id).consumer_account_id = "home:account-a"

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "a", "domain": ".live.com", "path": "/"}],
            "access_token": "new-token",
            "identity_type": "",
            "account_id": "",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    assert store.get(acct_id).consumer_token == "old-token"


def test_refresh_consumer_discards_a_result_after_a_new_push(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    account = store.get(acct_id)
    account.consumer_account_id = "home:account-a"

    async def gate():
        store.set_consumer_auth(
            acct_id,
            [{"name": "WLSSC", "value": "b", "domain": ".live.com", "path": "/"}],
            "token-b",
            "MSA",
            "b@example.com",
        )
        store.get(acct_id).consumer_account_id = "home:account-b"
        return {
            "cookies": [{"name": "WLSSC", "value": "a2", "domain": ".live.com", "path": "/"}],
            "access_token": "token-a-new",
            "identity_type": "",
            "account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is False
    current = store.get(acct_id)
    assert current.consumer_account_id == "home:account-b"
    assert current.consumer_token == "token-b"
    assert _pick_cookies(current.cookies) == {"WLSSC": "b"}
    assert current.email == "b@example.com"


def test_remove_account_rechecks_the_unbound_predicate_after_waiting_for_lock(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    sched = RefreshScheduler(store, tmp_path / "profiles")

    async def scenario():
        lock = sched._account_lock(acct_id)
        await lock.acquire()
        unbound = True
        task = asyncio.create_task(
            sched.remove_account(acct_id, can_remove=lambda: unbound)
        )
        await asyncio.sleep(0)
        unbound = False
        lock.release()
        return await task

    assert asyncio.run(scenario()) is False
    assert store.get(acct_id) is not None


def test_remove_account_keeps_the_record_when_profile_cleanup_fails(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    sched = RefreshScheduler(store, tmp_path / "profiles")

    def fail_cleanup(_account_id):
        raise OSError("profile is busy")

    monkeypatch.setattr(sched, "_clear_consumer_profiles", fail_cleanup)

    with pytest.raises(OSError, match="profile is busy"):
        asyncio.run(sched.remove_account(acct_id))
    assert store.get(acct_id) is not None


def test_clear_credentials_retries_stale_profile_cleanup_after_provider_reset(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    sched = RefreshScheduler(store, tmp_path / "profiles")
    profile = sched._consumer_profile_dir(acct_id, "home:account-a")
    profile.mkdir(parents=True)
    (profile / "session-state").write_text("secret", encoding="utf-8")
    store.clear_credentials(acct_id)
    assert store.get(acct_id).provider == "m365"

    assert asyncio.run(sched.clear_account_credentials(acct_id)) is True
    assert not profile.exists()
