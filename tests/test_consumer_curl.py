"""The consumer transport keeps curl_cffi's Chrome fingerprint end to end."""

import asyncio
import json

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
        self.frames = list(frames or [
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


def test_websocket_avoids_the_tls_profiles_copilot_challenges():
    # Copilot fingerprints the TLS client when `send` arrives: every Chrome,
    # Edge and Safari profile draws {"event":"challenge","method":null} while
    # firefox147 gets a normal reply (measured 4/4 vs 0/4, alternating, on one
    # set of credentials). A Chrome-family profile here is a silent outage --
    # the transport connects, then every turn dies on the challenge.
    sessions = []

    def factory(**kwargs):
        session = _FakeSession()
        sessions.append(session)
        return session

    client = ConsumerCopilotClient(access_token="tok", session_factory=factory)
    asyncio.run(_collect(client))

    profile = sessions[0].ws_calls[0][1]["impersonate"]
    assert not profile.startswith(("chrome", "edge", "safari")), profile


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
            _FakeSession([b'{"event":"challenge","method":null}'])
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
                    b'{"event":"challenge","method":null}',
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
                b'{"event":"challenge","method":null}',
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
        return _FakeSession([b'{"event":"challenge","method":null}'])

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
            [b'{"event":"challenge","method":null}']
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
            b'{"event":"challenge","method":null}',
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
