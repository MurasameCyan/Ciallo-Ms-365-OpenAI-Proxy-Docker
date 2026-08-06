"""Consumer (personal-account) Copilot chat client.

Speaks the copilot.microsoft.com chat protocol, which shares nothing with the
M365 Substrate protocol in :mod:`substrate_client` — different endpoint, a
mandatory two-frame handshake, cookie+accessToken auth instead of a Bearer JWT,
and a proof-of-work challenge per turn.

Protocol shape (captured from the live web client):

    POST /c/api/conversations                     -> {"id": ...}
    wss://copilot.microsoft.com/c/api/chat?api-version=2
        &clientSessionId=<uuid>[&accessToken=<tok>]
    -> setOptions -> reportLocalConsents -> send
    -> connected, challenge (answer it, then re-send), appendText*, done

Ordering is enforced by the backend: a ``send`` before the handshake is rejected
with ``error: invalid-event``.

Wire constants and the PoW solvers are ported from the MIT-licensed
windows-copilot-api project; the transport is this repo's own httpx/websockets
stack rather than curl_cffi, which a live probe confirmed is unnecessary —
Cloudflare admits a plain httpx session with a browser User-Agent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
import websockets

BASE_URL = "https://copilot.microsoft.com"
CHAT_WEBSOCKET_URL = f"{BASE_URL.replace('https', 'wss')}/c/api/chat?api-version=2"
CONVERSATION_URL = f"{BASE_URL}/c/api/conversations"

# A current Chrome UA. Cloudflare rejects httpx's default UA outright, and the
# chat backend keys some behaviour off it; keep this in step with the Chromium
# we ship for token refresh.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# First handshake frame. The lists advertise what a *UI* could render; a text
# prompt still streams back as plain appendText, so sending empty lists is
# enough for a bridge. ponytail: kept minimal deliberately — if Microsoft starts
# gating replies on advertised features, port the full list from solo's
# protocol.py SET_OPTIONS_FRAME.
SET_OPTIONS_FRAME = {
    "event": "setOptions",
    "supportedFeatures": [],
    "supportedCards": [],
    "supportedUIComponents": {},
    "ads": {"supportedTypes": []},
    "supportedActions": [],
}
# Second handshake frame: declare no locally-granted consents.
CONSENTS_FRAME = {"event": "reportLocalConsents", "grantedConsents": []}

_IDLE_TIMEOUT = 60.0
_DECODER = json.JSONDecoder()


class ConsumerCopilotError(RuntimeError):
    """The consumer chat backend refused or failed a turn."""


class ClearanceRequired(ConsumerCopilotError):
    """Copilot demanded a Cloudflare Turnstile token we can't mint here.

    A ``challenge`` frame with ``method`` null or ``"cloudflare"`` means the
    session's ``cf_clearance`` is stale or missing. Minting that token requires
    executing Cloudflare's challenge JS in a real browser, so the caller must
    refresh clearance out-of-band and retry the turn.
    """


class RegionBlocked(ConsumerCopilotError):
    """The chat backend refused the session as anonymous/out-of-region.

    Surfaces as ``chat-service-unavailable``. Confirmed reproducible for
    anonymous sessions: a signed-in ``accessToken`` (MSAL scope
    ``ChatAI.ReadWrite``) is required, or an egress proxy in a supported region.
    """


def solve_hashcash(parameter: str) -> str:
    """Smallest nonce ``n`` with ``difficulty`` leading zero bits in sha256(seed+n)."""
    seed, diff = parameter.rsplit(":", 1)
    difficulty = int(diff)
    full, rem = difficulty // 8, difficulty % 8
    mask = (255 << (8 - rem)) & 0xFF if rem else 0
    n = 0
    while True:
        digest = hashlib.sha256(f"{seed}{n}".encode()).digest()
        if not any(digest[:full]) and (not rem or not digest[full] & mask):
            return str(n)
        n += 1


def solve_copilot_challenge(parameter: str) -> str:
    """The arithmetic ``copilot`` variant: round((a^3/100 + a*25) % 22)."""
    a = float(parameter)
    return str(int(math.floor(((a**3 / 100 + a * 25) % 22) + 0.5)))


def solve_challenge(msg: dict) -> str | None:
    """Return the challenge token, or ``None`` when only a browser can mint it."""
    method, parameter = msg.get("method"), msg.get("parameter")
    if method == "hashcash" and parameter:
        return solve_hashcash(parameter)
    if method == "copilot" and parameter:
        return solve_copilot_challenge(parameter)
    # method null / "cloudflare" / an unknown PoW: browser-only Turnstile token.
    # An *empty* challenge is not a no-op — the real client answers it with a
    # Turnstile token, so acking it with an empty one just stalls the socket.
    return None


def drain_json(raw: str | bytes) -> list[dict]:
    """Split one WS frame into its JSON objects (Copilot packs several per frame)."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    out: list[dict] = []
    idx, length = 0, len(raw)
    while idx < length:
        while idx < length and raw[idx] in " \r\n\t\x1e":
            idx += 1
        if idx >= length:
            break
        try:
            obj, idx = _DECODER.raw_decode(raw, idx)
        except ValueError:
            break  # trailing partial object; the next frame completes it
        if isinstance(obj, dict):
            out.append(obj)
    return out
