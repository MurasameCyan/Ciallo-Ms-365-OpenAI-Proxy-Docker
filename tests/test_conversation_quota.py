"""The server's own conversation-message count must reach an operator intact.

Every token number this proxy reports is its own estimate -- the ChatHub protocol
sends no token usage at all. What it DOES send is `throttling`, how many user
messages the conversation has spent against its ceiling, and the only thing we
did with it was read the `Throttled` verdict off a failed turn.

Measured 2026-09-14 against the deployed container (`.probe/throttling_counters.py`,
three turns on one PersistentSession, tone Claude_Sonnet): `num` advanced 1 -> 2 -> 3,
`max` held at 600, and BOTH the update frames (`arguments[0].throttling`) and the
completion frame (`item.throttling`) carried it on every single turn. The frame
shapes below are copied from that capture.

What each test here defends, and the plausible bug it would catch:
  * reading the count must not disturb delivery -- a parse bolted into the hot
    frame loop that swallowed or reordered a delta would be a far worse
    regression than the missing number it adds
  * a frame with no `throttling` must leave the last known value alone; the
    quota describes the conversation, not the frame
  * "not reported" must stay None, never 0/0, or a build that stops sending the
    object would read as a fresh conversation with nothing spent
  * a broken telemetry sink must never take the turn down with it
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.conversation_quota import ConversationQuotaStore
from m365_copilot_openai_proxy.substrate_client import (
    SIGNALR_SEP,
    SubstrateCopilotClient,
)


ANSWER = "Send an application-level heartbeat every 30 seconds."

# Verbatim field names from the live capture. Spelling them out rather than
# building them from a helper is deliberate: a rename upstream has to break this.
THROTTLING = {
    "numUserMessagesInConversation": 3,
    "maxNumUserMessagesInConversation": 600,
    "numLongDocSummaryUserMessagesInConversation": 0,
}


def _fake_ws(messages: list[dict]):
    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            return None

        async def recv(self):
            return "{}" + SIGNALR_SEP

        def __aiter__(self):
            self._messages = iter(
                [json.dumps(m) + SIGNALR_SEP for m in [*messages, {"type": 3}]]
            )
            return self

        async def __anext__(self):
            try:
                return next(self._messages)
            except StopIteration:
                raise StopAsyncIteration

    return FakeWebSocket


def _client() -> SubstrateCopilotClient:
    """A client built the way every substrate fixture builds one: no __init__.

    This is also the shape that made the first draft of the feature fragile --
    `__new__` never runs `__init__`, so any attribute the frame loop reads
    directly has to tolerate being absent.
    """
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._tone = "Claude_Sonnet"
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    return client


def _delta(text: str, throttling: dict | None = None) -> dict:
    args: dict = {"writeAtCursor": text}
    if throttling is not None:
        args["throttling"] = throttling
    return {"type": 1, "target": "update", "arguments": [args]}


def _complete(text: str, throttling: dict | None = None) -> dict:
    item: dict = {
        "messages": [{"author": "bot", "text": text, "contentOrigin": "DeepLeo"}],
        "result": {"value": "Success"},
        "turnState": "Completed",
    }
    if throttling is not None:
        item["throttling"] = throttling
    return {"type": 2, "item": item}


def _run(client: SubstrateCopilotClient, frames: list[dict], monkeypatch) -> str:
    import websockets

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _fake_ws(frames)())

    async def go() -> str:
        chunks = []
        async for chunk in client._chat_stream_for_turn(
            "q", "conv", "sess", is_start_of_session=True
        ):
            chunks.append(chunk)
        return "".join(chunks)

    return asyncio.run(go())


# ------------------------------------------------------- delivery is untouched

@pytest.mark.parametrize(
    "frames_desc, frames",
    [
        ("update frame carries it", [_delta(ANSWER, THROTTLING), _complete(ANSWER)]),
        ("completion frame carries it", [_delta(ANSWER), _complete(ANSWER, THROTTLING)]),
        (
            "both carry it, as measured",
            [_delta(ANSWER, THROTTLING), _complete(ANSWER, THROTTLING)],
        ),
    ],
)
def test_the_answer_survives_wherever_the_quota_rides(frames_desc, frames, monkeypatch):
    """Whichever frame carries the counters, the reply is byte-identical.

    The number is worthless if collecting it costs a delta, and the parse sits in
    the loop that yields them.
    """
    client = _client()
    seen: list[dict] = []
    client._quota_sink = seen.append

    assert _run(client, frames, monkeypatch) == ANSWER
    assert seen[-1] == {"messages": 3, "max_messages": 600, "long_doc_messages": 0}


def test_a_turn_that_never_reports_a_quota_reads_as_no_data(monkeypatch):
    """Nothing is emitted at all, so no reader can mistake silence for 0/0."""
    client = _client()
    seen: list[dict] = []
    client._quota_sink = seen.append

    assert _run(client, [_delta(ANSWER), _complete(ANSWER)], monkeypatch) == ANSWER
    assert seen == []


def test_a_later_frame_without_throttling_does_not_erase_the_count(monkeypatch):
    """The quota describes the conversation, so absence is silence, not zero.

    Live turns interleave many frames and only some carry `throttling`; treating
    a bare frame as a reset would leave the last reading wrong on most turns.
    """
    client = _client()
    store = ConversationQuotaStore()
    client._quota_sink = lambda quota: store.record("acct_1", quota)

    text = _run(
        client,
        [_delta("Send an ", THROTTLING), _delta("application-level heartbeat."),
         _complete("Send an application-level heartbeat.")],
        monkeypatch,
    )

    assert text == "Send an application-level heartbeat."
    assert store.stats()["acct_1"]["messages"] == 3


def test_the_newest_report_wins_even_when_it_counts_down(monkeypatch):
    """A fresh conversation on the same client legitimately restarts the count."""
    client = _client()
    store = ConversationQuotaStore()
    client._quota_sink = lambda quota: store.record("acct_1", quota)

    _run(client, [_delta(ANSWER, THROTTLING), _complete(ANSWER)], monkeypatch)
    _run(
        client,
        [_delta(ANSWER, {"numUserMessagesInConversation": 1,
                         "maxNumUserMessagesInConversation": 600}),
         _complete(ANSWER)],
        monkeypatch,
    )

    assert store.stats()["acct_1"]["messages"] == 1


@pytest.mark.parametrize(
    "throttling",
    [
        {"maxNumUserMessagesInConversation": 600},          # no current count
        {"numUserMessagesInConversation": 3},               # no ceiling
        {"numUserMessagesInConversation": "3",
         "maxNumUserMessagesInConversation": 600},          # string, not int
        {},
    ],
)
def test_a_half_shaped_throttling_object_is_not_a_reading(throttling, monkeypatch):
    """Partial data must be dropped, not defaulted into a plausible-looking number."""
    client = _client()
    seen: list[dict] = []
    client._quota_sink = seen.append

    assert _run(client, [_delta(ANSWER, throttling), _complete(ANSWER)], monkeypatch) == ANSWER
    assert seen == []


def test_a_broken_quota_sink_cannot_take_the_turn_down(monkeypatch):
    """Telemetry is never worth a failed reply."""
    client = _client()

    def exploding_sink(quota):
        raise RuntimeError("sink is broken")

    client._quota_sink = exploding_sink

    assert _run(client, [_delta(ANSWER, THROTTLING), _complete(ANSWER)], monkeypatch) == ANSWER


def test_the_sink_sees_the_count_the_client_saw(monkeypatch):
    """What an operator is shown must be what the frame said."""
    client = _client()
    seen: list[dict] = []
    client._quota_sink = seen.append

    _run(client, [_delta(ANSWER, THROTTLING), _complete(ANSWER, THROTTLING)], monkeypatch)

    assert seen, "the sink was never called"
    assert seen[-1] == {"messages": 3, "max_messages": 600, "long_doc_messages": 0}


# ------------------------------------------------------------------- the store

def test_the_store_reports_what_an_operator_needs_to_act_on():
    """Spent, ceiling, and how much is left -- derived once, not per template."""
    store = ConversationQuotaStore()

    store.record("acct_1", {"messages": 150, "max_messages": 600})

    entry = store.stats()["acct_1"]
    assert entry["messages"] == 150
    assert entry["max_messages"] == 600
    assert entry["remaining"] == 450
    assert entry["percent"] == 25.0


def test_the_store_takes_the_newest_reading_even_if_it_is_lower():
    """The server is the authority; a new conversation resets its own count."""
    store = ConversationQuotaStore()

    store.record("acct_1", {"messages": 400, "max_messages": 600})
    store.record("acct_1", {"messages": 2, "max_messages": 600})

    assert store.stats()["acct_1"]["messages"] == 2


def test_a_stated_ceiling_of_zero_yields_no_percentage():
    """Zero is 'no ceiling stated', not 'nothing left' -- and never a ZeroDivisionError."""
    store = ConversationQuotaStore()

    store.record("acct_1", {"messages": 0, "max_messages": 0})

    entry = store.stats()["acct_1"]
    assert "percent" not in entry
    assert "remaining" not in entry


@pytest.mark.parametrize("quota", [None, {}, {"messages": 3}, {"messages": None, "max_messages": 600}])
def test_the_store_refuses_a_reading_it_cannot_trust(quota):
    """Better absent than invented: a bad payload must not become a displayed number."""
    store = ConversationQuotaStore()

    store.record("acct_1", quota)

    assert store.stats() == {}


def test_a_deleted_account_stops_being_reported():
    """The gauge is keyed by account id, and a deleted account can never issue
    another turn -- so nothing would ever overwrite its last reading. Left in
    place it is a number an operator cannot act on and cannot clear, which is
    worse than showing nothing."""
    store = ConversationQuotaStore()
    store.record("gone", {"messages": 12, "max_messages": 600})
    store.record("stays", {"messages": 3, "max_messages": 600})

    store.forget("gone")

    assert "gone" not in store.stats()
    assert store.stats()["stays"]["messages"] == 3

def test_a_late_inflight_report_after_forget_is_ignored():
    store = ConversationQuotaStore()

    store.forget("gone")
    store.record("gone", {"messages": 12, "max_messages": 600})

    assert "gone" not in store.stats()


@pytest.mark.parametrize("unknown", ["never_seen", "", "   "])
def test_forgetting_an_account_that_never_reported_is_harmless(unknown):
    """Account deletion runs this unconditionally, including for accounts that
    never ran a turn, so it must not raise or disturb other entries."""
    store = ConversationQuotaStore()
    store.record("acct_1", {"messages": 5, "max_messages": 600})

    store.forget(unknown)

    assert store.stats()["acct_1"]["messages"] == 5


def test_the_store_does_not_grow_without_bound():
    """A long-lived process rotating accounts must not accumulate them forever."""
    store = ConversationQuotaStore()

    for index in range(ConversationQuotaStore._MAX_ACCOUNTS + 25):
        store.record(f"acct_{index}", {"messages": index, "max_messages": 600})

    assert len(store.stats()) <= ConversationQuotaStore._MAX_ACCOUNTS
    # The most recent reading is the one that must still be there.
    newest = f"acct_{ConversationQuotaStore._MAX_ACCOUNTS + 24}"
    assert newest in store.stats()


# --------------------------------------------------- through the actual route
#
# Every test above this line calls the store directly. That is exactly how the
# fan-out caps in tool_hygiene.py came to be dead code: ten green assertions,
# all of them invoking the functions by hand, none of them going through a
# route -- so "implemented and tested" hid "called by nothing". `forget()` is
# reachable only from DELETE /admin/accounts/{id}, so it gets a test that goes
# through that endpoint rather than one more direct call.

def _admin_client(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    client = TestClient(app)
    # /admin/* authenticates with the cookie /admin/login sets, not a bearer
    # header. Getting this wrong is what made a live probe report 18/18 failures
    # against working code.
    assert client.post("/admin/login", json={"password": "admin-key"}).status_code == 200
    return app, client


def _quota_in_stats(client: TestClient) -> dict:
    response = client.get("/admin/stats")
    assert response.status_code == 200, response.text
    return ((response.json() or {}).get("cache") or {}).get("conversation_quota") or {}


def test_deleting_an_account_clears_its_quota_from_the_admin_snapshot(tmp_path):
    """The route, not the store method, is what an operator actually triggers.

    A reading left behind after deletion is unfixable by design: the account can
    never run another turn, so no later frame can overwrite it, and there is no
    per-account clear. It would sit in /admin/stats looking authoritative
    forever.
    """
    app, client = _admin_client(tmp_path)
    doomed = app.state.account_store.add(name="doomed", token="")
    kept = app.state.account_store.add(name="kept", token="")
    from types import SimpleNamespace
    from m365_copilot_openai_proxy.dependencies import _attach_quota_sink

    inflight_client = SimpleNamespace()
    _attach_quota_sink(app, inflight_client, doomed)
    app.state.conversation_quota_store.record(doomed.id, {"messages": 12, "max_messages": 600})
    app.state.conversation_quota_store.record(kept.id, {"messages": 3, "max_messages": 600})
    assert doomed.id in _quota_in_stats(client)

    assert client.delete(f"/admin/accounts/{doomed.id}").status_code == 200
    inflight_client._quota_sink({"messages": 13, "max_messages": 600})

    surfaced = _quota_in_stats(client)
    assert doomed.id not in surfaced
    # The neighbour must be untouched: a delete that cleared the whole gauge
    # would also "pass" the assertion above.
    assert surfaced[kept.id]["messages"] == 3


def test_deleting_an_account_that_never_ran_a_turn_still_succeeds(tmp_path):
    """The route calls forget() unconditionally, so the common case -- an account
    removed before it ever answered anything -- must not 500."""
    app, client = _admin_client(tmp_path)
    account = app.state.account_store.add(name="never-used", token="")

    assert client.delete(f"/admin/accounts/{account.id}").status_code == 200
    assert _quota_in_stats(client) == {}
