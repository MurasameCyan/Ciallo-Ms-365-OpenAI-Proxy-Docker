from __future__ import annotations

import time

from m365_copilot_openai_proxy import refresh_scheduler as rs
from m365_copilot_openai_proxy.account_store import Account
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler


def _make_scheduler(tmp_path) -> RefreshScheduler:
    # account_store is only used via .list() in the paths under test; a scheduler
    # with no store attached is fine for _keepalive_due unit checks.
    return RefreshScheduler(account_store=None, profile_root=tmp_path)


def _acct(**kw) -> Account:
    base = dict(token_source="cdp", cookie_valid=True, cookie_expires_at=time.time() + 10_000)
    base.update(kw)
    return Account(**base)


def test_keepalive_due_when_cookie_near_expiry(tmp_path):
    sched = _make_scheduler(tmp_path)
    # Cookie expires within the keepalive window -> due.
    acct = _acct(cookie_expires_at=time.time() + rs._COOKIE_KEEPALIVE_BEFORE_SECONDS - 60)
    assert sched._keepalive_due(acct) is True


def test_not_due_when_cookie_far_from_expiry(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(cookie_expires_at=time.time() + rs._COOKIE_KEEPALIVE_BEFORE_SECONDS + 3600)
    assert sched._keepalive_due(acct) is False


def test_not_due_for_non_cdp_account(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(token_source="push", cookie_expires_at=time.time() + 60)
    assert sched._keepalive_due(acct) is False


def test_not_due_when_cookie_invalid(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(cookie_valid=False, cookie_expires_at=time.time() + 60)
    assert sched._keepalive_due(acct) is False


def test_not_due_when_expiry_unset(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(cookie_expires_at=0.0)
    assert sched._keepalive_due(acct) is False


# --------------------------------------------------------- _recovery_due (self-heal)

def test_recovery_due_for_stuck_cdp_account_with_stored_cookies(tmp_path):
    """A cdp account marked cookie_valid=False but still holding cookies should
    be eligible for self-heal re-injection (the death-spiral fix)."""
    sched = _make_scheduler(tmp_path)
    acct = _acct(cookie_valid=False, cookies=[{"name": "ESTSAUTH", "value": "x"}])
    assert sched._recovery_due(acct) is True


def test_recovery_not_due_when_cookie_still_valid(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(cookie_valid=True, cookies=[{"name": "ESTSAUTH", "value": "x"}])
    assert sched._recovery_due(acct) is False


def test_recovery_not_due_without_stored_cookies(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(cookie_valid=False, cookies=[])
    assert sched._recovery_due(acct) is False


def test_recovery_not_due_for_manual_account(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(token_source="manual", cookie_valid=False, cookies=[{"name": "ESTSAUTH", "value": "x"}])
    assert sched._recovery_due(acct) is False


def test_recovery_backoff_blocks_immediate_retry(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _acct(cookie_valid=False, cookies=[{"name": "ESTSAUTH", "value": "x"}])
    sched._recovery_attempted_at[acct.id] = time.time()
    assert sched._recovery_due(acct) is False


# ------------------------------------------- _consumer_keepalive_due (Camoufox re-mint)

def _consumer(**kw) -> Account:
    """A consumer account whose credential was captured `age` seconds ago."""
    age = kw.pop("age", 0.0)
    base = dict(
        provider="consumer",
        consumer_token="tok",
        consumer_updated_at=time.time() - age,
    )
    base.update(kw)
    return _acct(**base)


def test_consumer_keepalive_due_once_the_credential_is_stale(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _consumer(age=rs._CONSUMER_KEEPALIVE_AGE_SECONDS + 60)
    assert sched._consumer_keepalive_due(acct) is True


def test_consumer_keepalive_not_due_while_the_credential_is_fresh(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _consumer(age=60)
    assert sched._consumer_keepalive_due(acct) is False


def test_consumer_keepalive_skips_m365_accounts(tmp_path):
    """The age predicate must not touch M365 accounts, which have a real exp."""
    sched = _make_scheduler(tmp_path)
    acct = _acct(provider="m365", consumer_token="tok", consumer_updated_at=0.0)
    assert sched._consumer_keepalive_due(acct) is False


def test_consumer_keepalive_not_due_without_a_captured_credential(tmp_path):
    """No token means no MSA session to renew from -- the first push must be human."""
    sched = _make_scheduler(tmp_path)
    acct = _consumer(consumer_token="", age=99_999)
    assert sched._consumer_keepalive_due(acct) is False


def test_consumer_keepalive_backoff_blocks_immediate_retry(tmp_path):
    sched = _make_scheduler(tmp_path)
    acct = _consumer(age=rs._CONSUMER_KEEPALIVE_AGE_SECONDS + 60)
    sched._consumer_attempted_at[acct.id] = time.time()
    assert sched._consumer_keepalive_due(acct) is False


def test_consumer_profile_dir_is_separate_from_the_chromium_one(tmp_path):
    """A Firefox profile and a Chromium profile cannot share a directory."""
    sched = _make_scheduler(tmp_path)
    assert sched._consumer_profile_dir("acct1") == tmp_path / "acct1-consumer"
