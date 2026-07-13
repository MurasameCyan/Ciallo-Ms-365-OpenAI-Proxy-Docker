from __future__ import annotations

from m365_copilot_openai_proxy.models import OpenAIResponsesRequest
from m365_copilot_openai_proxy.session_helpers import (
    _decode_responses_session_id,
    _encode_responses_session_id,
    _responses_session_key,
)


def test_encode_decode_round_trip_recovers_session_key():
    """The session key encoded into a resp_id must decode back exactly, so a
    client echoing previous_response_id lands on the same persistent session."""
    key = "responses_abc123def456"
    resp_id = _encode_responses_session_id(key)
    assert resp_id.startswith("resp_")
    assert _decode_responses_session_id(resp_id) == key


def test_encoded_ids_are_unique_but_decode_to_same_key():
    """Each turn returns a unique resp_id (OpenAI semantics) while still
    decoding to the stable conversation key."""
    key = "responses_stable"
    first = _encode_responses_session_id(key)
    second = _encode_responses_session_id(key)
    assert first != second
    assert _decode_responses_session_id(first) == key
    assert _decode_responses_session_id(second) == key


def test_decode_returns_none_for_foreign_ids():
    """Ids we did not produce (plain random ids, garbage) must return None so
    callers fall back to user / input-hash keys."""
    assert _decode_responses_session_id("resp_deadbeefdeadbeef") is None
    assert _decode_responses_session_id(None) is None
    assert _decode_responses_session_id("") is None
    assert _decode_responses_session_id("resp_") is None


def test_session_key_prefers_previous_response_id_over_input_hash():
    """previous_response_id must win over the input hash so multi-turn context
    stays stable even as the input array grows each turn."""
    original_key = _responses_session_key(
        OpenAIResponsesRequest(model="m365-copilot", input="first turn")
    )
    assert original_key is not None
    resp_id = _encode_responses_session_id(original_key)

    # Second turn: input changed (grew), but previous_response_id is echoed.
    next_turn = OpenAIResponsesRequest(
        model="m365-copilot",
        input="first turn and a much longer second turn",
        previous_response_id=resp_id,
    )
    assert _responses_session_key(next_turn) == original_key


def test_session_key_falls_back_to_input_hash_without_previous_id():
    """Without previous_response_id or user, behaviour is unchanged: a stable
    hash of the input (backward compatible)."""
    req = OpenAIResponsesRequest(model="m365-copilot", input="hello world")
    key = _responses_session_key(req)
    assert key is not None and key.startswith("responses_")
