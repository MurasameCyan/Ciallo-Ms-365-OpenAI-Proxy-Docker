"""The consumer transport keeps curl_cffi's Chrome fingerprint end to end."""

import asyncio
import base64
import hashlib
import json
import struct

import pytest
from curl_cffi.curl import CurlError
from curl_cffi.requests import WebSocketError
from curl_cffi.requests.exceptions import RequestException

from m365_copilot_openai_proxy.consumer_client import (
    ClearanceRequired,
    ConsumerCopilotClient,
    ConsumerCopilotError,
)


class _Response:
    def __init__(self, status_code=200, text='{"id":"conversation-1"}'):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


class _FakeSocket:
    def __init__(self, frames=None):
        self.sent = []
        # Every real socket opens with `connected`, and the client waits for it
        # before sending anything -- frames that arrive earlier come back as
        # `error: invalid-event`. Prepending it here keeps these tests about what
        # they are actually testing instead of restating the handshake.
        self.frames = [b'{"event":"connected"}'] + list(frames or [
            b'{"event":"appendText","text":"CURL"}',
            b'{"event":"appendText","text":"-OK"}{"event":"done"}',
        ])

    async def send(self, payload, flags=None):
        self.sent.append(json.loads(payload))

    async def recv(self, *, timeout=None):
        return self.frames.pop(0), 1


class _SocketContext:
    def __init__(self, socket, enter_error=None):
        self.socket = socket
        self.enter_error = enter_error

    async def __aenter__(self):
        if self.enter_error:
            raise self.enter_error
        return self.socket

    async def __aexit__(self, *args):
        return None


class _FakeSession:
    def __init__(
        self, frames=None, enter_error=None, response=None, get_error=None,
    ):
        self.socket = _FakeSocket(frames)
        self.enter_error = enter_error
        self.response = response or _Response()
        self.get_error = get_error
        self.gets = []
        self.posts = []
        self.ws_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        self.gets.append(url)
        if self.get_error:
            raise self.get_error
        return _Response()

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.response

    def ws_connect(self, url, **kwargs):
        self.ws_calls.append((url, kwargs))
        return _SocketContext(self.socket, self.enter_error)


async def _collect(client):
    return "".join([chunk async for chunk in client.chat_stream("say hi")])


def test_curl_transport_uses_one_impersonated_session_for_rest_and_websocket():
    made = []

    sessions = []

    def factory(**kwargs):
        made.append(kwargs)
        session = _FakeSession()
        sessions.append(session)
        return session

    client = ConsumerCopilotClient(
        cookies={"_C_Auth": "live"}, access_token="tok", session_factory=factory,
    )

    assert asyncio.run(_collect(client)) == "CURL-OK"
    assert made == [
        {"impersonate": "firefox147", "cookies": {"_C_Auth": "live"}, "timeout": 90}
    ]
    session = sessions[0]
    assert session.gets == ["https://copilot.microsoft.com/"]
    assert session.posts[0][1]["headers"]["authorization"] == "Bearer tok"
    assert session.ws_calls[0][1]["impersonate"] == "firefox147"
    assert [frame["event"] for frame in session.socket.sent] == [
        "setOptions", "reportLocalConsents", "send",
    ]


def test_websocket_opts_into_draining_frames_queued_at_close():
    # curl_cffi records an exception for every terminal condition, ordinary
    # closure included, and `recv()` fast-fails on it before reading the queue --
    # so without this flag any frame still queued when upstream closes is thrown
    # away (measured on 0.16.0: the queued frame comes back only with it set).
    # That is how the terminal `imageGenerated` can vanish behind two 250-460KB
    # `partialImageGenerated` frames this loop is still parsing.
    sessions = []

    def factory(**kwargs):
        session = _FakeSession()
        sessions.append(session)
        return session

    client = ConsumerCopilotClient(access_token="tok", session_factory=factory)

    assert asyncio.run(_collect(client)) == "CURL-OK"
    assert sessions[0].ws_calls[0][1]["drain_on_error"] is True


def test_send_frame_uses_the_selected_consumer_mode():
    sessions = []

    def factory(**kwargs):
        session = _FakeSession()
        sessions.append(session)
        return session

    client = ConsumerCopilotClient(
        access_token="tok", mode="reasoning", session_factory=factory,
    )

    assert asyncio.run(_collect(client)) == "CURL-OK"
    send_frame = sessions[0].socket.sent[-1]
    assert send_frame["mode"] == "reasoning"
    assert "tone" not in send_frame
    assert "toneId" not in send_frame


