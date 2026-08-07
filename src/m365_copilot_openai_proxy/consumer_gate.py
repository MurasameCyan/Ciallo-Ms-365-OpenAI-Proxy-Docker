"""Drive Edge's native consumer-Copilot UI through interactive verification."""

from __future__ import annotations

import asyncio
import json
import subprocess
import weakref
from collections.abc import Awaitable, Callable
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

from .consumer_client import (
    ClearanceRequired,
    ConsumerCopilotError,
    drain_json,
)

COPILOT_URL = "https://copilot.microsoft.com/"

_VERIFICATION_TEXT = (
    "验证您是真人",
    "確認您是真人",
    "verify you are human",
)

_STEALTH_JS = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
_GATE_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _gate_lock(profile_dir: Path, cdp_port: int) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _GATE_LOCKS.setdefault(loop, {})
    key = (str(profile_dir.resolve()), cdp_port)
    return locks.setdefault(key, asyncio.Lock())


_FIND_CHAT_TOKEN_JS = """
(() => {
  for (let i = 0; i < localStorage.length; i++) {
    const value = localStorage.getItem(localStorage.key(i));
    if (!value || !value.includes('"credentialType":"AccessToken"')) continue;
    try {
      const token = JSON.parse(value);
      if (token && token.secret && token.target && token.target.includes('ChatAI'))
        return token.secret;
    } catch (error) {}
  }
  return '';
})() /* consumer:chat-token */
"""

_FIND_NATIVE_TURN_JS = """
(() => {
  let newChat = null;
  for (const element of document.querySelectorAll('button')) {
    const label = element.getAttribute('aria-label') || '';
    const rect = element.getBoundingClientRect();
    if (rect.width <= 20 || rect.height <= 10) continue;
    const box = {x: rect.x, y: rect.y, w: rect.width, h: rect.height};
    if (/^Starter prompt /i.test(label))
      return JSON.stringify({...box, kind: 'starter'});
    if (/^New chat$/i.test(label)) newChat = {...box, kind: 'new-chat'};
  }
  return JSON.stringify(newChat);
})() /* consumer:native-turn */
"""

class CdpSession:
    """Route CDP command replies and page events through one socket reader."""

    def __init__(self, ws):
        self._ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._chat_requests: set[str] = set()
        self._warmup_started = False
        self._warmup_request = ""
        self.access_token = ""
        self.identity_type = ""
        self.challenge_seen = False
        self.replied = False
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while True:
                message = json.loads(await self._ws.recv())
                if "id" in message:
                    future = self._pending.pop(message["id"], None)
                    if future is not None and not future.done():
                        future.set_result(message)
                elif message.get("method"):
                    self._on_event(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - debugger transports vary
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)
            self._pending.clear()

    def begin_warmup(self) -> None:
        """Reset reply state before clicking the page-owned warm-up control."""
        self._warmup_started = True
        self._warmup_request = ""
        self.challenge_seen = False
        self.replied = False

    def _on_event(self, message: dict) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "Network.webSocketCreated":
            url = params.get("url") or ""
            if "/c/api/chat" not in url:
                return
            request_id = str(params.get("requestId") or "")
            if request_id:
                self._chat_requests.add(request_id)
            query = parse_qs(urlparse(url).query)
            self.access_token = (query.get("accessToken") or [self.access_token])[0]
            self.identity_type = (
                query.get("X-UserIdentityType") or [self.identity_type]
            )[0]
            return
        request_id = str(params.get("requestId") or "")
        payload = ((params.get("response") or {}).get("payloadData")) or ""
        if method == "Network.webSocketFrameSent":
            if not self._warmup_started or request_id not in self._chat_requests:
                return
            if any(frame.get("event") == "send" for frame in drain_json(payload)):
                self._warmup_request = request_id
            return
        if method != "Network.webSocketFrameReceived":
            return
        if not self._warmup_request or request_id != self._warmup_request:
            return
        for frame in drain_json(payload):
            event = frame.get("event")
            if event == "challenge":
                self.challenge_seen = True
            elif event in ("appendText", "imageGenerated"):
                self.replied = True

    async def call(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 10.0,
    ) -> dict:
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._ws.send(json.dumps({
            "id": request_id,
            "method": method,
            "params": params or {},
        }))
        try:
            message = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise ConsumerCopilotError(
                f"Edge CDP command {method} timed out after {timeout:.0f}s."
            ) from exc
        if message.get("error"):
            raise ConsumerCopilotError(
                f"Edge CDP command {method} failed: {message['error']}"
            )
        return message.get("result") or {}

    async def evaluate(self, expression: str, timeout: float = 10.0):
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=timeout,
        )
        return ((result.get("result") or {}).get("value"))

    async def cookies(self) -> list[dict]:
        return (await self.call("Network.getAllCookies")).get("cookies") or []

    async def close(self) -> None:
        self._reader.cancel()
        try:
            await self._reader
        except (asyncio.CancelledError, Exception):
            pass


