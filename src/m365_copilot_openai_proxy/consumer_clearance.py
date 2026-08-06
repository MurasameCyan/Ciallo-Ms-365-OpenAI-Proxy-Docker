"""Earn Cloudflare clearance for the consumer Copilot backend, headlessly.

:mod:`consumer_client` speaks the chat protocol but cannot answer a Turnstile
``challenge`` frame: minting that token means running Cloudflare's challenge JS.
This module does that in a real browser and hands back the session it earned.

The mechanism, confirmed against the live backend: the token is not something we
mint and forward. Passing the gate *in a browser* makes Cloudflare issue a fresh
``cf_clearance`` cookie, and replaying that cookie is what gets a plain HTTP/WS
client past the gate. So a fresh ``cf_clearance`` (or a warm-up turn that
actually streamed a reply) is the success signal here -- not a token value.

Deliberately built on this repo's existing Chromium + CDP stack rather than
Playwright/Camoufox: the anti-detection that matters is three lines (a real UA,
``--disable-blink-features=AutomationControlled``, hiding ``navigator.webdriver``),
all of which CDP can do, so neither dependency buys anything here.

ponytail: the Turnstile click is a coordinate click on the host ``iframe``.
Cross-origin frame *contents* are unreachable from a top-level
``Runtime.evaluate``, and attaching a CDP session per frame to query the checkbox
is a lot of machinery for a widget whose checkbox is reliably left-of-centre.
Ceiling: if Cloudflare moves the checkbox, this misses -- upgrade by attaching to
the frame target (``Target.attachToTarget`` with ``flatten``) and locating the
checkbox properly.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import websockets

from .refresh_chromium import (
    _chromium_path,
    _cleanup_profile_locks,
    _close_chromium_gracefully,
    chromium_proxy_args,
)
from .runtime_flags import elog, ulog

COPILOT_URL = "https://copilot.microsoft.com/"

# The widget renders in a cross-origin iframe from challenges.cloudflare.com,
# both as a page-load interstitial and as the in-chat gate.
_TURNSTILE_IFRAME = (
    "iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile']"
)

# Viewport-relative box of the Turnstile host iframe, or null when none is
# showing. Skips zero-sized hosts: Copilot keeps a hidden Turnstile iframe
# mounted at all times, so "an iframe exists" is not "a challenge is showing".
_TURNSTILE_BOX_JS = """
(() => {
  const el = document.querySelector(%s);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 10 || r.height < 10) return null;
  return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height});
})()
""" % json.dumps(_TURNSTILE_IFRAME)

# MSAL writes an `account.keys` index the moment sign-in completes, and it stays
# unencrypted even for federated logins whose token cache is encrypted -- so it
# is the one sign-in signal that works for every account type.
_SIGNED_IN_JS = """
(() => {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf('account.keys') !== -1) {
        const a = JSON.parse(localStorage.getItem(k) || 'null');
        if (Array.isArray(a) ? a.length > 0 : (a && Object.keys(a).length > 0))
          return true;
      }
    }
  } catch (e) {}
  return false;
})()
"""

# Focus the composer so the synthetic keystrokes land in it. Returns whether one
# was found; the caller skips typing if not (the page may still be loading).
_FOCUS_COMPOSER_JS = """
(() => {
  for (const sel of ['textarea', "div[contenteditable='true']", "[role='textbox']"]) {
    const el = document.querySelector(sel);
    if (el) { el.focus(); if (el.click) el.click(); return true; }
  }
  return false;
})()
"""

# Survives --disable-blink-features=AutomationControlled in some builds, and is
# a cheap bot tell Turnstile reads. Page.addScriptToEvaluateOnNewDocument runs it
# before any page script, including Cloudflare's.
_STEALTH_JS = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"

_CLEARANCE_COOKIE = "cf_clearance"


class ConsumerSession(dict):
    """Result of a harvest: ``cookies``, ``access_token``, ``identity_type``, ``earned``.

    A dict subclass so it serialises straight to JSON for the account store.
    ``earned`` is False when the browser came back without passing the gate --
    the cookies may still be worth keeping, but the caller should not expect the
    next turn to succeed.
    """

    @property
    def earned(self) -> bool:
        return bool(self.get("earned"))


def _launch_chromium(profile_dir: Path, cdp_port: int, *, headless: bool) -> subprocess.Popen:
    """Start Chromium on ``cdp_port`` against a persistent profile.

    Flags mirror the M365 refresh launch, minus a few that hurt here:
    ``--disable-blink-features=AutomationControlled`` hides the automation tell
    Turnstile reads, and a window size is set because a headless default
    viewport can render the widget off-screen, which breaks the coordinate click.

    The profile must persist: clearance and sign-in both live in it, and wiping
    it turns every turn into a fresh low-trust session.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_profile_locks(profile_dir)
    argv = [
        _chromium_path(),
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        *chromium_proxy_args(),
        "--disable-blink-features=AutomationControlled",
        "--window-size=1280,900",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-sync",
        "--disable-breakpad",
        "--disable-features=InfiniteRestore,MediaRouter,DialMediaRouteProvider,TranslateUI",
        "--log-level=3",
        "--disable-software-rasterizer",
    ]
    if headless:
        argv.append("--headless=new")
    argv.append(COPILOT_URL)
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def _wait_for_page(cdp_port: int, timeout: float) -> dict | None:
    """Return the first CDP page target, or None if the port never answers."""
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=2) as client:
        while time.time() < deadline:
            try:
                tabs = (await client.get(f"http://127.0.0.1:{cdp_port}/json")).json()
                tab = next((t for t in tabs if t.get("type") == "page"), None)
                if tab and tab.get("webSocketDebuggerUrl"):
                    return tab
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return None


