"""Unit tests for the consumer-Copilot protocol helpers.

Covers the two pieces that fail silently if wrong: the proof-of-work solvers
(a bad nonce stalls the socket until the idle timeout) and the frame splitter
(Copilot packs several JSON objects into one WS frame).
"""

import asyncio
import hashlib
import json
import threading
from datetime import datetime, timezone

import pytest

from curl_cffi.requests import WebSocketClosed, WebSocketError, WebSocketTimeout

from m365_copilot_openai_proxy.consumer_client import (
    AccountThrottled,
    ClearanceRequired,
    ConsumerCopilotClient,
    ConsumerCopilotError,
    RegionBlocked,
    TurnRefused,
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
    {"method": "cloudflare", "parameter": "x"},
    {"method": "some-new-pow", "parameter": "x"},
    {"method": "hashcash"},  # no parameter -> unsolvable, not a crash
])
def test_browser_only_challenges_return_none(msg):
    # None tells the reader that this frame has no valid challenge response.
    assert solve_challenge(msg) is None


@pytest.mark.parametrize("msg", [
    {"method": None, "parameter": None},
    {},
    {"id": "0.0001"},
])
def test_empty_challenge_has_no_token_the_client_can_send(msg):
    """The frame discloses no proof method and therefore has no valid response.

    An empty token drew ``invalid-event`` online. The frame alone does not reveal
    why this connection received it, so the client must stop without replying or
    automatically re-minting credentials.
    """
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
    assert [m.get("event") for m in socket.sent] == [
        "setOptions", "reportLocalConsents", "send",  # opened by `connected`
        "challengeResponse", "send",  # a real challenge held the send back
    ]
    assert socket.sent[3]["id"] == "0.1"  # the backend correlates on the id


def test_nothing_is_sent_before_the_connected_frame():
    """The backend speaks first; a frame that beats `connected` is answered with
    `error: invalid-event`. curl_cffi's ws_connect returns a full round trip
    before `connected` arrives, so opening the turn from there loses every
    time."""
    socket = _FakeSocket([
        '{"event":"appendText","text":"hi"}{"event":"done"}',
    ])
    assert _collect(ConsumerCopilotClient(), socket) == "hi"
    assert socket.sent == []


def test_a_second_connected_frame_does_not_replay_the_handshake():
    """A live socket sends `connected` twice (captured from the real page). A
    replayed burst is a duplicate `send` on a live turn, which the backend
    rejects with `invalid-event`."""
    socket = _FakeSocket([
        '{"event":"connected"}{"event":"connected"}',
        '{"event":"appendText","text":"hi"}{"event":"done"}',
    ])
    assert _collect(ConsumerCopilotClient(), socket) == "hi"
    assert [m.get("event") for m in socket.sent] == [
        "setOptions", "reportLocalConsents", "send",
    ]


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


def test_unknown_challenge_after_a_solved_pow_is_still_refused():
    # The regression this guards: gating the refusal check behind `answered`
    # swallows the frame and the turn dies at the idle timeout instead.
    socket = _FakeSocket([
        '{"event":"challenge","method":"hashcash","parameter":"s:0","id":"0.1"}',
        '{"event":"challenge","method":"cloudflare","parameter":"x","id":"0.2"}',
    ])
    with pytest.raises(TurnRefused):
        _collect(ConsumerCopilotClient(), socket)


def test_an_empty_challenge_refuses_without_answering_or_reminting():
    """A method-less challenge has no valid response. By itself it does not
    identify quota, egress, credentials, or client fingerprint."""
    socket = _FakeSocket([
        '{"event":"connected"}{"event":"challenge","id":"0.0001"}',
    ])
    with pytest.raises(TurnRefused, match="method=None") as error:
        _collect(ConsumerCopilotClient(), socket)
    assert [m.get("event") for m in socket.sent] == [
        "setOptions", "reportLocalConsents", "send",
    ]
    assert ">send(mode=" in str(error.value)


