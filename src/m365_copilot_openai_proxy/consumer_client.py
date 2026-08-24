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
from datetime import datetime, timezone
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

# The lists advertise what a UI could render. Measured on live turns (2026-08-23):
# they do not gate image generation -- upstream sends `generatingImage` and the
# finished JPEG in `partialImageGenerated` whether this frame carries empty lists,
# the two entries below, or the browser's full list. They are kept at the two the
# reference clients send (src/solo/*, E5-M365Copilot-API) only because the
# terminal `imageGenerated` url is a card, and the one turn that did reach it had
# `image` advertised; the rest of the browser's list buys nothing here.
#
# What actually loses an image reply is upstream cutting the socket before that
# terminal frame: see the WebSocketClosed branch of _read_stream.
SET_OPTIONS_FRAME = {
    "event": "setOptions",
    "supportedFeatures": ["partial-generated-images"],
    "supportedCards": ["image"],
    "supportedUIComponents": {},
    "ads": {"supportedTypes": []},
    "supportedActions": [],
}
CONSENTS_FRAME = {"event": "reportLocalConsents", "grantedConsents": []}

# The profile that mints the credentials, so the replay's TLS matches the
# handshake the account was last seen behind. It is not a fix for
# {"event":"challenge","method":null}: an earlier reading of that frame as a
# TLS-fingerprint verdict (firefox147 4/4 replied, chrome146 0/4) has been
# withdrawn, because the method of the first challenge drifts on its own -- the
# same account through the same egress with the same profile drew a solvable
# hashcash and, forty minutes later, the method-less frame -- so one run per cell
# measured the clock, not the stack. Measured 2026-08-12 from the deployed VPS:
# firefox147/144/135 and chrome146 are all challenged within 0.4s, and Copilot's
# own web UI on the same egress draws the identical frame, so no profile
# curl_cffi offers clears whatever this connection scores. See solve_challenge.
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


def _frame_note(message: dict | None) -> str:
    """Compact one frame, either direction, for an error trace.

    Everything but bulk payload is kept verbatim, because a protocol rejection is
    about frame shape -- an explicit ``"method": null`` and an absent ``method``
    are different frames, and the trace is useless if it cannot tell them apart.
    Text and image bytes are reduced instead: they are bulky, they are the user's
    content, and no protocol error is ever about what was said. A
    ``partialImageGenerated`` frame is half a megabyte of base64, so any error
    quoting one verbatim reaches the client as an unreadable wall.
    """
    if not message:
        return "(none)"
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


def _image_markdown(prompt: str, target: str) -> str:
    """Markdown for one generated image; ``target`` is a url or a data uri."""
    return f"\n\n![{prompt or 'image'}]({target})\n\n"


def _socket_death_note(
    exc: WebSocketError,
    *,
    idle_timeout: float,
    opened: bool,
    started: bool,
    last_message: dict | None,
    trace: list[str],
) -> str:
    """How the chat socket died, worded per terminal condition.

    ``WebSocketTimeout`` and ``WebSocketClosed`` both subclass ``WebSocketError``,
    so the read loop needs a single handler to guarantee a buffered image is
    delivered however the socket dies; the wording that used to live in three
    separate ``except`` clauses moves here unchanged.
    """
    if isinstance(exc, WebSocketTimeout):
        stage = (
            f"last frame was {_frame_note(last_message)}."
            if opened
            else "it never sent the `connected` frame the turn opens on."
        )
        return (
            f"Copilot chat socket went silent for {idle_timeout:.0f}s; "
            f"{stage}{_trace_suffix(trace)}"
        )
    if isinstance(exc, WebSocketClosed):
        stage = "after reply streaming started" if started else "without replying"
        return (
            f"Copilot chat socket closed {stage}; last frame was "
            f"{_frame_note(last_message)}.{_trace_suffix(trace)}"
        )
    stage = " after reply streaming started" if started else ""
    return f"Copilot chat socket failed{stage}: {exc}"


# Stable wording shared by throttle diagnostics and tests. HTTP status mapping
# uses the typed AccountThrottled exception rather than parsing this text.
_THROTTLED_MARKER = "spent its message quota"


class ConsumerCopilotError(RuntimeError):
    """The consumer chat backend refused or failed a turn."""


class ClearanceRequired(ConsumerCopilotError):
    """Copilot demanded an interactive Cloudflare verification."""


