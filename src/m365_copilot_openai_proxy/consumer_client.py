"""Consumer (personal-account) Copilot chat client.

Consumer Copilot uses a different protocol from M365 Substrate: it creates a
conversation over REST, then sends a two-frame handshake and the turn over a
WebSocket. Cloudflare fingerprints both connections, so they must share one
curl_cffi session impersonating Chrome; plain httpx/websockets are rejected even
when they replay the same browser cookies and ChatAI access token.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import quote

from curl_cffi.curl import CurlError
from curl_cffi.requests import (
    AsyncSession,
    CurlWsFlag,
    WebSocketClosed,
    WebSocketError,
    WebSocketTimeout,
)
from curl_cffi.requests.exceptions import RequestException

BASE_URL = "https://copilot.microsoft.com"
CHAT_WEBSOCKET_URL = f"{BASE_URL.replace('https', 'wss')}/c/api/chat?api-version=2"
CONVERSATION_URL = f"{BASE_URL}/c/api/conversations"

# The lists advertise what a UI could render. Text-only bridge traffic does not
# need them; port the full browser list only if Microsoft starts gating features.
SET_OPTIONS_FRAME = {
    "event": "setOptions",
    "supportedFeatures": [],
    "supportedCards": [],
    "supportedUIComponents": {},
    "ads": {"supportedTypes": []},
    "supportedActions": [],
}
CONSENTS_FRAME = {"event": "reportLocalConsents", "grantedConsents": []}

# Copilot fingerprints the TLS client when a `send` frame arrives, and every
# Chrome/Edge/Safari profile curl_cffi offers answers with
# {"event":"challenge","method":null} -- a verdict, not a solvable puzzle. Under
# firefox147 the identical turn is answered normally. Measured on one set of
# credentials, alternating profiles: firefox147 4/4 replied, chrome146 0/4.
# Nothing above the TLS layer distinguishes the two: handshake headers, cookies,
# conversation provenance, and frame payloads were all matched against a real
# browser's capture first, and a bare WebSocket opened from page JS -- no SPA
# logic, our own frames -- replies fine, so this is the stack, not the protocol.
#
# 2026-08-12, from the deployed VPS (Oracle Cloud Tokyo, colo NRT), that no
# longer reproduces: firefox147/144/135 and chrome146 are all challenged within
# 0.4s on fresh credentials, and alternating firefox147/chrome146 six times is
# 6/6 challenged. So the profile is no longer the discriminant -- whatever score
# this egress carries, no profile curl_cffi offers clears it. Keeping firefox147
# because it is the closest match to the Firefox that mints the credentials.
_IMPERSONATE = "firefox147"

# curl_cffi's WebSocket handshake omits Origin; browsers always send it, and the
# server echoes it back in Access-Control-Allow-Origin.
_WS_HEADERS = {"Origin": BASE_URL}

_IDLE_TIMEOUT = 60.0
_REQUEST_TIMEOUT = 90.0
_MAX_HASHCASH_DIFFICULTY = 22
_MAX_HASHCASH_NONCE = 1 << 25
_DECODER = json.JSONDecoder()

# How many frames of the exchange to keep for the diagnostic that accompanies a
# backend `error` frame. `invalid-event` names no offending frame, so the frame
# that drew it can only be identified from what was in flight around it -- which
# needs both directions, in order, hence one interleaved trace. The oldest frames
# are the ones kept: a handshake rejection lands within the first few.
_TRACE_LIMIT = 16


def _frame_note(message: dict) -> str:
    """Compact one frame, either direction, for an error trace.

    Everything but message text is kept verbatim, because a protocol rejection is
    about frame shape -- an explicit ``"method": null`` and an absent ``method``
    are different frames, and the trace is useless if it cannot tell them apart.
    Text is reduced to a length instead: it is bulky, it is the user's content,
    and no protocol error is ever about what was said.
    """
    event = message.get("event") or message.get("type") or "(none)"
    if event in ("appendText", "appendTextSuggestion"):
        return f"{event}(len={len(message.get('text') or '')})"
    if event == "send":
        parts = message.get("content") or []
        return (
            f"send(mode={message.get('mode')!r}, parts={len(parts)}, "
            f"len={sum(len(part.get('text') or '') for part in parts)})"
        )
    dumped = json.dumps(message, ensure_ascii=False)
    return dumped if len(dumped) <= 400 else dumped[:400] + "...}"


def _trace_suffix(trace: list[str]) -> str:
    return f" frames: {' '.join(trace)}" if trace else ""


class ConsumerCopilotError(RuntimeError):
    """The consumer chat backend refused or failed a turn."""


class ClearanceRequired(ConsumerCopilotError):
    """Copilot demanded an interactive Cloudflare verification."""


class RegionBlocked(ConsumerCopilotError):
    """The consumer backend refused this account or egress region."""


def solve_hashcash(parameter: str) -> str:
    """Return the smallest nonce satisfying the requested SHA-256 difficulty."""
    seed, diff = parameter.rsplit(":", 1)
    difficulty = int(diff)
    if not 0 <= difficulty <= _MAX_HASHCASH_DIFFICULTY:
        raise ValueError(
            f"Hashcash difficulty must be between 0 and "
            f"{_MAX_HASHCASH_DIFFICULTY}."
        )
    full, rem = difficulty // 8, difficulty % 8
    mask = (255 << (8 - rem)) & 0xFF if rem else 0
    for nonce in range(_MAX_HASHCASH_NONCE):
        digest = hashlib.sha256(f"{seed}{nonce}".encode()).digest()
        if not any(digest[:full]) and (not rem or not digest[full] & mask):
            return str(nonce)
    raise ValueError("Hashcash nonce search exceeded its safety budget.")


def solve_copilot_challenge(parameter: str) -> str:
    """Solve Copilot's arithmetic proof-of-work variant."""
    value = float(parameter)
    return str(int(math.floor(((value**3 / 100 + value * 25) % 22) + 0.5)))