def test_event_error_does_not_retry_or_fallback_mode():
    sessions = []
    gate_calls = []

    def factory(**kwargs):
        session = _FakeSession([
            b'{"event":"error","errorCode":"unsupported-mode"}',
        ])
        sessions.append(session)
        return session

    async def gate():
        gate_calls.append(True)
        return {"cookies": {"_C_Auth": "fresh"}}

    client = ConsumerCopilotClient(
        access_token="tok",
        gate=gate,
        mode="reasoning",
        session_factory=factory,
    )

    with pytest.raises(ConsumerCopilotError, match="unsupported-mode"):
        asyncio.run(_collect(client))
    assert len(sessions) == 1
    assert gate_calls == []
    assert sessions[0].socket.sent[-1]["mode"] == "reasoning"


def test_the_error_diagnostic_reports_the_prompt_as_a_length():
    """The frame trace attached to a backend error must not carry the prompt.

    It reaches the client's error body and the server log, and a protocol
    rejection is about the shape of `send`, never about its text.
    """
    def factory(**kwargs):
        return _FakeSession([b'{"event":"error","errorCode":"invalid-event"}'])

    client = ConsumerCopilotClient(access_token="tok", session_factory=factory)

    with pytest.raises(ConsumerCopilotError) as error:
        asyncio.run(_collect(client))
    assert ">send(mode='smart', parts=1, len=6)" in str(error.value)
    assert "say hi" not in str(error.value)


def test_websocket_impersonates_the_browser_that_mints_the_credentials():
    # The credentials are minted by a Firefox (Camoufox) profile, so the replay
    # has to present the same TLS family -- a Chrome handshake is one the account
    # has never been seen behind. This assertion used to be justified as the cure
    # for {"event":"challenge","method":null} (firefox147 4/4 vs chrome146 0/4);
    # that reading was withdrawn once the method turned out to drift on its own
    # and Copilot's own web UI drew the same frame on the same egress. The
    # invariant that survives is the narrower one: follow the minting browser.
    sessions = []

    def factory(**kwargs):
        session = _FakeSession()
        sessions.append(session)
        return session

    client = ConsumerCopilotClient(access_token="tok", session_factory=factory)
    asyncio.run(_collect(client))

    profile = sessions[0].ws_calls[0][1]["impersonate"]
    assert profile.startswith("firefox"), profile


def test_websocket_handshake_sends_the_origin_curl_omits():
    # Browsers always put Origin on the chat-ws upgrade and the server echoes it
    # in Access-Control-Allow-Origin, but curl_cffi's WebSocket handshake leaves
    # it out entirely.
    sessions = []

    def factory(**kwargs):
        session = _FakeSession()
        sessions.append(session)
        return session

    client = ConsumerCopilotClient(access_token="tok", session_factory=factory)
    asyncio.run(_collect(client))

    headers = sessions[0].ws_calls[0][1]["headers"]
    assert headers["Origin"] == "https://copilot.microsoft.com"


def test_explicit_proxy_is_used_for_the_session_and_websocket():
    made = []
    sessions = []

    def factory(**kwargs):
        made.append(kwargs)
        session = _FakeSession()
        sessions.append(session)
        return session

    client = ConsumerCopilotClient(
        access_token="tok",
        proxy="socks5://127.0.0.1:1080",
        session_factory=factory,
    )

    assert asyncio.run(_collect(client)) == "CURL-OK"
    assert made[0]["proxy"] == "socks5://127.0.0.1:1080"
    assert sessions[0].ws_calls[0][1]["proxy"] == "socks5://127.0.0.1:1080"


