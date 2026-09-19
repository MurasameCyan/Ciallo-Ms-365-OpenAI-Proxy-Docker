"""RefreshScheduler's unattended consumer re-mint path.

The real gate launches a browser, so every test here injects a fake through
_consumer_gate_factory. What is under test is the scheduler's side of the
contract: which accounts it touches, how it writes the result back, and that a
gate failure degrades to False instead of propagating.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
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



def test_refresh_consumer_persists_only_a_verified_gate_refresh_token(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "new", "domain": ".live.com", "path": "/"}],
            "access_token": "new-token",
            "identity_type": "",
            "account_id": "home:account-a",
            "refresh_token": "captured-refresh-token-" + "x" * 40,
            "refresh_token_client_id": "14638111-3389-403d-b206-a6a71d9f8f16",
            "refresh_token_scope": "140e65af-45d1-4427-bf08-3e7295db6836/ChatAI.ReadWrite",
            "refresh_token_account_id": "home:account-a",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is True
    account = store.get(acct_id)
    assert account.consumer_refresh_token == "captured-refresh-token-" + "x" * 40
    assert account.consumer_refresh_token_client_id == "14638111-3389-403d-b206-a6a71d9f8f16"
    assert account.consumer_refresh_token_scope == "140e65af-45d1-4427-bf08-3e7295db6836/ChatAI.ReadWrite"


def test_refresh_consumer_does_not_store_an_unidentified_gate_refresh_token(tmp_path):
    """An RT without a subject is not evidence that it belongs to this account,
    even when its client and scope look valid."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": [{"name": "WLSSC", "value": "new", "domain": ".live.com", "path": "/"}],
            "access_token": "new-token",
            "identity_type": "",
            "account_id": "home:account-a",
            "refresh_token": "unidentified-refresh-token-" + "x" * 40,
            "refresh_token_client_id": "14638111-3389-403d-b206-a6a71d9f8f16",
            "refresh_token_scope": "140e65af-45d1-4427-bf08-3e7295db6836/ChatAI.ReadWrite",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is True
    assert store.get(acct_id).consumer_refresh_token == ""

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


def test_passive_ensure_fresh_refreshes_a_known_expiring_consumer_token(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    current = store.get(acct_id)
    store.set_consumer_auth(
        acct_id,
        current.cookies,
        current.consumer_token,
        current.consumer_identity_type,
        consumer_account_id=current.consumer_account_id,
        expires_at=time.time() + refresh_scheduler_module._CONSUMER_REFRESH_BEFORE_SECONDS - 1,
    )
    calls = []

    async def refresh(account_id):
        calls.append(account_id)
        return True

    sched = RefreshScheduler(account_store=store, profile_root=tmp_path / "profiles")
    sched.refresh_consumer = refresh

    assert asyncio.run(sched.ensure_fresh(acct_id)) is True
    assert calls == [acct_id]


def test_passive_expiry_refresh_backs_off_after_a_failed_attempt(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    store.get(acct_id).consumer_token_expires_at = time.time() + 60
    calls = []

    async def gate():
        calls.append(acct_id)
        raise RuntimeError("temporary gate failure")

    sched = _sched(store, tmp_path, gate)

    async def run():
        assert await sched.ensure_fresh(acct_id) is True
        assert await sched.ensure_fresh(acct_id) is True
        assert calls == [acct_id]
        # An explicit admin refresh still overrides the passive retry delay.
        assert await sched.ensure_fresh(acct_id, force=True) is True
        assert calls == [acct_id, acct_id]

    asyncio.run(run())


@pytest.mark.parametrize("status", [200, 503])
def test_concurrent_expiry_requests_share_one_refresh_attempt(tmp_path, monkeypatch, status):
    from m365_copilot_openai_proxy import consumer_refresh_via_rt as rt

    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    account = store.get(acct_id)
    store.set_consumer_auth(
        acct_id,
        account.cookies,
        account.consumer_token,
        consumer_account_id="home:account-a.tenant-a",
        expires_at=time.time() + 60,
        consumer_refresh_token="stored-refresh-token-" + "x" * 40,
        consumer_refresh_token_client_id=rt.CONSUMER_CLIENT_ID,
        consumer_refresh_token_scope=rt.CONSUMER_CHATAI_SCOPE,
    )
    http_calls = []
    gate_calls = []

    async def run():
        started = asyncio.Event()
        release = asyncio.Event()

        async def post_token(**kwargs):
            http_calls.append(kwargs)
            started.set()
            await release.wait()
            return httpx.Response(status, json={
                "access_token": "fresh-token",
                "refresh_token": "rotated-refresh-token-" + "x" * 40,
                "expires_in": 3600,
                "client_info": base64.urlsafe_b64encode(json.dumps({
                    "uid": "account-a", "utid": "tenant-a",
                }).encode()).decode(),
                "error": "temporarily_unavailable",
            })

        async def gate():
            gate_calls.append(acct_id)
            raise RuntimeError("temporary gate failure")

        monkeypatch.setattr(rt, "_post_token", post_token)
        sched = _sched(store, tmp_path, gate)
        first = asyncio.create_task(sched.ensure_fresh(acct_id))
        await asyncio.wait_for(started.wait(), timeout=5)
        queued = [asyncio.create_task(sched.ensure_fresh(acct_id)) for _ in range(4)]
        # Let every waiter reach the lock while the first HTTP call is held.
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, *queued), timeout=5)
        assert results == [True] * 5

    asyncio.run(run())

    assert len(http_calls) == 1
    assert len(gate_calls) == (0 if status == 200 else 1)
    reopened = AccountStore(tmp_path / "accounts.json").get(acct_id)
    assert reopened.consumer_token == ("fresh-token" if status == 200 else "old-token")


def test_a_new_push_is_not_coalesced_with_an_older_failed_refresh(tmp_path):
    from m365_copilot_openai_proxy.routes_user import (
        _BACKGROUND_TASKS,
        _spawn_post_push_refresh,
    )

    store = _store(tmp_path)
    acct_id = _consumer_account(store)
    seeds = []

    async def run():
        started = asyncio.Event()
        release = asyncio.Event()
        sched = RefreshScheduler(account_store=store, profile_root=tmp_path / "profiles")

        def factory(account_id):
            seed = store.get(account_id).consumer_token

            async def gate():
                seeds.append(seed)
                if seed == "old-token":
                    started.set()
                    await release.wait()
                return {
                    "access_token": "reminted-" + seed,
                    "account_id": "home:account-a",
                    "cookies": [{"name": "WLSSC", "value": "fresh", "domain": ".live.com", "path": "/"}],
                }

            return gate

        sched._consumer_gate_factory = factory
        first = asyncio.create_task(sched.refresh_consumer(acct_id))
        await asyncio.wait_for(started.wait(), timeout=5)
        store.set_consumer_auth(
            acct_id, store.get(acct_id).cookies, "pushed-token", consumer_account_id="home:account-a"
        )
        previous_tasks = set(_BACKGROUND_TASKS)
        _spawn_post_push_refresh(sched, acct_id, force=True)
        pushed_tasks = set(_BACKGROUND_TASKS) - previous_tasks
        assert len(pushed_tasks) == 1
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, *pushed_tasks), timeout=5)
        assert results[0] is False  # The old result lost the existing CAS race.

    asyncio.run(run())

    assert seeds == ["old-token", "pushed-token"]
    assert store.get(acct_id).consumer_token == "reminted-pushed-token"


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
