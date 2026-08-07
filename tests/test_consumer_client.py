"""Unit tests for the consumer-Copilot protocol helpers.

Covers the two pieces that fail silently if wrong: the proof-of-work solvers
(a bad nonce stalls the socket until the idle timeout) and the frame splitter
(Copilot packs several JSON objects into one WS frame).
"""

import asyncio
import hashlib
import json
import threading

import pytest

from curl_cffi.requests import WebSocketClosed, WebSocketError, WebSocketTimeout

from m365_copilot_openai_proxy.consumer_client import (
    ClearanceRequired,
    ConsumerCopilotClient,
    ConsumerCopilotError,
    RegionBlocked,
    drain_json,
    solve_challenge,
    solve_copilot_challenge,
    solve_hashcash,
)


def _leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte:
            return bits + (8 - byte.bit_length())
        bits += 8
    return bits


@pytest.mark.parametrize("difficulty", [0, 1, 4, 8, 11])
def test_hashcash_nonce_actually_satisfies_the_difficulty(difficulty):
    seed = "269f08c72d841a24d839b0d55d2dadbb3551d7f89d35991f4bef499c893b253d"
    nonce = solve_hashcash(f"{seed}:{difficulty}")
    digest = hashlib.sha256(f"{seed}{nonce}".encode()).digest()
    assert _leading_zero_bits(digest) >= difficulty


def test_hashcash_returns_the_smallest_nonce():
    # The real client sends the first nonce that works; a larger one is accepted
    # but proves the scan skipped candidates, so guard the scan order.
    seed = "abc"
    nonce = int(solve_hashcash(f"{seed}:8"))
    for smaller in range(nonce):
        assert _leading_zero_bits(hashlib.sha256(f"{seed}{smaller}".encode()).digest()) < 8


def test_hashcash_splits_on_the_last_colon():
    # Seeds are hex today, but the parameter format is "<seed>:<difficulty>" and
    # a seed containing a colon must not break the difficulty parse.
    assert solve_hashcash("a:b:0") == "0"


def test_hashcash_rejects_unbounded_server_difficulty():
    with pytest.raises(ValueError, match="difficulty"):
        solve_hashcash("seed:23")


def test_copilot_arithmetic_challenge():
    assert solve_copilot_challenge("7") == str(round((7**3 / 100 + 7 * 25) % 22))
    assert solve_copilot_challenge("0") == "0"


def test_solve_challenge_dispatches_by_method():
    assert solve_challenge({"method": "hashcash", "parameter": "seed:0"}) == "0"
    assert solve_challenge({"method": "copilot", "parameter": "7"}) is not None


@pytest.mark.parametrize("msg", [
    {"method": None, "parameter": None},
    {"method": "cloudflare", "parameter": "x"},
    {"method": "some-new-pow", "parameter": "x"},
    {"method": "hashcash"},  # no parameter -> unsolvable, not a crash
])
def test_browser_only_challenges_return_none(msg):
    # None is the signal the caller turns into ClearanceRequired. Answering an
    # empty challenge with an empty token stalls the socket instead.
    assert solve_challenge(msg) is None


def test_drain_json_splits_concatenated_objects():
    raw = '{"event":"connected"}{"event":"appendText","text":"hi"}'
    assert drain_json(raw) == [
        {"event": "connected"},
        {"event": "appendText", "text": "hi"},
    ]


def test_drain_json_handles_whitespace_and_record_separators():
    raw = '\x1e{"a":1}\n  {"b":2}\r\n'
    assert drain_json(raw) == [{"a": 1}, {"b": 2}]


def test_drain_json_drops_a_trailing_partial_object():
    # A frame can end mid-object; the parsed prefix must still be usable.
    assert drain_json('{"a":1}{"b":') == [{"a": 1}]


def test_drain_json_accepts_bytes_and_ignores_non_objects():
    assert drain_json(b'{"a":1}') == [{"a": 1}]
    assert drain_json('[1,2]{"a":1}') == [{"a": 1}]


def test_ws_url_carries_session_id_and_encodes_the_token():
    client = ConsumerCopilotClient(access_token="a b+c", identity_type="Google")
    url = client._ws_url()
    assert "clientSessionId=" in url  # omitting it triggers invalid-event
    # JWTs contain '+' and '='; unescaped they'd corrupt the query and 401 the upgrade.
    assert "accessToken=a%20b%2Bc" in url
    assert "X-UserIdentityType=Google" in url