def test_throttled_message_wins_over_a_later_empty_challenge():
    """The actionable quota error must win over a later method-less challenge."""
    socket = _FakeSocket([
        '{"event":"chatMessageError","errorCode":"throttled",'
        '"errorDetail":{"type":"throttled",'
        '"nextAvailableAt":"2026-08-13T15:17:13+00:00"}}'
        '{"event":"challenge","method":null,"parameter":null,"id":"0.0002"}',
    ])
    with pytest.raises(AccountThrottled) as error:
        _collect(ConsumerCopilotClient(), socket)
    assert error.value.next_available_at == "2026-08-13T15:17:13+00:00"
    assert error.value.retry_after_seconds(
        datetime(2026, 8, 13, 15, 17, 2, 900_000, tzinfo=timezone.utc)
    ) == 11
    assert '<{"event": "challenge"' not in str(error.value)


def test_throttle_retry_after_is_zero_once_the_reset_time_passes():
    error = AccountThrottled("quota", "2026-08-13T15:17:13+00:00")
    assert error.retry_after_seconds(
        datetime(2026, 8, 13, 15, 17, 14, tzinfo=timezone.utc)
    ) == 0


def test_the_handshake_advertises_the_image_capability():
    # Measured on live turns: these lists do not gate image generation -- the
    # backend sends generatingImage and the base64 partials with empty lists too.
    # They are pinned because every reference client sends them and the terminal
    # `imageGenerated` url is a card, so a "text-only bridge needs no lists"
    # cleanup should be a deliberate decision rather than a silent one.
    socket = _FakeSocket([
        '{"event":"connected"}',
        '{"event":"appendText","text":"hi"}{"event":"done"}',
    ])
    _collect(ConsumerCopilotClient(), socket)

    options = socket.sent[0]
    assert options["event"] == "setOptions"
    assert "partial-generated-images" in options["supportedFeatures"]
    assert "image" in options["supportedCards"]