async def find_verification_box(cdp) -> dict | None:
    """Return the visible verification box, piercing closed shadow roots."""
    tree = await cdp.call("Accessibility.getFullAXTree") or {}
    for node in tree.get("nodes") or []:
        name = str((node.get("name") or {}).get("value") or "")
        if not any(text.lower() in name.lower() for text in _VERIFICATION_TEXT):
            continue
        backend_id = node.get("backendDOMNodeId")
        if not backend_id:
            continue
        result = await cdp.call(
            "DOM.getBoxModel", {"backendNodeId": backend_id}
        ) or {}
        model = result.get("model") or {}
        border = model.get("border") or []
        if (
            len(border) >= 4
            and model.get("width", 0) > 10
            and model.get("height", 0) > 10
        ):
            return {
                "x": border[0],
                "y": border[1],
                "w": model["width"],
                "h": model["height"],
            }
    return None


async def _click_at(cdp, x: float, y: float) -> None:
    for event in ("mouseMoved", "mousePressed", "mouseReleased"):
        await cdp.call("Input.dispatchMouseEvent", {
            "type": event,
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })
        await asyncio.sleep(0.05)


async def click_verification_box(cdp) -> bool:
    """Click the Turnstile checkbox with trusted CDP mouse events."""
    box = await find_verification_box(cdp)
    if not box:
        return False
    x = box["x"] + min(30.0, box["w"] / 2)
    y = box["y"] + box["h"] / 2
    await _click_at(cdp, x, y)
    return True


def _pick_cookies(raw: list[dict]) -> dict[str, str]:
    keep = ("copilot.microsoft.com", "microsoft.com", "bing.com", "live.com")
    picked: dict[str, str] = {}
    for cookie in sorted(raw, key=lambda item: len(item.get("domain") or "")):
        domain = str(cookie.get("domain") or "").lower().lstrip(".")
        if (
            any(domain == suffix or domain.endswith(f".{suffix}") for suffix in keep)
            and cookie.get("value")
        ):
            picked[cookie["name"]] = cookie["value"]
    return picked


async def export_consumer_auth(cdp) -> dict:
    """Export cookies plus a strict ChatAI token from the signed-in Edge tab."""
    cache_token = await cdp.evaluate(_FIND_CHAT_TOKEN_JS)
    access_token = cdp.access_token or str(cache_token or "")
    if not access_token:
        raise ConsumerCopilotError(
            "No ChatAI access token was found in the signed-in Edge profile."
        )
    return {
        "cookies": _pick_cookies(await cdp.cookies()),
        "access_token": access_token,
        "identity_type": cdp.identity_type,
    }