class RegionBlocked(ConsumerCopilotError):
    """The consumer backend refused this account or egress region."""


class TurnRefused(ConsumerCopilotError):
    """Copilot returned a challenge for which this protocol has no valid token.

    Deliberately not a ``ClearanceRequired``: replying with an empty token is an
    invalid event, while the frame alone does not disclose whether credentials,
    egress, quota, or another connection property caused the refusal. Do not
    spend the turn's one credential re-mint on an undisclosed cause.
    """


def parse_next_available_at(value: str) -> float:
    """Epoch seconds for a throttle frame's ``nextAvailableAt``, 0.0 if unusable.

    A naive timestamp is read as UTC: the value is machine-generated and every
    sample so far carried an offset, so a missing one is far likelier to mean UTC
    than the host's local zone -- and guessing local would move the reported reset
    by whole hours.
    """
    if not value:
        return 0.0
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


class AccountThrottled(ConsumerCopilotError):
    """The account spent its message quota; the backend named a reset time.

    ``next_available_at`` is kept verbatim from ``errorDetail`` because the wait
    is the only actionable part: no client, credential or egress change shortens
    it, and a retry before then draws the same refusal.
    """

    def __init__(self, message: str, next_available_at: str = ""):
        super().__init__(message)
        self.next_available_at = next_available_at

    def retry_after_seconds(self, now: datetime | None = None) -> int | None:
        """Seconds until the quota returns, or None if the frame named no time.

        Clamped at zero: a reset time already in the past must not become a
        negative ``Retry-After``, which clients read as "retry immediately".
        """
        when = parse_next_available_at(self.next_available_at)
        if not when:
            return None
        return math.ceil(max(0.0, when - (now or datetime.now(timezone.utc)).timestamp()))


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
    # method nor a parameter -- is a refusal rather than a puzzle. All three
    # answers were tried against the live backend before this one settled:
    #
    #   empty token   -> `error: invalid-event` (the frame shape is refused)
    #   no frame      -> backend closed the socket without replying, 3/3
    #   None (here)   -> TurnRefused, with the frame trace attached
    #
    # A live throttled turn later established one ordering fact, not an identity:
    # it emitted `chatMessageError errorCode=throttled` with `nextAvailableAt`,
    # followed by this method-less challenge. The explicit error is sufficient to
    # diagnose that turn; a challenge received without it is not sufficient to
    # diagnose quota, egress, credentials, or the client stack. Keep those cases
    # separate rather than turning temporal correlation into a protocol rule.
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
                # Hand over frames that are already in curl_cffi's receive queue
                # when the socket ends. Read out of curl_cffi 0.16.0 (the pinned
                # floor, and what the container runs): a server EOF or a transport
                # error goes through `_finalize_connection`, which records the
                # exception, and the next `recv()` fast-fails on it *before* it
                # reads the queue -- so whatever is still queued is thrown away.
                # This flag makes those queued frames come back first, with the
                # exception after them. An ordinary CLOSE frame is queued rather
                # than recorded, so that path never lost anything; a bare EOF --
                # the shape our image turns actually die of -- does.
                #
                # Which is very likely why the terminal `imageGenerated` vanishes:
                # each `partialImageGenerated` is 250-460KB of base64 to parse, so
                # this loop runs behind the reader task, and a small frame arriving
                # just before the close is dropped rather than read. It also fits
                # "never on a text turn" -- small frames, loop keeps up, nothing
                # left queued. Worth setting either way: a queued frame is data
                # upstream already sent us, and losing the last one can truncate a
                # text reply just as easily as it drops a picture.
                "drain_on_error": True,
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
        partial_image = ""
        image_delivered = False
        # One interleaved trace, `>` sent and `<` received, for the error branch.
        trace: list[str] = []

        async def emit(frame: dict) -> None:
            if len(trace) < _TRACE_LIMIT:
                trace.append(">" + _frame_note(frame))
            await ws.send(json.dumps(frame), CurlWsFlag.TEXT)

        while True:
            try:
                raw, _flags = await ws.recv(timeout=self._idle_timeout)
            except WebSocketError as exc:
                # One handler for every terminal condition -- WebSocketTimeout and
                # WebSocketClosed both subclass WebSocketError -- because an image
                # that is already in hand must be delivered however the socket
                # dies. A clean EOF is only the shape measured most often (6 of 7
                # live turns on 2026-08-23); this route also gets RSTs, which
                # surface as WebSocketError, and upstream can simply go silent,
                # which surfaces as WebSocketTimeout. Handling only the EOF left
                # those two throwing the picture away.
                #
                # An image turn ends by closing rather than by sending `done`: no
                # trace, ours or the browser's, has shown `done` after
                # `imageGenerated`. So once the url is out the close *is* the end
                # of the turn, and raising would report a complete turn as a
                # failure -- which on the non-streaming path throws away the
                # collected reply and loses the very image just delivered. This
                # became the common shape with `drain_on_error`: the terminal
                # frame now arrives out of the queue, immediately followed by the
                # recorded close. A text stream cut short still raises, because a
                # truncated sentence must not pass as a finished answer.
                if image_delivered:
                    return
                # Upstream streams the finished JPEG as progressive base64 in
                # `partialImageGenerated`, then ends the turn instead of sending
                # the terminal `imageGenerated` url (never on a text turn). The
                # image is already in hand, so hand it over as a data uri rather
                # than raise; the alternative is a retry that spends another image
                # quota unit on the same coin flip.
                #
                # Not conditioned on `started`: upstream often writes a sentence
                # before it draws, and a turn that streamed "here it is" and then
                # lost the picture is the bug being fixed, not a success.
                if partial_image:
                    mime = "png" if partial_image.startswith("iVBOR") else "jpeg"
                    yield _image_markdown(
                        image_prompt, f"data:image/{mime};base64,{partial_image}"
                    )
                    return
                raise ConsumerCopilotError(
                    _socket_death_note(
                        exc,
                        idle_timeout=self._idle_timeout,
                        opened=opened,
                        started=started,
                        last_message=last_message,
                        trace=trace,
                    )
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
                        # Supersedes the base64 previews of this same image, so
                        # the close branch does not send it a second time, and
                        # marks the turn's deliverable complete so the close that
                        # follows is an ending rather than a failure.
                        partial_image = ""
                        image_delivered = True
                        yield _image_markdown(image_prompt, url)
                elif event == "partialImageGenerated":
                    # Progressive preview: each frame is a complete JPEG, 300-600KB
                    # of base64. Not streamed on -- the terminal frame's url is far
                    # cheaper when it arrives -- but kept as the fallback for the
                    # usual case where it does not.
                    #
                    # ponytail: one slot, so a turn drawing several images that
                    # then gets cut delivers only the last. Real turns draw one;
                    # widen to a dict keyed by `partId` if that changes.
                    partial_image = message.get("content") or ""
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
                    # None means no token can pass. This frame is terminal but
                    # not diagnostic by itself: a live throttled turn emitted an
                    # explicit chatMessageError first, while other turns exposed
                    # only this challenge. Do not invent a cause when the backend
                    # did not disclose one, and do not spend a credential re-mint
                    # on a frame that has no valid answer.
                    if token is None:
                        raise TurnRefused(
                            "Copilot refused the turn with a challenge no token "
                            f"can pass (method={method!r}); the reason was not "
                            "disclosed. Do not answer this frame or re-mint "
                            f"credentials.{_trace_suffix(trace)}"
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
                elif event == "chatMessageError":
                    # The backend's per-message refusal, captured 2026-08-12:
                    # `{"event":"chatMessageError","errorCode":"throttled",
                    #   "errorDetail":{"type":"throttled","nextAvailableAt":...}}`
                    # followed by a method-less challenge and a close. Unhandled
                    # it was invisible -- the turn sat until the idle timeout and
                    # reported silence, hiding the one number that matters.
                    detail = message.get("errorDetail") or {}
                    code = str(
                        message.get("errorCode") or detail.get("type") or "unknown"
                    )
                    if code == "throttled":
                        when = str(detail.get("nextAvailableAt") or "")
                        raise AccountThrottled(
                            f"This Copilot account {_THROTTLED_MARKER}"
                            + (f"; the backend allows the next turn at {when}"
                               if when else " and named no reset time")
                            + f".{_trace_suffix(trace)}",
                            next_available_at=when,
                        )
                    raise ConsumerCopilotError(
                        f"Copilot refused the message: {code};{_trace_suffix(trace)}"
                    )
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