class _Cdp:
    """One CDP connection that serves commands and watches events concurrently.

    Both are needed at once here: we drive the page with commands *while*
    watching for the chat socket's URL (the access token) and its reply frames
    (the gate-passed signal). A single reader task owns ``recv`` and routes
    replies to per-command futures, because two coroutines calling ``recv`` on
    one websocket race and lose frames.
    """

    def __init__(self, ws):
        self._ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.access_token = ""
        self.identity_type = ""
        self.replied = False
        self.challenge_seen = False
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        while True:
            try:
                msg = json.loads(await self._ws.recv())
            except Exception:
                break
            future = self._pending.pop(msg.get("id"), None) if "id" in msg else None
            if future is not None and not future.done():
                future.set_result(msg)
            elif msg.get("method"):
                self._on_event(msg)

    def _on_event(self, msg: dict) -> None:
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "Network.webSocketCreated":
            url = params.get("url") or ""
            if "/c/api/chat" in url and "accessToken=" in url:
                query = parse_qs(urlparse(url).query)
                # parse_qs URL-decodes, so this is the raw token; the chat client
                # re-quotes it when building its own socket URL.
                self.access_token = (query.get("accessToken") or [""])[0]
                self.identity_type = (query.get("X-UserIdentityType") or [""])[0]
        elif method == "Network.webSocketFrameReceived":
            payload = ((params.get("response") or {}).get("payloadData")) or ""
            # appendText means the warm-up turn is streaming, i.e. Cloudflare let
            # it through. A challenge frame carries neither, so this never
            # false-fires on the gate itself.
            if "appendText" in payload or "imageGenerated" in payload:
                self.replied = True
            elif '"challenge"' in payload:
                self.challenge_seen = True

    async def call(self, method: str, params: dict | None = None, timeout: float = 10.0):
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        try:
            msg = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            return None
        return msg.get("result")

    async def evaluate(self, expression: str, timeout: float = 10.0):
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=timeout,
        )
        return ((result or {}).get("result") or {}).get("value")

    async def cookies(self) -> list[dict]:
        return ((await self.call("Network.getAllCookies")) or {}).get("cookies") or []

    async def clearance(self) -> str:
        for cookie in await self.cookies():
            if cookie.get("name") == _CLEARANCE_COOKIE:
                return cookie.get("value") or ""
        return ""

    async def close(self) -> None:
        self._reader.cancel()
        try:
            await self._reader
        except (asyncio.CancelledError, Exception):
            pass


