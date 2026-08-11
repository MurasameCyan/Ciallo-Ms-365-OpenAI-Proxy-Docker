"""The mid-request consumer re-mint attached by create_api_dependencies.

ConsumerCopilotClient calls this gate once per turn, on a ClearanceRequired
raised before any output. What matters is that it routes through the scheduler
(so the result is persisted and the browser lock is respected) and that every
failure mode collapses to one actionable ClearanceRequired.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from m365_copilot_openai_proxy.consumer_client import ClearanceRequired
from m365_copilot_openai_proxy.dependencies import _consumer_gate_for, create_api_dependencies


def _app(*, scheduler=None, account=None) -> FastAPI:
    app = FastAPI()
    if scheduler is not None:
        app.state.refresh_scheduler = scheduler
    app.state.account_store = SimpleNamespace(get=lambda _id: account)
    return app


def _scheduler(result):
    calls: list[str] = []

    async def refresh_consumer(account_id: str) -> bool:
        calls.append(account_id)
        if isinstance(result, Exception):
            raise result
        return result

    return SimpleNamespace(refresh_consumer=refresh_consumer, calls=calls)


def test_gate_returns_the_persisted_credential_after_a_successful_remint():
    """The gate reads back from the store rather than trusting the browser's
    return value, so the client and the store cannot drift apart."""
    account = SimpleNamespace(
        cookies=[{"name": "_C_Auth", "value": "new", "domain": ".copilot.microsoft.com"}],
        consumer_token="reminted",
        consumer_identity_type="MSA",
    )
    sched = _scheduler(True)
    gate = _consumer_gate_for(_app(scheduler=sched, account=account), "acct-1")

    auth = asyncio.run(gate())

    assert sched.calls == ["acct-1"]
    assert auth == {
        "cookies": {"_C_Auth": "new"},
        "access_token": "reminted",
        "identity_type": "MSA",
    }


def test_gate_preserves_the_identity_type_the_userscript_captured():
    """MSAL mints no X-UserIdentityType, so the value can only come from the
    store; a gate reading the browser directly would blank it."""
    account = SimpleNamespace(cookies=[], consumer_token="t", consumer_identity_type="MSA")
    gate = _consumer_gate_for(_app(scheduler=_scheduler(True), account=account), "a")
    assert asyncio.run(gate())["identity_type"] == "MSA"


def test_gate_raises_clearance_required_when_the_remint_fails():
    """Browser absent, launch broken, MSA session lapsed -- all one human step."""
    gate = _consumer_gate_for(_app(scheduler=_scheduler(False)), "a")
    with pytest.raises(ClearanceRequired, match="userscript"):
        asyncio.run(gate())


def test_gate_raises_clearance_required_when_the_account_vanished():
    gate = _consumer_gate_for(_app(scheduler=_scheduler(True), account=None), "a")
    with pytest.raises(ClearanceRequired, match="disappeared"):
        asyncio.run(gate())


def test_no_gate_without_a_scheduler():
    """Leaving the gate unset keeps the client's original error intact."""
    assert _consumer_gate_for(_app(), "a") is None


def test_gate_does_not_run_at_dependency_resolution_time():
    """Building the gate must not launch anything: it is a closure, and a /v1
    request that never fails must never pay for a browser."""
    sched = _scheduler(True)
    _consumer_gate_for(_app(scheduler=sched, account=None), "a")
    assert sched.calls == []


def _consumer_request(account):
    """A request shaped the way the /v1 auth middleware leaves it."""
    return SimpleNamespace(state=SimpleNamespace(api_key_obj=None, account=account))


def _consumer_account(**overrides):
    account = SimpleNamespace(
        id="acct-1",
        provider="consumer",
        token="",
        cookies=[{"name": "_U", "value": "v", "domain": ".copilot.microsoft.com"}],
        consumer_token="tok",
        consumer_identity_type="MSA",
        proxy_url="",
    )
    for key, value in overrides.items():
        setattr(account, key, value)
    return account


def _capturing_app(account) -> FastAPI:
    """An app whose consumer_client_factory records the kwargs it was handed."""
    app = _app(scheduler=_scheduler(True), account=account)
    app.state.tool_prompt = ""
    app.state.ws_idle_timeout_minutes = 0
    app.state.seen = {}
    app.state.consumer_client_factory = lambda **kwargs: (
        app.state.seen.update(kwargs) or SimpleNamespace(chat_stream=None)
    )
    return app


def test_consumer_client_receives_the_account_proxy():
    """The consumer client must ride the account's own egress, not just the
    process-global proxy env: that split is the whole point of the field."""
    app = _capturing_app(_consumer_account(proxy_url="socks5h://127.0.0.1:1080"))
    _get_settings, get_client = create_api_dependencies(app)

    get_client(_consumer_request(app.state.account_store.get("acct-1")))

    assert app.state.seen["proxy"] == "socks5h://127.0.0.1:1080"


def test_consumer_client_proxy_is_none_when_the_account_has_none():
    """None, not "": the client falls through to curl_cffi's own env handling,
    which is what preserves today's behaviour for accounts that never opted in."""
    app = _capturing_app(_consumer_account())
    _get_settings, get_client = create_api_dependencies(app)

    get_client(_consumer_request(app.state.account_store.get("acct-1")))

    assert app.state.seen["proxy"] is None
