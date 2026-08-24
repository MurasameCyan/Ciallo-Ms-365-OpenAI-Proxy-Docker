"""The per-account turn ceiling: that it serialises, that it queues instead of
rejecting, and that the wrapper it rides on stays invisible to the routes.

The transparency tests are not ceremony -- the /v1 routes assign
``client.mode``/``client._tone`` on the way in, so a wrapper that swallowed
attribute writes would silently send every turn with the wrong model.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.account_concurrency import AccountConcurrency, ThrottledClient
from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.dependencies import create_api_dependencies
from m365_copilot_openai_proxy.runtime_settings import _RUNTIME_SETTINGS_DEFAULTS


class _Client:
    """A turn that blocks until the test lets it finish."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.release = asyncio.Event()
        self.mode = ""

    async def chat(self, prompt):
        self.started.append(prompt)
        await self.release.wait()
        return f"answer:{prompt}"

    async def chat_stream(self, prompt):
        self.started.append(prompt)
        yield "a"
        await self.release.wait()
        yield "b"


def _wrap(gate: AccountConcurrency, client, account_id="acct", limit=1):
    return ThrottledClient(client, lambda: gate.hold(account_id, limit))


def test_a_second_turn_on_one_account_waits_for_the_first(tmp_path):
    async def _run():
        gate = AccountConcurrency()
        client = _Client()
        wrapped = _wrap(gate, client, limit=1)

        first = asyncio.create_task(wrapped.chat("one"))
        await asyncio.sleep(0.02)
        second = asyncio.create_task(wrapped.chat("two"))
        await asyncio.sleep(0.02)

        # Queued, not rejected: the second turn exists and is waiting.
        assert client.started == ["one"]
        assert gate.stats() == {"acct": {"inflight": 1, "waiting": 1}}

        client.release.set()
        assert await asyncio.gather(first, second) == ["answer:one", "answer:two"]
        assert client.started == ["one", "two"]
        assert gate.stats() == {}

    asyncio.run(_run())


def test_zero_lifts_the_ceiling(tmp_path):
    async def _run():
        gate = AccountConcurrency()
        client = _Client()
        wrapped = _wrap(gate, client, limit=0)

        turns = [asyncio.create_task(wrapped.chat(name)) for name in ("one", "two", "three")]
        await asyncio.sleep(0.02)

        assert client.started == ["one", "two", "three"]
        assert gate.stats() == {"acct": {"inflight": 3, "waiting": 0}}
        client.release.set()
        await asyncio.gather(*turns)

    asyncio.run(_run())


def test_one_busy_account_does_not_hold_up_another(tmp_path):
    async def _run():
        gate = AccountConcurrency()
        first_client, second_client = _Client(), _Client()
        busy = _wrap(gate, first_client, account_id="acct_a", limit=1)
        other = _wrap(gate, second_client, account_id="acct_b", limit=1)

        turns = [asyncio.create_task(busy.chat("a1")), asyncio.create_task(busy.chat("a2"))]
        turns.append(asyncio.create_task(other.chat("b1")))
        await asyncio.sleep(0.02)

        assert first_client.started == ["a1"]
        assert second_client.started == ["b1"]  # its own gate, its own slot

        first_client.release.set()
        second_client.release.set()
        await asyncio.gather(*turns)

    asyncio.run(_run())


def test_a_stream_holds_the_slot_until_its_last_delta(tmp_path):
    async def _run():
        gate = AccountConcurrency()
        client = _Client()
        wrapped = _wrap(gate, client, limit=1)

        stream = wrapped.chat_stream("one")
        assert await stream.__anext__() == "a"
        queued = asyncio.create_task(wrapped.chat("two"))
        await asyncio.sleep(0.02)

        # The upstream WebSocket is still open, so the slot is still taken.
        assert client.started == ["one"]

        client.release.set()
        assert [delta async for delta in stream] == ["b"]
        assert await queued == "answer:two"

    asyncio.run(_run())