def _checkbox_point(box: dict) -> tuple[float, float]:
    """Viewport coordinates of the Turnstile checkbox within its host iframe.

    The checkbox sits left-of-centre, vertically middle. Clamped to 30px from the
    left edge so a wide widget still hits the box rather than the label text.
    """
    return box["x"] + min(30.0, box["w"] / 2), box["y"] + box["h"] / 2


async def _click_turnstile(cdp: _Cdp) -> bool:
    """Click the Turnstile checkbox if one is showing. Returns whether it clicked.

    A CDP mouse event is trusted input dispatched through the browser's normal
    pipeline, so it crosses into the cross-origin challenge frame exactly as a
    real click does -- the same reason the media capture uses dispatchMouseEvent
    rather than a synthetic DOM event.
    """
    raw = await cdp.evaluate(_TURNSTILE_BOX_JS)
    if not raw:
        return False
    try:
        box = json.loads(raw)
    except (TypeError, ValueError):
        return False
    x, y = _checkbox_point(box)
    for event in ("mouseMoved", "mousePressed", "mouseReleased"):
        params = {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1}
        if event == "mouseMoved":
            params.pop("clickCount")
        await cdp.call("Input.dispatchMouseEvent", params)
        await asyncio.sleep(0.05)
    return True


async def _send_warmup(cdp: _Cdp, text: str = "hi") -> bool:
    """Send one throwaway turn through the page composer.

    This is what triggers the *in-chat* gate -- the one the chat socket hits.
    Solving only the page-load interstitial does not earn the clearance a chat
    turn needs. Real key events, not a synthetic input event, because the
    composer's send button stays disabled unless it sees trusted input.
    """
    if not await cdp.evaluate(_FOCUS_COMPOSER_JS):
        return False
    for char in text:
        code = f"Key{char.upper()}" if char.isalpha() else ""
        for event in ("keyDown", "char", "keyUp"):
            params = {"type": event, "key": char, "text": char}
            if event != "char" and code:
                params["code"] = code
                params["windowsVirtualKeyCode"] = ord(char.upper())
            await cdp.call("Input.dispatchKeyEvent", params)
            await asyncio.sleep(0.02)
    await asyncio.sleep(0.3)
    for event in ("keyDown", "keyUp"):
        await cdp.call("Input.dispatchKeyEvent", {
            "type": event, "key": "Enter", "code": "Enter",
            "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
        })
        await asyncio.sleep(0.05)
    return True


def _pick_cookies(raw: list[dict]) -> dict[str, str]:
    """Microsoft-session cookies as name->value, newest-domain wins.

    Sorted so a host-specific cookie overwrites a parent-domain one of the same
    name: Microsoft sets ``_C_Auth`` on both, and the host-scoped value is the
    one the real client sends.
    """
    keep = ("copilot.microsoft.com", ".microsoft.com", ".bing.com", ".live.com")
    picked: dict[str, str] = {}
    for cookie in sorted(raw, key=lambda c: len(c.get("domain") or "")):
        domain = cookie.get("domain") or ""
        if any(d in domain for d in keep) and cookie.get("value"):
            picked[cookie["name"]] = cookie["value"]
    return picked