class ConsumerCopilotClient:
    """Stream consumer-Copilot replies over its chat WebSocket.

    ``cookies`` and ``access_token`` come from a signed-in browser session. Both
    are optional, but anonymous sessions are refused as ``chat-service-unavailable``
    in most regions, so in practice both are required.

    Auth split mirrors the real web client:
      * REST calls (conversation create) authenticate by COOKIE only — sending
        the token as ``Authorization: Bearer`` there returns 401.
      * the WebSocket carries identity in its ``?accessToken=`` query param, and
        it must be the chat-scoped token (MSAL ``ChatAI.ReadWrite``); a
        wrong-audience token 401s the upgrade.
    """

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        access_token: str = "",
        identity_type: str = "",
        idle_timeout: float | None = None,
    ):
        self._cookies = dict(cookies or {})
        self._token = access_token or ""
        self._identity_type = identity_type or ""
        self._idle_timeout = idle_timeout or _IDLE_TIMEOUT

    def _headers(self) -> dict[str, str]:
        return {
            "user-agent": BROWSER_USER_AGENT,
            "origin": BASE_URL,
            "referer": f"{BASE_URL}/",
        }

    def _ws_url(self) -> str:
        """Mirror the real client's param order: api-version, session id, token.

        ``clientSessionId`` is not optional — omitting it is one trigger for an
        ``invalid-event`` rejection.
        """
        url = f"{CHAT_WEBSOCKET_URL}&clientSessionId={uuid.uuid4()}"
        if self._token:
            url += f"&accessToken={quote(self._token)}"
            # Federated (Google) tokens ride an extra identity marker; replay it
            # or the upgrade is rejected.
            if self._identity_type:
                url += f"&X-UserIdentityType={quote(self._identity_type)}"
        return url

    async def create_conversation(self) -> str:
        """Create a conversation and return its id, seeding cookies from the landing page."""
        async with httpx.AsyncClient(
            headers=self._headers(), cookies=self._cookies, timeout=30, follow_redirects=True
        ) as http:
            await http.get(f"{BASE_URL}/")  # establishes __cf_bm / Cloudflare clearance
            response = await http.post(CONVERSATION_URL)
            if response.status_code != 200:
                raise ConsumerCopilotError(
                    f"Could not create a Copilot conversation (HTTP {response.status_code}): "
                    f"{response.text[:200]}"
                )
            conversation_id = (response.json() or {}).get("id")
            if not conversation_id:
                raise ConsumerCopilotError("Copilot returned a conversation with no id.")
            # Keep the freshly-issued cookies for the socket.
            self._absorb_cookies(http.cookies)
            return conversation_id

    def _absorb_cookies(self, cookies: httpx.Cookies) -> None:
        """Merge server-issued cookies (notably ``__cf_bm``) into the session.

        Read the jar rather than ``dict(cookies)``: httpx raises
        ``CookieConflict`` when one name lives on several domains, which is the
        normal case here -- cookies we inject go in domain-less while the
        server's ``Set-Cookie`` carries a real domain, so every signed-in turn
        would crash on ``_C_Auth``.

        Empty values are skipped. The landing page answers with a blank
        ``_C_Auth``, and adopting it would wipe the signed-in cookie the caller
        supplied. The trade-off is that a genuinely cleared cookie lingers for
        the rest of the turn, which is the better failure of the two.
        """
        for cookie in cookies.jar:
            if cookie.value:
                self._cookies[cookie.name] = cookie.value

    async def chat_stream(self, prompt: str, conversation_id: str = "") -> AsyncIterator[str]:
        """Yield reply text chunks for ``prompt``.

        The consumer protocol has no separate system/role channel, so callers
        must fold any system prompt into ``prompt`` themselves.
        """
        conversation_id = conversation_id or await self.create_conversation()
        send_frame = json.dumps({
            "event": "send",
            "conversationId": conversation_id,
            "content": [{"type": "text", "text": prompt}],
            "mode": "smart",
            "context": {},
        })
        cookie_header = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        try:
            ws = await websockets.connect(
                self._ws_url(),
                additional_headers={**self._headers(), "cookie": cookie_header},
                open_timeout=30,
                max_size=None,
            )
        except Exception as exc:  # noqa: BLE001 - upgrade failures vary by cause
            raise ConsumerCopilotError(f"Copilot chat socket refused the connection: {exc}") from exc

        async with ws:
            await ws.send(json.dumps(SET_OPTIONS_FRAME))
            await ws.send(json.dumps(CONSENTS_FRAME))
            await ws.send(send_frame)
            async for chunk in self._read_stream(ws, send_frame):
                yield chunk

    async def _read_stream(self, ws, send_frame: str) -> AsyncIterator[str]:
        """Consume chat frames, answering the PoW challenge, yielding reply text."""
        started = answered = False
        last_msg: dict | None = None
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=self._idle_timeout)
            except asyncio.TimeoutError as exc:
                raise ConsumerCopilotError(
                    f"Copilot chat socket went silent for {self._idle_timeout:.0f}s; "
                    f"last frame was {last_msg!r}."
                ) from exc
            except websockets.ConnectionClosed:
                break

            for msg in drain_json(raw):
                last_msg = msg
                event = msg.get("event")
                if event == "appendText":
                    started = True
                    yield msg.get("text") or ""
                elif event == "done":
                    return
                elif event == "challenge":
                    # A Turnstile can arrive at any point, including after a PoW
                    # was already answered this turn. Surface it regardless of
                    # `answered`, so a stale cf_clearance is a clean error rather
                    # than a silent idle timeout.
                    if msg.get("method") in (None, "cloudflare"):
                        raise ClearanceRequired(
                            "Copilot chat demands a Cloudflare Turnstile token "
                            f"(challenge method={msg.get('method')!r}). Minting that token "
                            "requires executing Cloudflare's challenge JS in a real browser — "
                            "the consumer chat backend gates some sessions this way, especially "
                            "during high load or from certain regions."
                        )
                    if answered:
                        continue  # echo of the challenge we already answered
                    token = solve_challenge(msg)
                    if token is None:
                        raise ClearanceRequired(
                            f"Unsolvable Copilot challenge (method={msg.get('method')!r}); "
                            "Microsoft may have escalated to a browser-only challenge."
                        )
                    await ws.send(json.dumps({
                        "event": "challengeResponse",
                        "token": token,
                        "method": msg.get("method"),
                        "id": msg.get("id"),
                    }))
                    answered = True
                    await ws.send(send_frame)  # the client re-sends the held message
                elif event == "error":
                    code = msg.get("errorCode") or msg
                    if code == "chat-service-unavailable":
                        raise RegionBlocked(
                            "Copilot refused the session (chat-service-unavailable). The "
                            "consumer chat backend rejects anonymous sessions and is "
                            "geo-restricted: sign in to supply an accessToken, or route "
                            "egress through a proxy in a supported region."
                        )
                    raise ConsumerCopilotError(f"Copilot error: {code}")

        if not started:
            raise ConsumerCopilotError(f"Copilot closed the socket without replying: {last_msg!r}")

    async def chat(self, prompt: str, conversation_id: str = "") -> str:
        """Non-streaming convenience wrapper: the whole reply as one string."""
        return "".join([chunk async for chunk in self.chat_stream(prompt, conversation_id)])

