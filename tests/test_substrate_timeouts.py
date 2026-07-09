from __future__ import annotations

import asyncio

import pytest

from m365_copilot_openai_proxy import substrate_client
from m365_copilot_openai_proxy.substrate_client import (
    SIGNALR_SEP,
    SubstrateCopilotClient,
    SubstrateCopilotError,
)
from m365_copilot_openai_proxy.session_store import PersistentSession


def _make_client() -> SubstrateCopilotClient:
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._tone = "Magic"
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    # __new__ bypasses __init__, so set the instance idle timeout the client reads.
    client._idle_timeout = substrate_client._WS_IDLE_TIMEOUT
    return client


class _HangingWebSocket:
    """Completes the handshake recv, then never yields another frame."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def send(self, data):
        return None

    async def recv(self):
        # Handshake ack only; the frame loop uses the async iterator below.
        return "{}" + SIGNALR_SEP

    def __aiter__(self):
        return self

    async def __anext__(self):
        # Simulate an upstream that established the socket but stopped pushing:
        # block forever so the idle-timeout wrapper must fire.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def test_chat_stream_idle_timeout_raises(monkeypatch):
    monkeypatch.setattr(substrate_client, "_WS_IDLE_TIMEOUT", 0.05)
    monkeypatch.setattr(
        substrate_client.websockets, "connect", lambda *a, **k: _HangingWebSocket()
    )
    client = _make_client()

    async def collect():
        return [
            chunk
            async for chunk in client._chat_stream_for_turn(
                text="hi", conv_id="c", session_id="s", is_start_of_session=True
            )
        ]

    with pytest.raises(SubstrateCopilotError):
        asyncio.run(collect())


def test_idle_timeout_constructor_arg_overrides_default(monkeypatch):
    # A valid substrate JWT is required by __init__; stub the decode/claims checks
    # so we can exercise only the idle_timeout wiring.
    monkeypatch.setattr(substrate_client, "decode_jwt_payload", lambda t: {"oid": "o", "tid": "t", "exp": 9999999999})
    monkeypatch.setattr(substrate_client, "is_substrate_token_claims", lambda c: True)

    # Explicit override (in seconds) wins.
    client = SubstrateCopilotClient("token", idle_timeout=42)
    assert client._idle_timeout == 42.0

    # Falsy (None/0) => module default.
    client_default = SubstrateCopilotClient("token")
    assert client_default._idle_timeout == substrate_client._WS_IDLE_TIMEOUT


def test_session_lock_timeout_does_not_block_forever(monkeypatch):
    monkeypatch.setattr(substrate_client, "_SESSION_LOCK_TIMEOUT", 0.05)
    client = _make_client()

    async def run():
        session = PersistentSession()
        await session.lock.acquire()  # simulate an in-flight same-session stream
        try:
            gen = client.chat_stream("hi", [], session)
            with pytest.raises(SubstrateCopilotError):
                async for _ in gen:
                    pass
        finally:
            session.lock.release()

    asyncio.run(run())