async def harvest_clearance(
    profile_dir: Path | str,
    *,
    cdp_port: int = 9400,
    headless: bool = True,
    timeout: float = 90.0,
    warmup: bool = True,
) -> ConsumerSession:
    """Drive a browser through the Turnstile gate; return the session it earned.

    Returns cookies (including a fresh ``cf_clearance`` when the gate was
    passed), the chat-scoped access token seen on the page's own chat socket, and
    ``earned``: whether the gate actually opened. ``earned=False`` with cookies
    present is the low-trust case -- a datacenter IP where Cloudflare escalates
    to a puzzle no click can solve. Nothing here raises; the caller decides what
    an unearned session is worth.

    ``headless=False`` needs a display (there is none in the container) and is
    the local escape hatch for solving that puzzle by hand.
    """
    profile_dir = Path(profile_dir)
    proc = None
    session = ConsumerSession(cookies={}, access_token="", identity_type="", earned=False)
    try:
        proc = _launch_chromium(profile_dir, cdp_port, headless=headless)
    except Exception as exc:
        elog(f"Consumer clearance: Chromium launch failed: {exc}")
        return session

    try:
        tab = await _wait_for_page(cdp_port, min(30.0, timeout))
        if tab is None:
            elog(f"Consumer clearance: no CDP page on port {cdp_port}")
            return session
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=None) as ws:
            cdp = _Cdp(ws)
            try:
                return await _run_harvest(cdp, session, timeout=timeout, warmup=warmup)
            finally:
                await cdp.close()
    except Exception as exc:
        elog(f"Consumer clearance: harvest errored: {exc}")
        return session
    finally:
        await _close_chromium_gracefully(cdp_port, proc)
        await asyncio.sleep(0.5)
        _cleanup_profile_locks(profile_dir)


async def _run_harvest(
    cdp: _Cdp, session: ConsumerSession, *, timeout: float, warmup: bool
) -> ConsumerSession:
    """The harvest itself, against an open CDP session (separated to keep it testable)."""
    await cdp.call("Page.enable")
    await cdp.call("Network.enable")
    await cdp.call("Runtime.enable")
    await cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS})
    # Reload so the stealth script applies to the document Cloudflare inspects --
    # the tab launched before we could install it.
    await cdp.call("Page.navigate", {"url": COPILOT_URL})
    await asyncio.sleep(3)

    # Success = clearance *changing*, so remember what we started with. A stale
    # cookie is present-but-rejected, which is exactly why we were called.
    before = await cdp.clearance()
    deadline = time.time() + timeout

    # 1. The page-load interstitial, if any.
    if await _click_turnstile(cdp):
        ulog("Consumer clearance: clicked a page-load Turnstile")

    # 2. The in-chat gate, which only a real turn triggers.
    signed_in = bool(await cdp.evaluate(_SIGNED_IN_JS))
    if warmup and signed_in:
        if await _send_warmup(cdp):
            ulog("Consumer clearance: warm-up turn sent; waiting for the gate")
        else:
            elog("Consumer clearance: no composer found; skipping the warm-up turn")
    elif warmup:
        elog("Consumer clearance: profile is not signed in; skipping the warm-up turn")

    # 3. Click any Turnstile that appears until the turn streams or time runs out.
    clicked = False
    while time.time() < deadline:
        if await _click_turnstile(cdp) and not clicked:
            clicked = True
            ulog("Consumer clearance: clicked the in-chat Turnstile")
        if cdp.replied:
            ulog("Consumer clearance: warm-up replied — gate passed")
            break
        current = await cdp.clearance()
        if current and current != before:
            ulog("Consumer clearance: fresh cf_clearance issued — gate passed")
            break
        await asyncio.sleep(0.5)
    else:
        elog(f"Consumer clearance: gate not passed within {timeout:.0f}s")

    await asyncio.sleep(1)  # let the cookie settle
    session["cookies"] = _pick_cookies(await cdp.cookies())
    session["access_token"] = cdp.access_token
    session["identity_type"] = cdp.identity_type
    session["earned"] = bool(session["cookies"]) and (
        cdp.replied or (await cdp.clearance()) != before
    )
    session["signed_in"] = signed_in
    session["challenge_seen"] = cdp.challenge_seen
    return session