def test_conversation_403_can_enter_the_browser_gate_recovery_path():
    attempts = 0
    gate_calls = []

    def factory(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _FakeSession(response=_Response(403, "blocked"))
        return _FakeSession()

    async def gate():
        gate_calls.append(True)
        return {"cookies": {"_C_Auth": "fresh"}, "access_token": "new-token"}

    client = ConsumerCopilotClient(gate=gate, session_factory=factory)

    assert asyncio.run(_collect(client)) == "CURL-OK"
    assert attempts == 2
    assert gate_calls == [True]


def test_conversation_401_is_not_misreported_as_a_browser_gate():
    gate_calls = []

    def factory(**kwargs):
        return _FakeSession(response=_Response(401, "unauthorized"))

    async def gate():
        gate_calls.append(True)
        return {}

    client = ConsumerCopilotClient(gate=gate, session_factory=factory)

    with pytest.raises(ConsumerCopilotError, match="HTTP 401"):
        asyncio.run(_collect(client))
    assert gate_calls == []


def test_browser_gate_refreshes_auth_and_retries_one_unstarted_turn():
    attempts = []
    sessions = []
    gate_calls = []

    def factory(**kwargs):
        attempts.append(kwargs)
        session = (
            _FakeSession([b'{"event":"challenge","method":"hashcash","parameter":"broken"}'])
            if len(attempts) == 1
            else _FakeSession()
        )
        sessions.append(session)
        return session

    async def gate():
        gate_calls.append(True)
        return {
            "cookies": {"_C_Auth": "fresh"},
            "access_token": "new-token",
            "identity_type": "MicrosoftAccount",
        }

    client = ConsumerCopilotClient(
        cookies={"_C_Auth": "stale"},
        access_token="old-token",
        gate=gate,
        session_factory=factory,
        mode="reasoning",
    )

    assert asyncio.run(_collect(client)) == "CURL-OK"
    assert gate_calls == [True]
    assert len(attempts) == 2
    assert attempts[1]["cookies"] == {"_C_Auth": "fresh"}
    assert [session.socket.sent[-1]["mode"] for session in sessions] == [
        "reasoning",
        "reasoning",
    ]
    assert "accessToken=new-token" in client._ws_url()
    assert "X-UserIdentityType=MicrosoftAccount" in client._ws_url()


def test_an_empty_text_frame_does_not_spend_the_one_browser_gate_retry():
    """A zero-length appendText must not count as output.

    Upstream sometimes opens a turn with an empty appendText and only then
    demands clearance. That frame yields "" -- nothing a client can see -- so
    treating it as "already emitted" burned the single mid-request re-mint and
    let the raw challenge escape, which is what made an expired clearance
    unrecoverable without operator action.
    """
    attempts = []
    gate_calls = []

    def factory(**kwargs):
        attempts.append(kwargs)
        return (
            _FakeSession(
                [
                    b'{"event":"appendText","text":""}',
                    b'{"event":"challenge","method":"hashcash","parameter":"broken"}',
                ]
            )
            if len(attempts) == 1
            else _FakeSession()
        )

    async def gate():
        gate_calls.append(True)
        return {"cookies": {"_C_Auth": "fresh"}, "access_token": "new-token"}

    client = ConsumerCopilotClient(gate=gate, session_factory=factory)

    assert asyncio.run(_collect(client)) == "CURL-OK"
    assert gate_calls == [True]
    assert len(attempts) == 2


def test_real_text_before_a_challenge_still_suppresses_the_gate():
    """Retrying after visible output would duplicate it, so the gate stays shut."""
    gate_calls = []

    def factory(**kwargs):
        return _FakeSession(
            [
                b'{"event":"appendText","text":"partial"}',
                b'{"event":"challenge","method":"hashcash","parameter":"broken"}',
            ]
        )

    async def gate():
        gate_calls.append(True)
        return {"cookies": {"_C_Auth": "fresh"}}

    client = ConsumerCopilotClient(gate=gate, session_factory=factory)

    with pytest.raises(ClearanceRequired):
        asyncio.run(_collect(client))
    assert gate_calls == []


def test_browser_gate_is_attempted_only_once():
    attempts = 0
    gate_calls = []

    def factory(**kwargs):
        nonlocal attempts
        attempts += 1
        return _FakeSession([b'{"event":"challenge","method":"hashcash","parameter":"broken"}'])

    async def gate():
        gate_calls.append(True)
        return {"cookies": {"_C_Auth": "still-gated"}}

    client = ConsumerCopilotClient(gate=gate, session_factory=factory)

    try:
        asyncio.run(_collect(client))
    except ClearanceRequired:
        pass
    else:
        raise AssertionError("the second challenge must escape")
    assert attempts == 2
    assert gate_calls == [True]


def test_gate_retry_discards_a_preexisting_blocked_conversation_id():
    attempts = []

    def factory(**kwargs):
        session = _FakeSession(
            [b'{"event":"challenge","method":"hashcash","parameter":"broken"}']
            if not attempts else None
        )
        attempts.append(session)
        return session

    async def gate():
        return {"cookies": {"_C_Auth": "fresh"}}

    client = ConsumerCopilotClient(gate=gate, session_factory=factory)

    assert asyncio.run(client.chat("say hi", conversation_id="blocked-id")) == "CURL-OK"
    assert attempts[0].posts == []
    assert len(attempts[1].posts) == 1
    second_send = attempts[1].socket.sent[-1]
    assert second_send["conversationId"] == "conversation-1"


def test_browser_gate_never_replays_after_a_chunk_was_emitted():
    attempts = 0
    gate_calls = []

    def factory(**kwargs):
        nonlocal attempts
        attempts += 1
        return _FakeSession([
            b'{"event":"appendText","text":"half"}',
            b'{"event":"challenge","method":"hashcash","parameter":"broken"}',
        ])

    async def gate():
        gate_calls.append(True)
        return {"cookies": {"_C_Auth": "fresh"}}

    client = ConsumerCopilotClient(gate=gate, session_factory=factory)

    try:
        asyncio.run(_collect(client))
    except ClearanceRequired:
        pass
    else:
        raise AssertionError("a streamed turn must fail instead of replaying")
    assert attempts == 1
    assert gate_calls == []


def test_http_transport_error_is_wrapped_for_route_callers():
    def factory(**kwargs):
        return _FakeSession(get_error=RequestException("landing failed"))

    client = ConsumerCopilotClient(session_factory=factory)

    with pytest.raises(ConsumerCopilotError, match="HTTP transport.*landing failed") as error:
        asyncio.run(_collect(client))
    assert isinstance(error.value.__cause__, RequestException)


@pytest.mark.parametrize(
    "transport_error",
    [WebSocketError("upgrade rejected"), CurlError("connection failed", 7)],
)
def test_websocket_upgrade_error_is_wrapped_for_route_callers(transport_error):
    def factory(**kwargs):
        return _FakeSession(enter_error=transport_error)

    client = ConsumerCopilotClient(access_token="tok", session_factory=factory)

    with pytest.raises(ConsumerCopilotError, match="refused") as error:
        asyncio.run(_collect(client))
    assert error.value.__cause__ is transport_error


def _ws_frame(payload: bytes) -> bytes:
    """Server->client text frame, unmasked."""
    n = len(payload)
    if n < 126:
        return struct.pack("!BB", 0x81, n) + payload
    if n < 65536:
        return struct.pack("!BBH", 0x81, 126, n) + payload
    return struct.pack("!BBQ", 0x81, 127, n) + payload


async def _serve_then_cut(reader, writer) -> None:
    """Answer the upgrade, queue the measured image shape, then bare-FIN close."""
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = await reader.read(4096)
        if not chunk:
            return
        request += chunk
    key = b""
    for line in request.split(b"\r\n"):
        if line.lower().startswith(b"sec-websocket-key:"):
            key = line.split(b":", 1)[1].strip()
    accept = base64.b64encode(
        hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
    )
    writer.write(
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n"
    )
    await writer.drain()

    # Two big partials ahead of the small terminal frame, then EOF with no close
    # frame -- the shape live image turns die of.
    big = base64.b64encode(b"\xff" * 260_000).decode()
    for payload in (
        {"event": "partialImageGenerated", "content": big},
        {"event": "partialImageGenerated", "content": big},
        {"event": "imageGenerated", "url": "https://example.invalid/final.png"},
    ):
        writer.write(_ws_frame(json.dumps(payload).encode()))
    await writer.drain()
    writer.close()


@pytest.mark.parametrize("drain,expected", [
    (False, []),
    (True, ["partialImageGenerated", "partialImageGenerated", "imageGenerated"]),
])
def test_drain_on_error_is_what_recovers_frames_queued_at_a_bare_eof(drain, expected):
    """Pins curl_cffi's semantics, not our own code: the flag is the only reason
    frames already sitting in the receive queue survive an EOF close. Without it
    every queued frame is discarded -- the terminal `imageGenerated` and the
    partials with it -- because `recv()` raises the recorded exception before it
    reads the queue. A test that only asserts we pass the kwarg would keep
    passing if a curl_cffi upgrade changed that behaviour, and the pin allows
    anything under 1.0.0.
    """

    async def run():
        from curl_cffi.requests import AsyncSession

        server = await asyncio.start_server(_serve_then_cut, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        events = []
        async with server:
            async with AsyncSession() as session:
                async with session.ws_connect(
                    f"ws://127.0.0.1:{port}/", drain_on_error=drain
                ) as ws:
                    # Let the reader task record the EOF first: that is the
                    # "loop is behind two 350KB frames" condition, made
                    # deterministic.
                    await asyncio.sleep(0.6)
                    while True:
                        try:
                            raw, _flags = await ws.recv(timeout=5)
                        except WebSocketError:
                            return events
                        events.append(json.loads(raw.decode())["event"])

    events = asyncio.run(run())

    assert events == expected
