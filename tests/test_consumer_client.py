"""Unit tests for the consumer-Copilot protocol helpers.

Covers the two pieces that fail silently if wrong: the proof-of-work solvers
(a bad nonce stalls the socket until the idle timeout) and the frame splitter
(Copilot packs several JSON objects into one WS frame).
"""

import asyncio
import hashlib
import json

import httpx
import pytest

from m365_copilot_openai_proxy.consumer_client import (
    ClearanceRequired,
    ConsumerCopilotClient,
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


def test_rest_headers_carry_the_bearer_token_but_the_socket_ones_do_not():
    # Measured by replaying the page's own request: cookies alone answer 403 on
    # /c/api/conversations, and the same headers plus Authorization answer 200.
    # The socket must NOT get the header -- it authenticates by query param.
    client = ConsumerCopilotClient(access_token="tok")
    assert client._headers(authorize=True)["authorization"] == "Bearer tok"
    assert "authorization" not in client._headers()


def test_anonymous_rest_headers_omit_an_empty_bearer():
    # "Bearer " with no token is worse than no header: it reads as a malformed
    # credential rather than an absent one.
    assert "authorization" not in ConsumerCopilotClient()._headers(authorize=True)


def _jar_with(entries):
    cookies = httpx.Cookies()
    for name, value, domain in entries:
        cookies.set(name, value, domain=domain, path="/")
    return cookies


def test_absorb_cookies_survives_one_name_on_two_domains():
    # The regression this guards: dict(httpx.Cookies) raises CookieConflict, and
    # every signed-in turn hits it -- injected cookies go in domain-less while
    # the server's Set-Cookie carries a domain.
    client = ConsumerCopilotClient(cookies={"_C_Auth": "live"})
    client._absorb_cookies(_jar_with([
        ("_C_Auth", "live", ""),
        ("_C_Auth", "fresh", "copilot.microsoft.com"),
        ("__cf_bm", "clearance", ".copilot.microsoft.com"),
    ]))
    assert client._cookies["__cf_bm"] == "clearance"  # the point of the merge


def test_absorb_cookies_does_not_let_a_cleared_value_wipe_a_live_one():
    # The landing page answers anonymous requests with a blank _C_Auth; adopting
    # it would log the session out mid-turn.
    client = ConsumerCopilotClient(cookies={"_C_Auth": "live"})
    client._absorb_cookies(_jar_with([("_C_Auth", "", "copilot.microsoft.com")]))
    assert client._cookies["_C_Auth"] == "live"


class _FakeSocket:
    """Minimal websockets stand-in: replays frames, records what we sent."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    async def recv(self):
        if not self._frames:
            raise AssertionError("stream read past the scripted frames")
        return self._frames.pop(0)


async def _read(client, socket) -> str:
    return "".join([chunk async for chunk in client._read_stream(socket, '{"event":"send"}')])


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


def test_apply_session_keeps_the_token_a_tokenless_harvest_did_not_carry():
    # A harvest can earn fresh clearance without ever seeing a chat socket, so it
    # comes back tokenless. Overwriting the live token would turn a solved gate
    # into a 401 on the very next turn.
    client = ConsumerCopilotClient(cookies={"_C_Auth": "live"}, access_token="tok")
    client.apply_session({"cookies": {"cf_clearance": "fresh", "_C_Auth": ""}, "access_token": ""})
    assert client._token == "tok"
    assert client._cookies == {"_C_Auth": "live", "cf_clearance": "fresh"}


def _scripted_client(attempts, session):
    """Client whose ``_chat_once`` replays ``attempts`` (chunk list or exception).

    Records what each attempt saw, so a test can assert the retry ran against the
    refreshed session rather than the stale one.
    """
    seen = []
    refreshed = []

    async def _refresh():
        refreshed.append(True)
        return session

    client = ConsumerCopilotClient(cookies={"a": "1"}, refresh_clearance=_refresh)

    async def _fake_once(prompt, conversation_id=""):
        seen.append((conversation_id, dict(client._cookies)))
        step = attempts.pop(0)
        if isinstance(step, Exception):
            raise step
        for chunk in step:
            yield chunk

    client._chat_once = _fake_once
    return client, seen, refreshed


def _drain(client, prompt="hi", conversation_id="old-convo"):
    async def _run():
        return [chunk async for chunk in client.chat_stream(prompt, conversation_id)]
    return asyncio.run(_run())


def test_a_gated_turn_is_replayed_against_the_refreshed_session():
    client, seen, refreshed = _scripted_client(
        [ClearanceRequired("gated"), ["hi"]],
        {"earned": True, "cookies": {"cf_clearance": "fresh"}},
    )
    assert _drain(client) == ["hi"]
    assert refreshed == [True]
    # The retry must start a new conversation: the old id belongs to the session
    # that was refused, and it carries the clearance it just earned.
    assert seen[1][0] == ""
    assert seen[1][1]["cf_clearance"] == "fresh"


def test_a_turn_that_already_streamed_is_not_replayed():
    # The regression this guards: replaying a half-streamed turn emits the answer
    # twice, which is exactly the duplicate-reply bug fixed on the M365 side.
    async def _partial(prompt, conversation_id=""):
        yield "half an answer"
        raise ClearanceRequired("gated mid-turn")

    client, _, refreshed = _scripted_client([], {"earned": True})
    client._chat_once = _partial
    with pytest.raises(ClearanceRequired):
        _drain(client)
    assert refreshed == []


def test_an_unearned_harvest_raises_instead_of_retrying_into_the_same_wall():
    client, seen, _ = _scripted_client(
        [ClearanceRequired("gated")], {"earned": False, "cookies": {"a": "1"}}
    )
    with pytest.raises(ClearanceRequired, match="residential proxy"):
        _drain(client)
    assert len(seen) == 1


def test_without_a_refresh_hook_the_gate_propagates_untouched():
    client = ConsumerCopilotClient()

    async def _gated(prompt, conversation_id=""):
        raise ClearanceRequired("gated")
        yield  # pragma: no cover - makes this an async generator

    client._chat_once = _gated
    with pytest.raises(ClearanceRequired, match="^gated$"):
        _drain(client)
