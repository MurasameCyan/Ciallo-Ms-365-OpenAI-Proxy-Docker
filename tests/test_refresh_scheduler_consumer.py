"""RefreshScheduler's unattended consumer re-mint path.

The real gate launches a browser, so every test here injects a fake through
_consumer_gate_factory. What is under test is the scheduler's side of the
contract: which accounts it touches, how it writes the result back, and that a
gate failure degrades to False instead of propagating.
"""

from __future__ import annotations

import asyncio
import time

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.consumer_camoufox import CamoufoxUnavailable
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler


def _store(tmp_path) -> AccountStore:
    return AccountStore(persist_path=tmp_path / "accounts.json")


def _consumer_account(store: AccountStore) -> str:
    """An account already bound to consumer Copilot, as a userscript push leaves it."""
    acc = store.add(name="personal", token="")
    store.set_consumer_auth(
        acc.id,
        [{"name": "__Host-MSAAUTHP", "value": "old"}],
        "old-token",
        "MSA",
    )
    return acc.id


def _sched(store: AccountStore, tmp_path, gate) -> RefreshScheduler:
    sched = RefreshScheduler(account_store=store, profile_root=tmp_path / "profiles")
    sched._consumer_gate_factory = lambda account_id: gate
    return sched


def test_refresh_consumer_stores_the_reminted_credential(tmp_path):
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {
            "cookies": {"__Host-MSAAUTHP": "new", "WLSSC": "fresh"},
            "access_token": "new-token",
            "identity_type": "",
        }

    sched = _sched(store, tmp_path, gate)
    assert asyncio.run(sched.refresh_consumer(acct_id)) is True

    acc = store.get(acct_id)
    assert acc.consumer_token == "new-token"
    # The gate hands back a name->value mapping; the store wants the userscript's
    # list-of-dicts shape.
    assert {c["name"] for c in acc.cookies} == {"__Host-MSAAUTHP", "WLSSC"}
    assert acc.cookie_valid is True


def test_refresh_consumer_keeps_the_known_identity_type(tmp_path):
    """MSAL mints the token without an X-UserIdentityType, so the gate returns
    "". That must not erase a value the userscript already captured."""
    store = _store(tmp_path)
    acct_id = _consumer_account(store)

    async def gate():
        return {"cookies": {"WLSSC": "x"}, "access_token": "new", "identity_type": ""}

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
        return {"cookies": {"WLSSC": "x"}, "access_token": "", "identity_type": ""}

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
        return {"cookies": {"WLSSC": "x"}, "access_token": "forced", "identity_type": ""}

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