def test_ws_url_omits_auth_params_when_anonymous():
    url = ConsumerCopilotClient()._ws_url()
    assert "accessToken=" not in url and "X-UserIdentityType=" not in url


class _FakeSocket:
    """Minimal curl_cffi socket stand-in: replays frames, records sent JSON."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []

    async def send(self, payload, flags=None):
        self.sent.append(json.loads(payload))

    async def recv(self, *, timeout=None):
        if not self._frames:
            raise AssertionError("stream read past the scripted frames")
        frame = self._frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        return frame, 1


async def _read(client, socket) -> str:
    send = {"event": "send"}
    return "".join([chunk async for chunk in client._read_stream(socket, send)])


def _collect(client, socket) -> str:
    # ponytail: asyncio.run instead of a pytest async plugin — the repo has none
    # installed and these tests don't need one.
    return asyncio.run(_read(client, socket))


def test_stream_answers_the_challenge_and_resends_the_held_message():
    socket = _FakeSocket([
        '{"event":"connected"}{"event":"challenge","method":"hashcash","parameter":"s:0","id":"0.1"}',
        '{"event":"appendText","text":"PROBE"}{"event":"appendText","text":"-OK"}',
        '{"event":"done"}',
    ])
    assert _collect(ConsumerCopilotClient(), socket) == "PROBE-OK"
    assert [m.get("event") for m in socket.sent] == ["challengeResponse", "send"]
    assert socket.sent[0]["id"] == "0.1"  # the backend correlates on the id


def test_stream_solves_hashcash_outside_the_event_loop(monkeypatch):
    solver_threads = []

    def solve_in_worker(message):
        solver_threads.append(threading.current_thread())
        return "0"

    monkeypatch.setattr(
        "m365_copilot_openai_proxy.consumer_client.solve_challenge",
        solve_in_worker,
    )
    socket = _FakeSocket([
        '{"event":"challenge","method":"hashcash","parameter":"s:0"}',
        '{"event":"done"}',
    ])

    _collect(ConsumerCopilotClient(), socket)

    assert solver_threads[0] is not threading.main_thread()


def test_repeated_challenge_is_not_answered_twice():
    socket = _FakeSocket([
        '{"event":"challenge","method":"hashcash","parameter":"s:0","id":"0.1"}',
        '{"event":"challenge","method":"hashcash","parameter":"s:0","id":"0.1"}',
        '{"event":"appendText","text":"hi"}{"event":"done"}',
    ])
    assert _collect(ConsumerCopilotClient(), socket) == "hi"
    assert len(socket.sent) == 2  # one challengeResponse + one re-send, not four


def test_turnstile_after_a_solved_pow_still_raises():
    # The regression this guards: gating the Turnstile check behind `answered`
    # swallows the frame and the turn dies at the idle timeout instead.
    socket = _FakeSocket([
        '{"event":"challenge","method":"hashcash","parameter":"s:0","id":"0.1"}',
        '{"event":"challenge","method":null,"id":"0.2"}',
    ])
    with pytest.raises(ClearanceRequired):
        _collect(ConsumerCopilotClient(), socket)


def test_chat_service_unavailable_is_a_typed_region_error():
    socket = _FakeSocket(['{"event":"error","errorCode":"chat-service-unavailable"}'])
    with pytest.raises(RegionBlocked, match="anonymous"):
        _collect(ConsumerCopilotClient(), socket)


def test_curl_websocket_timeout_becomes_a_typed_idle_error():
    socket = _FakeSocket([WebSocketTimeout("timed out")])

    with pytest.raises(ConsumerCopilotError, match="went silent"):
        _collect(ConsumerCopilotClient(idle_timeout=3), socket)


def test_curl_websocket_close_before_reply_is_not_silently_accepted():
    socket = _FakeSocket([WebSocketClosed("closed")])

    with pytest.raises(ConsumerCopilotError, match="closed without replying"):
        _collect(ConsumerCopilotClient(), socket)


def test_curl_websocket_transport_error_keeps_the_cause():
    socket = _FakeSocket([WebSocketError("recv failed")])

    with pytest.raises(ConsumerCopilotError, match="recv failed") as error:
        _collect(ConsumerCopilotClient(), socket)
    assert isinstance(error.value.__cause__, WebSocketError)


def test_partial_reply_followed_by_close_is_reported_as_interrupted():
    socket = _FakeSocket([
        '{"event":"appendText","text":"half"}',
        WebSocketClosed("closed"),
    ])

    with pytest.raises(ConsumerCopilotError, match="after reply streaming started"):
        _collect(ConsumerCopilotClient(), socket)