def solve_challenge(message: dict) -> str | None:
    """Return a proof-of-work token, or ``None`` when no token can pass."""
    method, parameter = message.get("method"), message.get("parameter")
    if method == "hashcash" and parameter:
        return solve_hashcash(parameter)
    if method == "copilot" and parameter:
        return solve_copilot_challenge(parameter)
    # Everything else -- including the empty challenge that carries neither a
    # method nor a parameter -- is Cloudflare's verdict on the client that sent
    # the `send` frame, not a puzzle. All three answers were tried against the
    # live backend before this one settled:
    #
    #   empty token   -> `error: invalid-event` (the frame shape is refused)
    #   no frame      -> backend closed the socket without replying, 3/3
    #   None (here)   -> ClearanceRequired, so chat_stream re-mints once
    #
    # It is a verdict on the stack rather than on the turn, which is why it never
    # coexists with a reply. What it tracks is the egress and the client stack
    # together, measured 2026-08-12 on the deployed VPS with one set of
    # credentials:
    #
    #                        Oracle Tokyo (direct)   authenticated FR proxy
    #   curl_cffi, 4 profiles   method=null            method=null
    #   real Firefox, our frames method=null           method=hashcash
    #
    # So the credentials are not the variable: a re-mint one minute earlier draws
    # it again, and `POST /c/api/conversations` answers 200 throughout. Answering
    # the hashcash the browser does get is the open question -- the frame after
    # our `challengeResponse` plus replayed `send` was `method=null` again.
    return None