async def send_browser_warmup(
    cdp,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    """Trigger a turn only through SPA-owned New chat/Starter prompt buttons."""
    deadline = asyncio.get_running_loop().time() + timeout
    clicked_new_chat = False
    while True:
        try:
            control = json.loads(
                await cdp.evaluate(_FIND_NATIVE_TURN_JS) or "null"
            )
        except (TypeError, ValueError):
            control = None
        if control and control.get("kind") == "starter":
            await _click_at(
                cdp,
                control["x"] + control["w"] / 2,
                control["y"] + control["h"] / 2,
            )
            return True
        if (
            control
            and control.get("kind") == "new-chat"
            and not clicked_new_chat
        ):
            await _click_at(
                cdp,
                control["x"] + control["w"] / 2,
                control["y"] + control["h"] / 2,
            )
            clicked_new_chat = True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(poll_interval)


def _launch_edge(
    profile_dir: Path,
    cdp_port: int,
    headless: bool,
) -> subprocess.Popen:
    """Launch the configured Edge/Chromium with a persistent consumer profile."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    # A relative --user-data-dir makes Edge start and stay alive while never
    # binding the debugging port, so the caller only sees "no CDP page appeared"
    # after the full timeout. Resolve before it reaches the command line.
    profile_dir = profile_dir.resolve()
    _cleanup_profile_locks(profile_dir)
    command = [
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
        COPILOT_URL,
    ]
    if headless:
        command.insert(-1, "--headless=new")
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _wait_for_copilot_page(cdp_port: int, timeout: float) -> dict | None:
    """Find a Copilot page target on a local Edge CDP endpoint."""
    deadline = asyncio.get_running_loop().time() + timeout
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        while True:
            try:
                response = await client.get(f"http://127.0.0.1:{cdp_port}/json")
                targets = response.json()
                page = next(
                    (
                        target
                        for target in targets
                        if target.get("type") == "page"
                        and "copilot.microsoft.com" in (target.get("url") or "")
                        and target.get("webSocketDebuggerUrl")
                    ),
                    None,
                )
                if page:
                    return page
            except (httpx.HTTPError, ValueError):
                pass
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.5)


async def _run_edge_page(ws_url: str, *, timeout: float = 90.0) -> dict:
    async with websockets.connect(ws_url, max_size=None, proxy=None) as ws:
        cdp = CdpSession(ws)
        try:
            return await recover_consumer_auth(cdp, timeout=timeout)
        finally:
            await cdp.close()


class ConsumerBrowserGate:
    """Callable Edge/CDP recovery adapter for ``ConsumerCopilotClient``."""

    def __init__(
        self,
        profile_dir: Path | str,
        *,
        cdp_port: int = 9400,
        headless: bool = False,
        timeout: float = 90.0,
        wait_for_page: Callable[[int, float], Awaitable[dict | None]] = (
            _wait_for_copilot_page
        ),
        launch: Callable[[Path, int, bool], subprocess.Popen] = _launch_edge,
        run_page: Callable[[str], Awaitable[dict]] | None = None,
        close: Callable[[int, subprocess.Popen | None], Awaitable[None]] = (
            _close_chromium_gracefully
        ),
    ):
        self._profile_dir = Path(profile_dir)
        self._cdp_port = cdp_port
        self._headless = headless
        self._timeout = timeout
        self._wait_for_page = wait_for_page
        self._launch = launch
        self._run_page = run_page or (
            lambda url: _run_edge_page(url, timeout=self._timeout)
        )
        self._close = close

    async def __call__(self) -> dict:
        async with _gate_lock(self._profile_dir, self._cdp_port):
            return await self._recover()

    async def _recover(self) -> dict:
        process = None
        page = await self._wait_for_page(self._cdp_port, 0)
        if page is None:
            process = self._launch(
                self._profile_dir,
                self._cdp_port,
                self._headless,
            )
            page = await self._wait_for_page(
                self._cdp_port,
                min(30.0, self._timeout),
            )
        if page is None:
            if process is not None:
                await self._close(self._cdp_port, process)
            raise ConsumerCopilotError(
                f"Edge started but no consumer-Copilot CDP page appeared on "
                f"port {self._cdp_port}."
            )
        try:
            return await self._run_page(page["webSocketDebuggerUrl"])
        finally:
            if process is not None:
                await self._close(self._cdp_port, process)
                await asyncio.sleep(0.2)
                _cleanup_profile_locks(self._profile_dir)


async def recover_consumer_auth(
    cdp,
    *,
    timeout: float = 90.0,
    poll_interval: float = 0.5,
) -> dict:
    """Drive a native browser turn through Turnstile and return refreshed auth."""
    for domain in ("Page", "Network", "Runtime", "DOM", "Accessibility"):
        await cdp.call(f"{domain}.enable")
    await cdp.call(
        "Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS}
    )
    cdp.begin_warmup()
    sent = await send_browser_warmup(
        cdp,
        timeout=min(30.0, max(timeout, 1.0)),
        poll_interval=poll_interval,
    )
    if not sent:
        raise ConsumerCopilotError(
            "The signed-in Edge tab has no visible New chat or Starter prompt "
            "control for a native consumer-Copilot turn."
        )

    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if cdp.replied:
            return await export_consumer_auth(cdp)
        await click_verification_box(cdp)
        if cdp.replied:
            return await export_consumer_auth(cdp)
        await asyncio.sleep(poll_interval)
    raise ClearanceRequired(
        f"The Edge warm-up did not pass the interactive verification within "
        f"{timeout:.0f}s."
    )