def test_a_failed_turn_gives_its_slot_back(tmp_path):
    async def _run():
        gate = AccountConcurrency()

        class _Boom:
            async def chat(self, prompt):
                raise RuntimeError("upstream refused")

        wrapped = _wrap(gate, _Boom(), limit=1)

        with pytest.raises(RuntimeError):
            await wrapped.chat("one")
        assert gate.stats() == {}
        # A leaked slot would deadlock this second turn instead of raising.
        with pytest.raises(RuntimeError):
            await wrapped.chat("two")

    asyncio.run(_run())


def test_raising_the_cap_mid_flight_neither_deadlocks_nor_loses_count(tmp_path):
    async def _run():
        gate = AccountConcurrency()
        client = _Client()
        limit = {"n": 1}
        wrapped = ThrottledClient(client, lambda: gate.hold("acct", limit["n"]))

        first = asyncio.create_task(wrapped.chat("one"))
        await asyncio.sleep(0.02)
        limit["n"] = 3  # an /admin change lands between turns
        second = asyncio.create_task(wrapped.chat("two"))
        await asyncio.sleep(0.02)

        assert client.started == ["one", "two"]
        client.release.set()
        await asyncio.gather(first, second)
        # The first turn released into the abandoned gate; the books still balance.
        assert gate.stats() == {}

    asyncio.run(_run())


def test_the_wrapper_is_transparent_to_reads_writes_and_isinstance(tmp_path):
    gate = AccountConcurrency()
    target = SimpleNamespace(mode="", mode_status="", tone="Magic")
    wrapped = _wrap(gate, target)

    assert wrapped.tone == "Magic"
    wrapped.mode = "smart"
    wrapped._tone = "Reasoning"

    # Writes have to reach the real client, or the turn goes out misconfigured.
    assert (target.mode, target._tone) == ("smart", "Reasoning")
    assert isinstance(wrapped, SimpleNamespace)


def test_the_dependency_wraps_an_account_bound_client(tmp_path):
    app = FastAPI()
    app.state.settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    sentinel = SimpleNamespace()
    app.state.copilot_client_factory = lambda **kw: sentinel
    app.state.account_concurrency_gate = AccountConcurrency()
    app.state.account_concurrency = 2

    _, get_copilot_client = create_api_dependencies(app)
    account = SimpleNamespace(id="acct-1", provider="m365", token="t")
    request = SimpleNamespace(state=SimpleNamespace(account=account, api_key_obj=None))

    client = get_copilot_client(request)

    assert type(client) is ThrottledClient  # noqa: E721 - __class__ is delegated
    assert client._throttle_target is sentinel


def test_no_gate_on_state_means_no_wrapper(tmp_path):
    """A hand-built app (or one whose state predates this setting) must still serve."""
    app = FastAPI()
    app.state.settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    sentinel = SimpleNamespace()
    app.state.copilot_client_factory = lambda **kw: sentinel

    _, get_copilot_client = create_api_dependencies(app)
    account = SimpleNamespace(id="acct-1", provider="m365", token="t")
    request = SimpleNamespace(state=SimpleNamespace(account=account, api_key_obj=None))

    assert get_copilot_client(request) is sentinel


def test_the_cap_defaults_to_eight_and_zero_survives_a_save(tmp_path):
    assert _RUNTIME_SETTINGS_DEFAULTS["account_concurrency"] == 8

    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    client = TestClient(app)
    assert app.state.account_concurrency == 8

    # 0 means unlimited, so it must not fall back to the default on the way in.
    response = client.post("/admin/runtime-settings", json={"account_concurrency": 0})

    assert response.status_code == 200
    assert response.json()["settings"]["account_concurrency"] == 0
    assert app.state.account_concurrency == 0
    reloaded = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    assert reloaded.state.account_concurrency == 0


# --- the reset time upstream names ------------------------------------------
#
# Only consumer's throttle frame carries one (``nextAvailableAt``); no provider
# ever reports a remaining count. The number is gone the moment the 429 is
# written, so it is recorded at the same funnel that holds the account's slot.

_RESET_AT = "2026-08-25T12:00:00Z"


