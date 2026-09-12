"""Guards on tool_calls out and tool results in.

These pin three separate failure modes we can actually cause:

* a duplicated `tool_call` id, which makes the client's result mapping ambiguous
  and which Anthropic rejects outright on the next request;
* a tool result naming a call that was never made, which upstream answers with a
  400 for the whole request rather than for the stray message;
* a single response fanning out more calls than anyone budgeted for, which the
  client executes in parallel before any later round can intervene.

Both message dialects are exercised everywhere a message is read: routes hand
these functions pydantic models, the history index hands them plain dicts, and a
guard that only understands one shape silently passes everything in the other.
"""

from __future__ import annotations

from types import SimpleNamespace

from m365_copilot_openai_proxy.tool_hygiene import (
    MAX_TOOL_CALLS_PER_ROUND,
    REASON_BUDGET_SPENT,
    REASON_TOO_MANY_THIS_ROUND,
    dedupe_tool_call_ids,
    dedupe_tool_call_payloads,
    orphan_tool_results,
    over_cap_reasons,
    refuse_over_cap,
    tool_round_allowance,
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


# --------------------------------------------------------------- allowance

def test_allowance_is_the_smaller_of_the_two_caps():
    """Neither cap may be widened by the other."""
    assert tool_round_allowance(remaining_turn_budget=3, per_round_cap=8) == 3
    assert tool_round_allowance(remaining_turn_budget=20, per_round_cap=8) == 8


def test_an_unknown_turn_budget_falls_back_to_the_round_cap():
    assert tool_round_allowance(remaining_turn_budget=None, per_round_cap=5) == 5


def test_a_spent_turn_budget_allows_nothing():
    assert tool_round_allowance(remaining_turn_budget=0, per_round_cap=8) == 0
    assert tool_round_allowance(remaining_turn_budget=-4, per_round_cap=8) == 0


# --------------------------------------------------------------- refusals

def test_over_cap_calls_are_refused_with_a_result_never_dropped():
    """A tool_calls entry with no matching result leaves the client's transcript
    unpaired, and the NEXT request is then rejected for that orphan. So every
    input id has to come back either kept or refused."""
    calls = [_call(f"id{i}") for i in range(5)]

    kept, refusals = refuse_over_cap(calls, per_round_cap=2)

    assert [c["id"] for c in kept] == ["id0", "id1"]
    assert {r["tool_call_id"] for r in refusals} == {"id2", "id3", "id4"}
    assert {c["id"] for c in kept} | {r["tool_call_id"] for r in refusals} == {
        c["id"] for c in calls
    }


def test_the_round_cap_and_the_turn_budget_give_different_refusals():
    """The distinction is the whole point: 'budget spent' tells the model to stop
    working, which is a lie when only this round's fan-out was exceeded."""
    calls = [_call(f"id{i}") for i in range(6)]

    _kept, refusals = refuse_over_cap(calls, remaining_turn_budget=4, per_round_cap=2)

    by_id = {r["tool_call_id"]: r["reason"] for r in refusals}
    # Indexes 2 and 3 are inside the turn budget (4) but past the round cap (2).
    assert by_id["id2"] == REASON_TOO_MANY_THIS_ROUND
    assert by_id["id3"] == REASON_TOO_MANY_THIS_ROUND
    # Indexes 4 and 5 are past the turn budget itself.
    assert by_id["id4"] == REASON_BUDGET_SPENT
    assert by_id["id5"] == REASON_BUDGET_SPENT


def test_each_refusal_message_tells_the_model_the_right_thing_to_do():
    """The codes are for us; the messages are what the MODEL reads, so they have
    to carry the same distinction. "Budget spent" must tell it to answer with what
    it has; the round cap must tell it to come back -- the inverse of either one
    makes the model give up early or retry forever."""
    calls = [_call(f"id{i}") for i in range(4)]

    _kept, refusals = refuse_over_cap(calls, remaining_turn_budget=3, per_round_cap=1)

    by_code = {r["reason"]: r["message"] for r in refusals}
    assert "next round" in by_code[REASON_TOO_MANY_THIS_ROUND]
    assert "next round" not in by_code[REASON_BUDGET_SPENT]
    assert "already" in by_code[REASON_BUDGET_SPENT]


def test_a_round_within_both_caps_refuses_nothing():
    calls = [_call("a"), _call("b")]

    kept, refusals = refuse_over_cap(calls, remaining_turn_budget=10, per_round_cap=8)

    assert kept == calls
    assert refusals == []


def test_the_default_round_cap_is_what_binds_when_no_budget_is_given():
    calls = [_call(f"id{i}") for i in range(MAX_TOOL_CALLS_PER_ROUND + 2)]

    kept, refusals = refuse_over_cap(calls)

    assert len(kept) == MAX_TOOL_CALLS_PER_ROUND
    assert len(refusals) == 2
    assert all(r["reason"] == REASON_TOO_MANY_THIS_ROUND for r in refusals)


def test_the_human_facing_note_names_which_cap_bound():
    """A log that only says 'refused N' cannot tell a turn that ran out of budget
    over many rounds apart from one shotgun response."""
    calls = [_call(f"id{i}") for i in range(6)]
    _kept, refusals = refuse_over_cap(calls, remaining_turn_budget=4, per_round_cap=2)

    notes = over_cap_reasons(refusals)

    assert len(notes) == 2
    assert any("单轮上限" in n for n in notes)
    assert any("预算" in n for n in notes)


def test_no_refusals_means_no_note():
    assert over_cap_reasons([]) == []
