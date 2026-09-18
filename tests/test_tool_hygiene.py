"""Guards on tool_calls out and tool results in.

These pin two separate failure modes we can actually cause:

* a duplicated `tool_call` id, which makes the client's result mapping ambiguous
  and which Anthropic rejects outright on the next request;
* a tool result naming a call that was never made, which upstream answers with a
  400 for the whole request rather than for the stray message.

A third guard (a per-round fan-out cap) was removed on 2026-09-14: it had no
caller in `src/`, and these tests were green anyway because they called it
directly. Measured on the deployed build, the largest real round carried ONE
call against a cap of 8, so it never bound. See tool_hygiene's module docstring
before reintroducing it.

Both message dialects are exercised everywhere a message is read: routes hand
these functions pydantic models, the history index hands them plain dicts, and a
guard that only understands one shape silently passes everything in the other.
"""

from __future__ import annotations

from types import SimpleNamespace

from m365_copilot_openai_proxy.tool_hygiene import (
    dedupe_tool_call_ids,
    dedupe_tool_call_payloads,
    orphan_tool_results,
)


def _call(call_id: str, name: str = "read_file") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


# --------------------------------------------------------------- dedupe

def test_duplicate_ids_keep_the_first_occurrence():
    kept, reasons = dedupe_tool_call_ids([_call("a"), _call("b"), _call("a", "other")])

    assert [c["id"] for c in kept] == ["a", "b"]
    # The survivor must be the FIRST 'a', not the last one to arrive.
    assert kept[0]["function"]["name"] == "read_file"
    assert len(reasons) == 1
    assert "a" in reasons[0]


def test_a_call_with_no_id_is_rejected_rather_than_assigned_one():
    """Our emitter always mints an id, so a blank one means a malformed parse.

    Back-filling would hand the client a call whose result it cannot correlate.
    """
    kept, reasons = dedupe_tool_call_ids([_call(""), _call("   "), _call("ok")])

    assert [c["id"] for c in kept] == ["ok"]
    assert len(reasons) == 2


def test_distinct_ids_pass_through_untouched():
    calls = [_call("a"), _call("b"), _call("c")]

    kept, reasons = dedupe_tool_call_ids(calls)

    assert kept == calls
    assert reasons == []


# ------------------------------------------------------- payload dedupe

def test_the_same_intent_parsed_twice_is_delivered_once():
    """The duplicate that actually reaches clients, and the one id-dedupe cannot
    see: `_extract_tool_calls` mints a fresh uuid per parse pass, so one model
    intent appearing twice in the prose becomes two calls with different ids and
    byte-identical payloads. Executing both repeats the side effect."""
    write = {
        "id": "call_first",
        "type": "function",
        "function": {"name": "Write", "arguments": '{"file_path": "/a.txt"}'},
    }
    echo = {
        "id": "call_second",
        "type": "function",
        "function": {"name": "Write", "arguments": '{"file_path": "/a.txt"}'},
    }

    kept, reasons = dedupe_tool_call_payloads([write, echo])

    assert [c["id"] for c in kept] == ["call_first"]
    assert len(reasons) == 1
    assert "Write" in reasons[0]


def test_id_dedupe_alone_cannot_catch_a_repeated_payload():
    """Guards the reason this function exists. If this ever passes through
    dedupe_tool_call_ids, the payload guard has become redundant -- but two uuid4
    ids never collide, so it cannot."""
    duplicated = [
        {"id": "u1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "rm -rf /tmp/x"}'}},
        {"id": "u2", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "rm -rf /tmp/x"}'}},
    ]

    by_id, id_reasons = dedupe_tool_call_ids(duplicated)
    by_payload, payload_reasons = dedupe_tool_call_payloads(duplicated)

    assert len(by_id) == 2 and id_reasons == []
    assert len(by_payload) == 1 and len(payload_reasons) == 1


def test_same_tool_with_different_arguments_is_not_a_duplicate():
    """Two reads of different files are two real requests; collapsing them would
    silently drop work the model asked for."""
    calls = [
        {"id": "a", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "/a"}'}},
        {"id": "b", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "/b"}'}},
    ]

    kept, reasons = dedupe_tool_call_payloads(calls)

    assert kept == calls
    assert reasons == []


# --------------------------------------------------------------- orphans

def test_openai_tool_message_answering_no_call_is_an_orphan():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "never_called", "content": "42"},
    ]

    reasons = orphan_tool_results(messages)

    assert len(reasons) == 1
    assert "never_called" in reasons[0]
    assert "tool_call_id" in reasons[0]


def test_anthropic_tool_result_block_answering_no_call_is_an_orphan():
    messages = [
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "ghost", "content": "42"}],
        }
    ]

    reasons = orphan_tool_results(messages)

    assert len(reasons) == 1
    assert "ghost" in reasons[0]
    assert "tool_use_id" in reasons[0]


def test_a_properly_paired_openai_result_produces_no_orphan():
    """Without this the orphan check could be vacuously true."""
    messages = [
        {"role": "assistant", "tool_calls": [_call("call_1")]},
        {"role": "tool", "tool_call_id": "call_1", "content": "42"},
    ]

    assert orphan_tool_results(messages) == []


def test_a_properly_paired_anthropic_result_produces_no_orphan():
    messages = [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "use_1", "name": "read_file"}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "use_1", "content": "42"}],
        },
    ]

    assert orphan_tool_results(messages) == []


def test_a_result_arriving_before_its_own_call_is_still_an_orphan():
    """Ids are accumulated walking forward, so order is part of the contract:
    upstream rejects a result that precedes its call exactly as it rejects one
    with no call at all."""
    messages = [
        {"role": "tool", "tool_call_id": "call_1", "content": "42"},
        {"role": "assistant", "tool_calls": [_call("call_1")]},
    ]

    assert len(orphan_tool_results(messages)) == 1


def test_pydantic_style_messages_are_read_the_same_as_dicts():
    """Routes pass models; the history index passes dicts. A guard that only
    understands dicts would pass every model-shaped request unchecked."""
    paired = [
        SimpleNamespace(
            role="assistant",
            content=None,
            tool_calls=[SimpleNamespace(id="call_1")],
        ),
        SimpleNamespace(role="tool", content="42", tool_call_id="call_1"),
    ]
    orphaned = [SimpleNamespace(role="tool", content="42", tool_call_id="stray")]

    assert orphan_tool_results(paired) == []
    assert len(orphan_tool_results(orphaned)) == 1


def test_a_tool_result_with_no_id_at_all_is_reported():
    messages = [{"role": "tool", "content": "42"}]

    reasons = orphan_tool_results(messages)

    assert len(reasons) == 1