class _FailingClient:
    """A turn that always fails with one given error."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def chat(self, prompt):
        raise self.exc

    async def chat_stream(self, prompt):
        raise self.exc
        yield ""  # pragma: no cover - unreachable; keeps this an async generator


def _funnel(tmp_path, client):
    """The production path: create_api_dependencies over a store-backed account."""
    app = FastAPI()
    app.state.settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    app.state.copilot_client_factory = lambda **kw: client
    app.state.account_concurrency_gate = AccountConcurrency()
    app.state.account_concurrency = 2
    store = AccountStore(persist_path=tmp_path / "accounts.json")
    account = store.add(name="a")
    app.state.account_store = store

    _, get_copilot_client = create_api_dependencies(app)
    request = SimpleNamespace(state=SimpleNamespace(account=account, api_key_obj=None))
    return store, account, get_copilot_client(request)


@pytest.mark.parametrize("shape", ["raw", "translated"])
def test_a_throttled_turn_records_the_reset_time_upstream_named(tmp_path, shape):
    from m365_copilot_openai_proxy.consumer_client import AccountThrottled, parse_next_available_at
    from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError

    exc: Exception = AccountThrottled("spent", next_available_at=_RESET_AT)
    if shape == "translated":
        # What a route actually catches: the consumer adapter re-raises as the
        # Substrate error and copies the timestamp across. Keying on the
        # attribute rather than the type is what makes both shapes work.
        exc = SubstrateCopilotError("spent")
        exc.next_available_at = _RESET_AT

    store, account, client = _funnel(tmp_path, _FailingClient(exc))

    with pytest.raises(type(exc)):
        asyncio.run(client.chat("hi"))

    assert store.get(account.id).throttled_until == parse_next_available_at(_RESET_AT)


def test_a_throttled_stream_records_it_too(tmp_path):
    """chat_stream is a separate body, so it needs the hook of its own."""
    from m365_copilot_openai_proxy.consumer_client import AccountThrottled, parse_next_available_at

    exc = AccountThrottled("spent", next_available_at=_RESET_AT)
    store, account, client = _funnel(tmp_path, _FailingClient(exc))

    async def _drain():
        async for _ in client.chat_stream("hi"):
            pass

    with pytest.raises(AccountThrottled):
        asyncio.run(_drain())

    assert store.get(account.id).throttled_until == parse_next_available_at(_RESET_AT)


def test_a_failure_that_names_no_time_leaves_the_window_alone(tmp_path):
    """M365's throttle frame names no time, and an ordinary failure names none
    either -- neither may be turned into a quota window."""
    from m365_copilot_openai_proxy.substrate_client import SubstrateThrottled

    store, account, client = _funnel(tmp_path, _FailingClient(SubstrateThrottled("throttled")))

    with pytest.raises(SubstrateThrottled):
        asyncio.run(client.chat("hi"))

    assert store.get(account.id).throttled_until == 0.0


def test_the_recorded_window_survives_a_reload_and_reaches_both_payloads(tmp_path):
    """AccountStore._load rebuilds Account(...) field by field, so a field that
    saves but is not listed there silently never comes back."""
    from m365_copilot_openai_proxy.account_serializers import account_public, user_account_public

    path = tmp_path / "accounts.json"
    store = AccountStore(persist_path=path)
    acc = store.add(name="a")
    assert store.set_throttled_until(acc.id, 1800000000.0) is not None

    reloaded = AccountStore(persist_path=path).get(acc.id)

    assert reloaded.throttled_until == 1800000000.0
    assert account_public(reloaded)["throttled_until"] == 1800000000.0
    assert user_account_public(reloaded)["throttled_until"] == 1800000000.0


def test_set_throttled_until_rejects_nothing_but_clamps(tmp_path):
    store = AccountStore(persist_path=tmp_path / "accounts.json")
    assert store.set_throttled_until("acct_nope", 1.0) is None

    acc = store.add(name="a")
    # A negative timestamp would render as a window that never closes.
    store.set_throttled_until(acc.id, -5.0)
    assert store.get(acc.id).throttled_until == 0.0
