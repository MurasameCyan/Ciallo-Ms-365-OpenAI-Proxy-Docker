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