def test_a_socket_cut_after_the_partial_images_still_delivers_the_image():
    # The live failure shape: upstream streams the finished JPEG as progressive
    # base64, then cuts the connection (bare EOF) before the terminal
    # `imageGenerated` url -- 6 of 7 real turns on 2026-08-23. The image is
    # already in hand, so the turn has to end with an image rather than an error.
    socket = _FakeSocket([
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"/9j/rough"}',
        '{"event":"partialImageGenerated","content":"/9j/sharper"}',
        WebSocketClosed("closed"),
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    # The last partial wins: they are the same image at rising quality.
    assert reply.strip() == "![a red apple](data:image/jpeg;base64,/9j/sharper)"


def test_text_before_the_image_does_not_forfeit_the_image_on_a_cut():
    # Upstream usually writes a line before it draws, so gating the fallback on
    # "nothing streamed yet" forfeited the picture on exactly the common turns --
    # with the finished JPEG already in hand.
    socket = _FakeSocket([
        '{"event":"appendText","text":"Sure, here it is."}',
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"/9j/final"}',
        WebSocketClosed("closed"),
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert "Sure, here it is." in reply
    assert "![a red apple](data:image/jpeg;base64,/9j/final)" in reply


@pytest.mark.parametrize("death", [
    WebSocketTimeout("timed out"),
    WebSocketError("recv failed"),
])
def test_any_socket_death_after_the_partial_images_still_delivers_the_image(death):
    # A bare EOF is only the shape measured most often. Upstream also just goes
    # quiet (WebSocketTimeout) and resets the connection (WebSocketError), and a
    # picture already in hand has to survive all three -- catching only the close
    # threw it away on the other two.
    socket = _FakeSocket([
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"/9j/final"}',
        death,
    ])

    reply = _collect(ConsumerCopilotClient(idle_timeout=3), socket)

    assert reply.strip() == "![a red apple](data:image/jpeg;base64,/9j/final)"


def test_a_delivered_url_ends_the_turn_and_is_not_also_sent_as_base64():
    # The shape `drain_on_error` makes ordinary: the terminal frame comes out of
    # curl_cffi's queue and the recorded close lands right behind it. An image
    # turn may end with either that bare close or a polite `done`, so the close
    # is an ending here rather than a failure --
    # raising here reported a complete turn as failed, and on the non-streaming
    # path that discards the reply and loses the image just delivered. The
    # terminal frame also clears the buffered partial, so the fallback cannot
    # append half a megabyte of duplicate for an image already sent by url.
    socket = _FakeSocket([
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"/9j/rough"}',
        '{"event":"imageGenerated","url":"https://example.invalid/final.png"}',
        WebSocketClosed("closed"),
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert reply.strip() == "![a red apple](https://example.invalid/final.png)"
    assert "data:image" not in reply


def test_a_polite_done_after_the_partial_images_still_delivers_the_image():
    # The other way an image turn ends. The cut branch already flushed the
    # buffered JPEG, but `done` returned immediately -- so a turn that had the
    # finished picture in hand reached the client as an empty reply purely
    # because upstream ended politely instead of dropping the socket.
    socket = _FakeSocket([
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"/9j/rough"}',
        '{"event":"partialImageGenerated","content":"/9j/sharper"}',
        '{"event":"done"}',
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert reply.strip() == "![a red apple](data:image/jpeg;base64,/9j/sharper)"


def test_text_before_the_image_keeps_both_when_the_turn_ends_politely():
    # Same common shape as the cut case: upstream writes a line before drawing.
    socket = _FakeSocket([
        '{"event":"appendText","text":"Sure, here it is."}',
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"/9j/final"}',
        '{"event":"done"}',
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert "Sure, here it is." in reply
    assert "![a red apple](data:image/jpeg;base64,/9j/final)" in reply


def test_a_url_delivered_before_done_is_not_also_repeated_as_base64():
    # The terminal `imageGenerated` clears the buffer, so the `done` flush must
    # not append half a megabyte of duplicate for an image already sent by url.
    socket = _FakeSocket([
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"/9j/rough"}',
        '{"event":"imageGenerated","url":"https://example.invalid/final.png"}',
        '{"event":"done"}',
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert reply.strip() == "![a red apple](https://example.invalid/final.png)"
    assert "data:image" not in reply


def test_a_plain_text_turn_ending_in_done_gains_no_image():
    # The flush is gated on a buffered partial, so ordinary text turns -- the
    # overwhelming majority -- must be untouched by it.
    socket = _FakeSocket([
        '{"event":"appendText","text":"Four."}',
        '{"event":"done"}',
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert reply.strip() == "Four."
    assert "![" not in reply


def test_a_png_partial_flushed_on_done_keeps_its_own_mime_type():
    # The mime sniff lives in the shared helper now; both endings must agree,
    # or a PNG delivered by `done` would reach the client labelled jpeg.
    socket = _FakeSocket([
        '{"event":"generatingImage","prompt":"a red apple"}',
        '{"event":"partialImageGenerated","content":"iVBORw0KGgo"}',
        '{"event":"done"}',
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert reply.strip() == "![a red apple](data:image/png;base64,iVBORw0KGgo)"


def test_a_cut_with_no_image_reports_the_failure_without_quoting_the_payload():
    # `last frame was <repr>` used to inline the whole frame, which for a
    # half-megabyte base64 partial reached the client as an unreadable wall.
    socket = _FakeSocket([
        '{"event":"unknownBulkFrame","blob":"' + "A" * 5000 + '"}',
        WebSocketClosed("closed"),
    ])

    with pytest.raises(ConsumerCopilotError, match="closed without replying") as caught:
        _collect(ConsumerCopilotClient(), socket)

    assert len(str(caught.value)) < 1500


def test_generated_image_is_emitted_as_markdown_with_the_prompt_as_alt_text():
    # Frame order and payload keys are a capture from a real consumer turn
    # (generatingImage carries the prompt, imageGenerated the finished url;
    # partialImageGenerated is progress noise and must not reach the client).
    socket = _FakeSocket([
        '{"event":"generatingImage","prompt":"a red circle"}',
        '{"event":"partialImageGenerated","url":"https://example.invalid/partial.png"}',
        '{"event":"imageGenerated","url":"https://example.invalid/final.png",'
        '"thumbnailUrl":"https://example.invalid/thumb.png"}',
        '{"event":"appendText","text":"Here it is."}{"event":"done"}',
    ])

    reply = _collect(ConsumerCopilotClient(), socket)

    assert "![a red circle](https://example.invalid/final.png)" in reply
    assert "Here it is." in reply
    assert "partial.png" not in reply


def test_generated_image_without_a_preceding_prompt_still_renders():
    socket = _FakeSocket([
        '{"event":"imageGenerated","url":"https://example.invalid/final.png"}',
        '{"event":"done"}',
    ])

    assert "![image](https://example.invalid/final.png)" in _collect(
        ConsumerCopilotClient(), socket
    )


def test_image_only_reply_is_a_complete_turn():
    # An image with no accompanying text is the whole deliverable, so the close
    # that follows ends the turn. A text stream cut short still raises -- see
    # test_partial_reply_followed_by_close_is_reported_as_interrupted, which is
    # what keeps the "interrupted, not never replied" wording honest.
    socket = _FakeSocket([
        '{"event":"imageGenerated","url":"https://example.invalid/final.png"}',
        WebSocketClosed("closed"),
    ])

    assert "![image](https://example.invalid/final.png)" in _collect(
        ConsumerCopilotClient(), socket
    )


def test_chat_service_unavailable_is_a_typed_region_error():
    socket = _FakeSocket(['{"event":"error","errorCode":"chat-service-unavailable"}'])
    with pytest.raises(RegionBlocked, match="anonymous"):
        _collect(ConsumerCopilotClient(), socket)


def test_backend_error_names_the_exchange_that_produced_it():
    """`invalid-event` identifies no offending frame, and the same opaque code
    covers a wrong handshake order, a duplicate `send` and a malformed frame
    shape. Only the interleaved exchange says which frame drew it."""
    socket = _FakeSocket([
        '{"event":"connected"}',
        '{"event":"challenge","method":"hashcash","parameter":"s:0","id":"0.1"}',
        '{"event":"error","errorCode":"invalid-event"}',
    ])

    with pytest.raises(ConsumerCopilotError) as error:
        _collect(ConsumerCopilotClient(), socket)
    message = str(error.value)
    assert '<{"event": "connected"}' in message
    assert '>{"event": "setOptions"' in message
    assert ">send(mode=" in message
    # Shapes, not just names: whether the backend rejected the frame's *shape*
    # cannot be read off an event name, so the trace keeps the payload verbatim.
    assert (
        '>{"event": "challengeResponse", "token": "0", "method": "hashcash", '
        '"id": "0.1"}'
    ) in message
    assert message.index(">send(") < message.index('>{"event": "challengeResponse"')
    assert message.endswith('<{"event": "error", "errorCode": "invalid-event"}')


def test_the_error_trace_keeps_message_text_out_of_the_diagnostic():
    # The trace lands in logs and in the client's error body. The frames that
    # matter carry no text, so content is reduced to a count.
    socket = _FakeSocket([
        '{"event":"connected"}{"event":"appendText","text":"secret reply"}',
        '{"event":"error","errorCode":"invalid-event"}',
    ])

    with pytest.raises(ConsumerCopilotError) as error:
        _collect(ConsumerCopilotClient(), socket)
    assert "<appendText(len=12)" in str(error.value)
    assert "secret" not in str(error.value)


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
