"""Auto-heal a rotted persistent M365 conversation.

A reused persistent conversation can start refusing every *continuation* turn
(``turnState=Failed`` / canned refusal) even though the same tone answers fine in
a brand-new conversation -- observed live as turns 13/14/15 refusing across
different tones after turns 4-12 succeeded, then a fresh chat working instantly.

``SubstrateCopilotClient.chat_stream`` must self-heal that case: on a continuation
turn that refuses before anything is streamed, discard the poisoned conversation,
retry ONCE as a fresh start-of-session turn, and keep the reset so following turns
run on the new conversation too -- instead of forcing the user to open a new chat.

The retry is deliberately scoped: only continuation turns (a fresh turn refusing
is a genuine tone/account outage), only refusals (an empty turn is already retried
upstream on a throwaway conversation), and only before any content has streamed.
"""

from __future__ import annotations

import asyncio

import pytest

from m365_copilot_openai_proxy.session_store import PersistentSession
from m365_copilot_openai_proxy.substrate_client import (
    SubstrateCopilotClient,
    SubstrateCopilotError,
)

_REFUSAL = (
    "M365 Copilot refused this turn instead of answering "
    "(conversation mode 'Magic') (upstream result: Success). If every request in "
    "this mode does this, the mode is not available for this account -- switch to "
    "another mode."
)


def _client() -> SubstrateCopilotClient:
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._tone = "Magic"
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    return client


def _collect(client: SubstrateCopilotClient, session: PersistentSession) -> list[str]:
    async def run() -> list[str]:
        return [chunk async for chunk in client.chat_stream("hi", [], session)]

    return asyncio.run(run())


def test_continuation_refusal_resets_and_retries_on_fresh_conversation():
    client = _client()
    events: list[dict] = []

    async def stub(*, text, conv_id, session_id, is_start_of_session, annotations=None):
        events.append({"conv_id": conv_id, "start": is_start_of_session})
        if not is_start_of_session:
            raise SubstrateCopilotError(_REFUSAL)
        yield "healed answer"

    client._stream_turn_with_retry = stub
    session = PersistentSession()
    session.turn_count = 5  # deep into a reused conversation -> continuation turn
    original_conv = session.conversation_id

    out = _collect(client, session)

    assert out == ["healed answer"]
    # Two attempts: the poisoned continuation, then a fresh start-of-session turn.
    assert [e["start"] for e in events] == [False, True]
    # The reset sticks so later turns use the new conversation, not just this one.
    assert session.conversation_id != original_conv
    assert events[0]["conv_id"] == original_conv
    assert events[1]["conv_id"] == session.conversation_id
    assert session.turn_count == 1  # fresh conversation advanced exactly one turn


def test_start_of_session_refusal_propagates_without_retry():
    client = _client()
    events: list[bool] = []

    async def always_refuse(*, text, conv_id, session_id, is_start_of_session, annotations=None):
        events.append(is_start_of_session)
        raise SubstrateCopilotError(_REFUSAL)
        yield ""  # pragma: no cover - marks this as an async generator

    client._stream_turn_with_retry = always_refuse
    session = PersistentSession()  # turn_count=0 -> first turn is start-of-session

    with pytest.raises(SubstrateCopilotError):
        _collect(client, session)

    # A fresh conversation refusing is a real outage; retrying another fresh one is
    # pointless, so there must be exactly one attempt.
    assert events == [True]


def test_continuation_non_refusal_error_propagates_without_retry():
    client = _client()
    events: list[bool] = []

    async def idle_timeout(*, text, conv_id, session_id, is_start_of_session, annotations=None):
        events.append(is_start_of_session)
        raise SubstrateCopilotError("Upstream stopped sending data (idle timeout).")
        yield ""  # pragma: no cover - marks this as an async generator

    client._stream_turn_with_retry = idle_timeout
    session = PersistentSession()
    session.turn_count = 3
    original_conv = session.conversation_id

    with pytest.raises(SubstrateCopilotError):
        _collect(client, session)

    assert events == [False]  # not a refusal -> no auto-retry
    assert session.conversation_id == original_conv  # conversation not reset


def test_refusal_after_partial_stream_is_not_retried():
    client = _client()
    events: list[bool] = []

    async def partial_then_refuse(*, text, conv_id, session_id, is_start_of_session, annotations=None):
        events.append(is_start_of_session)
        yield "partial"
        raise SubstrateCopilotError(_REFUSAL)

    client._stream_turn_with_retry = partial_then_refuse
    session = PersistentSession()
    session.turn_count = 2

    async def run() -> list[str]:
        chunks: list[str] = []
        with pytest.raises(SubstrateCopilotError):
            async for chunk in client.chat_stream("hi", [], session):
                chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())

    assert chunks == ["partial"]  # already-streamed content is preserved
    assert events == [False]  # cannot retry once bytes are on the wire


def test_reset_conversation_starts_fresh_in_place():
    saves: list[int] = []
    session = PersistentSession()
    session._on_change = lambda: saves.append(1)
    session.reserve_turn()
    session.reserve_turn()
    old_conv, old_sess = session.conversation_id, session.client_session_id

    session.reset_conversation()

    assert session.turn_count == 0
    assert session.conversation_id != old_conv
    assert session.client_session_id != old_sess
    assert saves  # the reset is persisted so a restart keeps the fresh conversation