def drain_json(raw: str | bytes) -> list[dict]:
    """Split one WebSocket message into its concatenated JSON objects."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    messages: list[dict] = []
    index, length = 0, len(raw)
    while index < length:
        while index < length and raw[index] in " \r\n\t\x1e":
            index += 1
        if index >= length:
            break
        try:
            value, index = _DECODER.raw_decode(raw, index)
        except ValueError:
            break
        if isinstance(value, dict):
            messages.append(value)
    return messages


class ConsumerCopilotClient:
    """Stream consumer-Copilot replies through browser-impersonated curl_cffi.

    ``cookies`` and ``access_token`` are exported from a signed-in Edge profile.
    Federated accounts may additionally require ``identity_type``. One curl
    session performs the landing-page request, conversation creation, and chat
    WebSocket so Cloudflare sees one coherent browser fingerprint.
    """

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        access_token: str = "",
        identity_type: str = "",
        idle_timeout: float | None = None,
        timeout: float = _REQUEST_TIMEOUT,
        proxy: str | None = None,
        gate: Callable[[], Awaitable[dict]] | None = None,
        session_factory: Callable[..., AsyncSession] = AsyncSession,
        mode: str = "smart",
    ):
        self._cookies = dict(cookies or {})
        self._token = access_token or ""
        self._identity_type = identity_type or ""
        self._mode = mode or "smart"
        self._idle_timeout = idle_timeout or _IDLE_TIMEOUT
        self._timeout = timeout
        self._proxy = proxy
        self._gate = gate
        self._session_factory = session_factory

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        self._mode = value or "smart"

    def _ws_url(self) -> str:
        """Build the authenticated v2 chat URL used by the current web client."""
        url = f"{CHAT_WEBSOCKET_URL}&clientSessionId={uuid.uuid4()}"
        if self._token:
            url += f"&accessToken={quote(self._token)}"
            if self._identity_type:
                url += f"&X-UserIdentityType={quote(self._identity_type)}"
        return url + "&features=anonymous-block-page&setflight=anonymous-block-page"

    async def chat_stream(
        self, prompt: str, conversation_id: str = ""
    ) -> AsyncIterator[str]:
        """Yield one turn, refreshing the browser gate once before any output."""
        emitted = retried = False
        while True:
            try:
                async for chunk in self._chat_stream_once(prompt, conversation_id):
                    # Only visible output closes the retry window. Upstream can
                    # open a turn with an empty appendText and demand clearance
                    # right after; counting that as emitted spent the one
                    # re-mint on nothing and made the raw challenge escape.
                    emitted = emitted or bool(chunk)
                    yield chunk
                return
            except ClearanceRequired:
                if emitted or retried or self._gate is None:
                    raise
                auth = await self._gate()
                if not isinstance(auth, dict):
                    raise ConsumerCopilotError(
                        "Consumer browser gate returned no authentication snapshot."
                    )
                if "cookies" in auth:
                    self._cookies = dict(auth.get("cookies") or {})
                if "access_token" in auth:
                    self._token = str(auth.get("access_token") or "")
                if "identity_type" in auth:
                    self._identity_type = str(auth.get("identity_type") or "")
                conversation_id = ""
                retried = True

    async def _chat_stream_once(
        self, prompt: str, conversation_id: str = ""
    ) -> AsyncIterator[str]:
        session_kwargs = {
            "impersonate": _IMPERSONATE,
            "cookies": self._cookies,
            "timeout": self._timeout,
        }
        if self._proxy:
            session_kwargs["proxy"] = self._proxy

        async with self._session_factory(**session_kwargs) as session:
            try:
                await session.get(f"{BASE_URL}/")
            except RequestException as exc:
                raise ConsumerCopilotError(
                    f"Consumer Copilot HTTP transport failed: {exc}"
                ) from exc
            if not conversation_id:
                headers = (
                    {"authorization": f"Bearer {self._token}"} if self._token else {}
                )
                try:
                    response = await session.post(CONVERSATION_URL, headers=headers)
                except RequestException as exc:
                    raise ConsumerCopilotError(
                        f"Consumer Copilot HTTP transport failed: {exc}"
                    ) from exc
                if response.status_code != 200:
                    error = (
                        "Could not create a Copilot conversation "
                        f"(HTTP {response.status_code}): {response.text[:200]}"
                    )
                    if response.status_code == 403:
                        raise ClearanceRequired(error)
                    raise ConsumerCopilotError(error)
                conversation_id = (response.json() or {}).get("id")
                if not conversation_id:
                    raise ConsumerCopilotError(
                        "Copilot returned a conversation with no id."
                    )

            send_frame = {
                "event": "send",
                "conversationId": conversation_id,
                "content": [{"type": "text", "text": prompt}],
                "mode": self._mode,
                "context": {},
            }
            ws_kwargs = {
                "impersonate": _IMPERSONATE,
                "timeout": self._timeout,
                "headers": dict(_WS_HEADERS),
            }
            if self._proxy:
                ws_kwargs["proxy"] = self._proxy
            try:
                async with session.ws_connect(self._ws_url(), **ws_kwargs) as ws:
                    # Nothing is sent from here: the backend speaks first with
                    # `connected`, and any frame that arrives before it is
                    # rejected with `error: invalid-event`. _read_stream opens
                    # the turn when that frame lands.
                    async for chunk in self._read_stream(ws, send_frame):
                        yield chunk
            except (WebSocketTimeout, WebSocketClosed, WebSocketError, CurlError) as exc:
                raise ConsumerCopilotError(
                    f"Copilot chat socket refused or interrupted the connection: {exc}"
                ) from exc

    async def _read_stream(self, ws, send_frame: dict) -> AsyncIterator[str]:
        """Open the turn on ``connected``, answer proof-of-work, yield reply text."""
        opened = answered = started = False
        last_message = None
        image_prompt = ""
        # One interleaved trace, `>` sent and `<` received, for the error branch.
        trace: list[str] = []

        async def emit(frame: dict) -> None:
            if len(trace) < _TRACE_LIMIT:
                trace.append(">" + _frame_note(frame))
            await ws.send(json.dumps(frame), CurlWsFlag.TEXT)

        while True:
            try:
                raw, _flags = await ws.recv(timeout=self._idle_timeout)
            except WebSocketTimeout as exc:
                stage = (
                    f"last frame was {last_message!r}."
                    if opened
                    else "it never sent the `connected` frame the turn opens on."
                )
                raise ConsumerCopilotError(
                    f"Copilot chat socket went silent for {self._idle_timeout:.0f}s; "
                    f"{stage}{_trace_suffix(trace)}"
                ) from exc
            except WebSocketClosed as exc:
                stage = (
                    "after reply streaming started"
                    if started
                    else "without replying"
                )
                raise ConsumerCopilotError(
                    f"Copilot chat socket closed {stage}; last frame was "
                    f"{last_message!r}.{_trace_suffix(trace)}"
                ) from exc
            except WebSocketError as exc:
                stage = " after reply streaming started" if started else ""
                raise ConsumerCopilotError(
                    f"Copilot chat socket failed{stage}: {exc}"
                ) from exc

            for message in drain_json(raw):
                last_message = message
                if len(trace) < _TRACE_LIMIT:
                    trace.append("<" + _frame_note(message))
                event = message.get("event")
                if event == "connected":
                    # The backend speaks first and rejects anything sent before
                    # this frame with `error: invalid-event`. curl_cffi's
                    # ws_connect returns as soon as the 101 lands -- a full round
                    # trip before `connected` -- so opening the turn from there
                    # lost that race every time, on every HTTP-only client
                    # written this way. It stayed invisible while an empty
                    # challenge was read as a Cloudflare verdict, because the
                    # turn died before the error frame was ever read.
                    #
                    # A live socket sends `connected` twice; replaying the burst
                    # on the second one is a duplicate `send`, which the backend
                    # also answers with `invalid-event`.
                    if opened:
                        continue
                    opened = True
                    for frame in (SET_OPTIONS_FRAME, CONSENTS_FRAME, send_frame):
                        await emit(frame)
                elif event == "appendText":
                    started = True
                    yield message.get("text") or ""
                elif event == "imageGenerated":
                    # Consumer image generation needs no media bearer: the URL
                    # here is anonymously fetchable (measured: HTTP 200 with no
                    # cookies or token). Emitting it as Markdown is the only way
                    # an OpenAI-compatible client can surface it, and dropping
                    # the frame -- as we used to -- silently lost the whole
                    # image. `prompt` from generatingImage is the alt text.
                    url = message.get("url") or ""
                    if url:
                        started = True
                        yield f"\n\n![{image_prompt or 'image'}]({url})\n\n"
                elif event == "generatingImage":
                    image_prompt = message.get("prompt") or ""
                elif event == "done":
                    return
                elif event == "challenge":
                    method = message.get("method")
                    try:
                        token = await asyncio.to_thread(solve_challenge, message)
                    except (TypeError, ValueError) as exc:
                        raise ClearanceRequired(
                            f"Unsafe Copilot challenge (method={method!r}): {exc}"
                        ) from exc
                    # None means no token can pass: a Turnstile, a method we do
                    # not know, or the method-less verdict Cloudflare returns
                    # when the `send` arrives from a client it does not trust.
                    # Checked before ``answered`` so one arriving late in a turn
                    # still surfaces as a clean error rather than being ignored
                    # into an idle timeout, and typed ClearanceRequired so
                    # chat_stream spends its one gate re-mint on it.
                    if token is None:
                        raise ClearanceRequired(
                            "Copilot answered the turn with a challenge no token "
                            f"can pass (method={method!r}): the chat client is not "
                            "trusted. Measured to follow the egress IP and the "
                            "client stack rather than the credentials -- a re-mint "
                            "a minute earlier draws it again -- so try this "
                            f"account through another egress.{_trace_suffix(trace)}"
                        )
                    if answered:
                        continue
                    await emit({
                        "event": "challengeResponse",
                        "token": token,
                        "method": method,
                        "id": message.get("id"),
                    })
                    answered = True
                    # A real challenge suspends the pending `send`, so it has to
                    # be replayed once cleared.
                    await emit(send_frame)
                elif event == "error":
                    code = message.get("errorCode") or message
                    if code == "chat-service-unavailable":
                        raise RegionBlocked(
                            "Copilot refused the anonymous or out-of-region consumer "
                            "session; sign in and use a supported egress region."
                        )
                    # `invalid-event` names no offending frame, so the exchange
                    # around it is the only way to tell which of ours it rejected.
                    raise ConsumerCopilotError(
                        f"Copilot error: {code};{_trace_suffix(trace)}"
                    )

    async def chat(self, prompt: str, conversation_id: str = "") -> str:
        """Return one complete non-streaming reply."""
        return "".join([
            chunk async for chunk in self.chat_stream(prompt, conversation_id)
        ])
