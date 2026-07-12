from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx
import websockets

from .token_store import decode_jwt_payload, is_substrate_token_claims

logger = logging.getLogger(__name__)

_CDP_JS = """
(() => {
    const candidates = [];
    for (const store of [sessionStorage, localStorage]) {
        for (const key of ['LokiAuthToken', ...Object.keys(store).filter(k => k.startsWith('LokiAuthToken'))]) {
            const token = store.getItem(key);
            if (token && token.startsWith('eyJ')) candidates.push(token);
        }
    }
    for (const entry of performance.getEntriesByType('resource')) {
        if (!entry.name.includes('substrate.office.com') ||
            !entry.name.includes('access_token=')) continue;
        const match = entry.name.match(/[?&]access_token=([^&]+)/);
        if (match) candidates.push(decodeURIComponent(match[1]));
    }
    const stores = [sessionStorage, localStorage];
    for (const store of stores) {
        for (const k of Object.keys(store)) {
            if (!k.includes('accesstoken')) continue;
            try {
                const v = JSON.parse(store.getItem(k));
                if (v && v.secret && v.secret.startsWith('eyJ') &&
                    ((v.target && v.target.includes('substrate')) || k.includes('substrate'))) {
                    candidates.push(v.secret);
                }
            } catch {}
        }
    }
    return candidates;
})()
"""

_CDP_DELETE_MSG_JS = """
(() => {
    // Find and click the "more options" / delete button on the latest user message
    const msgs = document.querySelectorAll('[data-content-length], [aria-label*="Delete"], button[title*="Delete"], button[title*="删除"]');
    // Try clicking "more options" on the last user message, then delete
    const moreBtns = document.querySelectorAll('button[aria-label*="More"], button[aria-label*="更多"], button[title*="More options"]');
    if (moreBtns.length > 0) {
        const last = moreBtns[moreBtns.length - 1];
        last.click();
        setTimeout(() => {
            const delBtn = document.querySelector('button[aria-label*="Delete"], button[aria-label*="删除"], [data-testid*="delete"]');
            if (delBtn) delBtn.click();
        }, 500);
    }
    return true;
})()
"""

_CDP_NUDGE_JS = """
(() => {
    const input = document.querySelector('[aria-label="Message Copilot"], textarea, [contenteditable="true"], [role="textbox"]');
    if (!input) return false;
    input.focus();
    input.click();
    return true;
})()
"""

def _token_identity_email(token: str) -> str:
    """Best-effort lowercase email/UPN from a JWT, used only for identity pinning.

    Mirrors the claim precedence in account_store.extract_identity so the
    capture side and the account record agree on what "identity" means.
    """
    try:
        claims = decode_jwt_payload(token)
    except Exception:
        return ""
    for key in ("email", "upn", "unique_name", "preferred_username"):
        val = claims.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return ""


def _select_substrate_token(candidates: list[str], expected_email: str = "") -> str | None:
    """Pick a valid substrate token, PREFERRING the expected identity but never
    rejecting a valid token solely because the identity did not match.

    Each account owns an isolated Chromium profile that is wiped + re-injected
    per account_id, so any substrate token captured in that session belongs to
    this account. The identity claim carried by a substrate token does NOT
    always match account.email (different/absent claim, casing, opaque token),
    so a strict "match or None" filter rejected every legitimate token and made
    the nudge loop time out (observed as repeated /v1 503s even though cookie
    injection succeeded). We therefore treat expected_email as a PREFERENCE:
    return the matching token when present, otherwise fall back to the first
    valid substrate token. Cross-identity protection still exists at write time
    via _identity_conflict, so this fallback cannot silently overwrite an
    account with a genuinely different identity.
    """
    want = (expected_email or "").strip().lower()
    first_valid: str | None = None
    for token in candidates:
        if not _is_substrate_token(token):
            continue
        if first_valid is None:
            first_valid = token
        if not want or _token_identity_email(token) == want:
            return token
    if first_valid is not None and want:
        print(
            f"Substrate token identity did not match expected {want!r} "
            f"(got {_token_identity_email(first_valid)!r}); using first valid token "
            f"(profile is isolated; write-time identity guard still applies)",
            flush=True,
        )
    return first_valid


async def _cdp_extract_token(port: int, *, allow_nudge: bool = True, expected_email: str = "") -> str | None:
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            tabs = (await client.get(f"http://localhost:{port}/json")).json()
    except Exception:
        return None

    tab = _find_m365_page(tabs)
    if not tab:
        return None

    try:
        async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": _CDP_JS}}))
            result = json.loads(await ws.recv())
            candidates = result.get("result", {}).get("result", {}).get("value") or []
            token = _select_substrate_token(candidates, expected_email)
            if token:
                return token
            if not allow_nudge:
                return None
            return await _cdp_nudge_and_wait_for_token(ws, expected_email=expected_email)
    except Exception:
        return None


async def _cdp_capture_websocket_token(port: int, timeout_seconds: int) -> str | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                tabs = (await client.get(f"http://localhost:{port}/json")).json()
        except Exception:
            await asyncio.sleep(1)
            continue

        tab = _find_m365_page(tabs)
        if not tab:
            await asyncio.sleep(1)
            continue

        try:
            async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
                token = await _wait_for_substrate_websocket_token(ws, deadline)
                if token:
                    return token
        except Exception:
            await asyncio.sleep(1)
            continue
    return None


async def _wait_for_substrate_websocket_token(ws, deadline: float) -> str | None:
    while asyncio.get_running_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1)
        except asyncio.TimeoutError:
            continue
        msg = json.loads(raw)
        if msg.get("method") != "Network.webSocketCreated":
            continue
        url = msg.get("params", {}).get("url", "")
        if "substrate.office.com" not in url:
            continue
        match = re.search(r"[?&]access_token=([^&]+)", url)
        if not match:
            continue
        token = match.group(1)
        if _is_substrate_token(token):
            # Try to delete the "hi" message via JS
            await ws.send(json.dumps({"id": 20, "method": "Runtime.evaluate", "params": {"expression": _CDP_DELETE_MSG_JS}}))
            return token
    return None


def _is_m365_page_url(url: str) -> bool:
    return url.startswith((
        "https://m365.cloud.microsoft/",
        "https://www.microsoft365.com/",
        "https://office.com/",
        "https://www.office.com/",
        "https://login.microsoftonline.com/",
        "https://login.live.com/",
    ))


def _find_m365_page(tabs: list[dict]) -> dict | None:
    return next(
        (
            tab for tab in tabs
            if tab.get("type") == "page" and _is_m365_page_url(tab.get("url", ""))
        ),
        None,
    )


def _summarize_cdp_tabs(tabs: list[dict]) -> str:
    urls = [tab.get("url", "") for tab in tabs if tab.get("type") == "page"]
    return " | ".join(urls[:5]) or "no page tabs"


def _cdp_tab_summary(cdp_port: int) -> str:
    try:
        with httpx.Client(timeout=1) as client:
            return _summarize_cdp_tabs(client.get(f"http://localhost:{cdp_port}/json").json())
    except Exception as exc:
        return f"failed to list tabs: {exc}"


# Read-only login diagnostic. m365 is an MSAL SPA that stores the signed-in
# account in localStorage (NOT just cookies). A profile that only had cookies
# injected has NO cached MSAL account, so MSAL cannot do silent SSO and the SPA
# dead-ends on an interactive popup (spalanding#code). This probe dumps the
# stuck page's URL, any MSAL/account localStorage keys, and client-visible
# cookie names so we can tell empty-MSAL-account (needs interactive login /
# localStorage restore) apart from a missing-cookie problem. Pure read; it
# changes nothing on the page.
_CDP_LOGIN_DIAG_JS = """
(() => {
    const out = {url: location.href, msalAccountKeys: [], cookieNames: []};
    try {
        for (const k of Object.keys(localStorage)) {
            const lk = k.toLowerCase();
            if (lk.includes('login.windows') || lk.includes('msal') ||
                lk.includes('login.microsoftonline.com') || lk.includes('authority') ||
                lk.includes('account') || lk.includes('clientinfo')) {
                out.msalAccountKeys.push(k.slice(0, 120));
            }
        }
    } catch (e) { out.lsError = String(e); }
    try {
        out.cookieNames = document.cookie.split(';')
            .map(s => s.trim().split('=')[0]).filter(Boolean);
    } catch (e) {}
    return JSON.stringify(out).slice(0, 1600);
})()
"""


async def _cdp_login_diagnostic(cdp_port: int) -> str | None:
    """Read-only: dump the current m365 tab's MSAL localStorage account keys.

    Returns a short JSON string or None. Never mutates the page; safe to call on
    a failed-refresh page to diagnose why silent SSO did not yield a token.
    """
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            tabs = (await client.get(f"http://localhost:{cdp_port}/json")).json()
    except Exception:
        return None
    tab = _find_m365_page(tabs) or next(
        (t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None
    )
    if not tab or not tab.get("webSocketDebuggerUrl"):
        return None
    try:
        async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
            await ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": _CDP_LOGIN_DIAG_JS, "returnByValue": True},
            }))
            deadline = asyncio.get_running_loop().time() + 3
            while asyncio.get_running_loop().time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                if msg.get("id") == 1:
                    return msg.get("result", {}).get("result", {}).get("value")
    except Exception:
        return None
    return None


async def _navigate_tab_to_m365(tab: dict) -> None:
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await ws.send(json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))


def _ensure_first_page_navigates_to_m365(tabs: list[dict]) -> None:
    tab = next((t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
    if not tab:
        return
    try:
        asyncio.run(_navigate_tab_to_m365(tab))
    except Exception:
        pass


def _wait_for_m365_page(cdp_port: int, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    navigated = False
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=1) as client:
                tabs = client.get(f"http://localhost:{cdp_port}/json").json()
        except Exception:
            time.sleep(0.5)
            continue
        if _find_m365_page(tabs):
            return True
        if not navigated:
            navigated = True
            _ensure_first_page_navigates_to_m365(tabs)
        time.sleep(0.5)
    return False


def _capture_token_to_env(cdp_port: int, timeout_seconds: int) -> bool:
    # Lazy import to avoid a cli <-> cli_cdp import cycle (cli imports cli_cdp).
    from .cli import _write_token

    token = asyncio.run(_cdp_capture_websocket_token(cdp_port, timeout_seconds))
    if not token:
        return False
    _write_token(token)
    return True


def _needs_substrate_token(token: str | None) -> bool:
    # Lazy import to avoid a cli <-> cli_cdp import cycle (cli imports cli_cdp).
    from .cli import _seconds_remaining

    if not token or not _is_substrate_token(token):
        return True
    try:
        return _seconds_remaining(token) <= 0
    except Exception:
        return True


def _startup_capture_loop(cdp_port: int, timeout_seconds: int) -> None:
    # Lazy import to avoid a cli <-> cli_cdp import cycle (cli imports cli_cdp).
    from .cli import _try_auto_refresh

    print("Waiting for the debug Edge M365 tab...")
    _wait_for_m365_page(cdp_port, min(timeout_seconds, 30))
    print("Trying to refresh Substrate token from the debug Edge tab...")
    if _try_auto_refresh(cdp_port):
        return
    print("Waiting for a Substrate token from the debug Edge M365 Copilot tab...")
    print("If needed: press F5 in Copilot, click the message box, and type one character.")
    if _capture_token_to_env(cdp_port, timeout_seconds):
        print("Token file updated with Substrate token.")
    else:
        print("Startup token capture timed out. Manual set-token is still available.")

def _m365_chat_url(login_hint: str = "") -> str:
    """M365 chat URL, optionally biased to an identity via login_hint.

    login_hint is a standard AAD/MSAL hint that pre-selects the account during
    silent SSO. It is only a query param, so if the SPA ignores it nothing
    breaks; this is a safe, reversible way to steer capture toward the intended
    account when the profile/cookies carry more than one Microsoft session.
    """
    base = "https://m365.cloud.microsoft/chat"
    hint = (login_hint or "").strip()
    if not hint:
        return base
    from urllib.parse import quote

    return f"{base}?login_hint={quote(hint, safe='')}"


async def _cdp_nudge_and_wait_for_token(ws, *, expected_email: str = "") -> str | None:
    want = (expected_email or "").strip().lower()

    async def trigger_input() -> None:
        # Focus the composer, type ONE character, then clear it WITHOUT ever
        # pressing Enter. This mirrors the single-tenant version: nudging the
        # input is enough to make Copilot (re)open the substrate WebSocket, and
        # never submitting keeps the account's chat history clean. Sending a
        # real "hi" turn (a prior approach) polluted the chat because the
        # delete-UI cleanup was unreliable (async menu + browser torn down
        # before setTimeout fired). returnByValue on id==10 lets the main loop
        # tell "chat UI never mounted" from "mounted but no WS".
        await ws.send(json.dumps({"id": 10, "method": "Runtime.evaluate", "params": {"expression": _CDP_NUDGE_JS, "returnByValue": True}}))
        await asyncio.sleep(0.5)
        # Simulate a real keystroke (keyDown -> char -> keyUp) so Copilot's
        # composer reacts as if a user typed.
        for payload in (
            {"type": "keyDown", "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65, "key": "a", "code": "KeyA"},
            {"type": "char", "text": "a", "key": "a"},
            {"type": "keyUp", "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65, "key": "a", "code": "KeyA"},
        ):
            await ws.send(json.dumps({"id": 11, "method": "Input.dispatchKeyEvent", "params": payload}))
            await asyncio.sleep(0.05)
        # Brief pause to let the WS appear, then Ctrl+A + Backspace to clear the
        # character. Never press Enter -> nothing is ever submitted.
        await asyncio.sleep(0.5)
        for payload in (
            {"type": "keyDown", "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65, "key": "a", "code": "KeyA", "modifiers": 2},
            {"type": "keyUp", "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65, "key": "a", "code": "KeyA", "modifiers": 2},
        ):
            await ws.send(json.dumps({"id": 12, "method": "Input.dispatchKeyEvent", "params": payload}))
            await asyncio.sleep(0.05)
        for evt_type in ("keyDown", "keyUp"):
            await ws.send(json.dumps({"id": 13, "method": "Input.dispatchKeyEvent", "params": {"type": evt_type, "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8, "key": "Backspace", "code": "Backspace"}}))
            await asyncio.sleep(0.05)

    await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
    await ws.send(json.dumps({"id": 2, "method": "Network.enable", "params": {"maxTotalBufferSize": 10000000, "maxResourceBufferSize": 5000000}}))
    # Plain /chat (NO login_hint). Runtime evidence: with the MSAL account seeded
    # into localStorage, navigating to plain /chat reaches an established login
    # (silent SSO works), while chat?login_hint degrades to an interactive popup
    # that dead-ends on spalanding#code. Identity is still enforced after capture
    # via _identity_conflict / _select_substrate_token(expected_email).
    await ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": _m365_chat_url()}}))
    await asyncio.sleep(2)
    await ws.send(json.dumps({"id": 4, "method": "Page.reload", "params": {"ignoreCache": True}}))

    loop = asyncio.get_running_loop()
    start = loop.time()
    deadline = start + 45
    # Each trigger now SENDS a real "hi" message (see trigger_input), so keep the
    # cadence sparse: give the cold-loaded chat UI time to mount before the first
    # send, and capture typically returns after the first successful send opens
    # the substrate WS (so extra sends rarely fire).
    trigger_times = [start + 6, start + 20, start + 34]
    triggered = 0
    first_valid: str | None = None
    # Read-only capture diagnostics: record which WebSockets open during the
    # nudge window so a failed capture can be classified -- no substrate WS at
    # all (page never opened the chat connection) vs substrate WS without an
    # access_token query param vs token present but rejected by the claims
    # check. access_token values are redacted; never logged verbatim.
    ws_total = 0
    substrate_total = 0
    substrate_no_token = 0
    substrate_bad_token = 0
    ws_seen: list[str] = []
    while loop.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
        except asyncio.TimeoutError:
            if triggered < len(trigger_times) and loop.time() >= trigger_times[triggered]:
                triggered += 1
                await trigger_input()
            continue
        msg = json.loads(raw)
        if msg.get("method") != "Network.webSocketCreated":
            continue
        url = msg.get("params", {}).get("url", "")
        ws_total += 1
        if len(ws_seen) < 8:
            # Redact any access_token value; keep only host + presence flag.
            redacted = re.sub(r"(access_token=)[^&]+", r"\1<redacted>", url)
            ws_seen.append(redacted[:120])
        if "substrate.office.com" not in url:
            continue
        substrate_total += 1
        match = re.search(r"[?&]access_token=([^&]+)", url)
        if not match:
            substrate_no_token += 1
            continue
        token = match.group(1)
        if not _is_substrate_token(token):
            substrate_bad_token += 1
            continue
        # Identity is a PREFERENCE, not a hard filter. The profile is isolated
        # and wiped+re-injected per account, so any substrate token seen here
        # belongs to this account; a mismatch usually means the substrate token
        # simply carries a different/absent identity claim than account.email.
        # Remember the first valid token and prefer a matching one, but never
        # time out empty-handed when a valid token was captured. Cross-identity
        # protection still applies at write time via _identity_conflict.
        if want and _token_identity_email(token) != want:
            if first_valid is None:
                first_valid = token
            continue
        # Nothing was ever submitted (type-and-clear only), so there is no chat
        # turn to clean up here.
        return token
    if first_valid is not None:
        print(
            f"Nudge captured a substrate token whose identity did not match expected "
            f"{want!r} (got {_token_identity_email(first_valid)!r}); using it "
            f"(profile is isolated; write-time identity guard still applies)",
            flush=True,
        )
        return first_valid
    # Capture failed: classify why so the fix can target the right layer.
    #   substrate_total==0  -> chat page never opened the substrate WS (login
    #                          established but Copilot did not start a session;
    #                          nudge/selector likely did not reach the input).
    #   substrate_no_token  -> substrate WS opened but carried no access_token.
    #   substrate_bad_token -> token present but failed the substrate claims check.
    print(
        f"Nudge capture diagnostic: ws_total={ws_total} substrate_total={substrate_total} "
        f"substrate_no_token={substrate_no_token} substrate_bad_token={substrate_bad_token} "
        f"triggered={triggered} ws_seen={ws_seen}",
        flush=True,
    )
    return first_valid


def _is_substrate_token(token: str) -> bool:
    try:
        claims = decode_jwt_payload(token)
    except Exception:
        return False
    return is_substrate_token_claims(claims) and time.time() < int(claims.get("exp", 0)) - 30


# Harvest every MSAL AccessToken entry (target + secret) from the page's storage.
# MSAL caches one entry per resource the SPA has requested; media (teams) and
# designer tokens live here alongside the substrate token IF the app already
# acquired them. We classify the entries in Python (see _classify_resource_token).
_CDP_RESOURCE_JS = """
(() => {
    const out = [];
    for (const store of [sessionStorage, localStorage]) {
        for (const k of Object.keys(store)) {
            if (!k.toLowerCase().includes('accesstoken')) continue;
            try {
                const v = JSON.parse(store.getItem(k));
                if (v && typeof v.secret === 'string' && v.secret.startsWith('eyJ')) {
                    out.push({key: k, target: String(v.target || ''), secret: v.secret});
                }
            } catch {}
        }
    }
    return out;
})()
"""


def _classify_resource_token(key: str, target: str) -> str | None:
    """Map an MSAL cache entry to 'media' / 'designer' / None.

    Media auth is the Bearer token the browser sends to *.teams.microsoft.com
    (incl. asyncgw); designer auth is the JWE sent to designerapp on
    officeapps.live.com. Substrate tokens are handled elsewhere, so exclude them.
    """
    hint = f"{key} {target}".lower()
    if "substrate" in hint:
        return None
    if any(m in hint for m in ("designerapp", "officeapps.live.com", "designer")):
        return "designer"
    if any(m in hint for m in ("asyncgw", "teams.microsoft.com", "skype", "teams")):
        return "media"
    return None


async def _cdp_extract_resource_tokens(port: int) -> dict[str, str]:
    """Best-effort harvest of media/designer auth tokens from the M365 page.

    Returns {'media': token?, 'designer': token?} for whatever is present in the
    MSAL cache. Absent resources are simply omitted -- the caller must NOT treat
    a missing key as a reason to wipe an existing (manually pushed) token.
    """
    result: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            tabs = (await client.get(f"http://localhost:{port}/json")).json()
    except Exception:
        return result

    tab = _find_m365_page(tabs)
    if not tab:
        return result

    try:
        async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
            await ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": _CDP_RESOURCE_JS, "returnByValue": True},
            }))
            raw = json.loads(await ws.recv())
            entries = raw.get("result", {}).get("result", {}).get("value") or []
    except Exception:
        return result

    seen_targets: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        target = str(entry.get("target") or "")
        key = str(entry.get("key") or "")
        secret = str(entry.get("secret") or "")
        if target:
            seen_targets.append(target[:80])
        kind = _classify_resource_token(key, target)
        if kind and kind not in result and secret:
            result[kind] = secret
    if seen_targets:
        print(f"CDP resource-token targets seen: {seen_targets[:8]}", flush=True)
    return result


# Media/designer auth tokens are NOT in the MSAL cache; they only appear as
# Authorization headers on the fetches the SPA issues when a conversation with
# media is opened. These mirror the userscript's MEDIA_AUTH_HOST_RE rules.
_MEDIA_AUTH_HOST_RE = re.compile(r"(^|\.)(asyncgw\.teams\.microsoft\.com|teams\.microsoft\.com)$", re.IGNORECASE)
_DESIGNER_AUTH_HOST_RE = re.compile(r"(^|\.)officeapps\.live\.com$", re.IGNORECASE)


async def _cdp_capture_media_auth(port: int, seed_url: str, settle_seconds: float = 12.0) -> dict[str, str]:
    """Navigate to a media-bearing conversation and capture the Authorization
    headers the SPA sends to asyncgw/teams (media) and designerapp (designer).

    These tokens are NOT in the MSAL cache; they only surface as live request
    headers when the page re-fetches media. Mirrors the userscript rules:
      - designerapp.officeapps.live.com -> store Authorization verbatim (raw JWE)
      - asyncgw/teams.microsoft.com with 'Bearer X' -> store X (Bearer stripped),
        preferring asyncgw (the actual media fetch endpoint).
    Returns {'media': token?, 'designer': token?}; absent keys are omitted so the
    caller never wipes an existing (manually pushed) token.
    """
    result: dict[str, str] = {}
    if not seed_url:
        return result
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            tabs = (await client.get(f"http://localhost:{port}/json")).json()
    except Exception:
        return result

    tab = _find_m365_page(tabs)
    if not tab:
        return result

    media_asyncgw = ""
    media_teams = ""
    designer = ""
    seen_hosts: list[str] = []
    try:
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=None) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
            await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
            await ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": seed_url}}))
            deadline = time.time() + settle_seconds
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("method") != "Network.requestWillBeSent":
                    continue
                req = msg.get("params", {}).get("request", {})
                url = str(req.get("url") or "")
                headers = req.get("headers") or {}
                auth = ""
                for hk, hv in headers.items():
                    if hk.lower() == "authorization":
                        auth = str(hv or "").strip()
                        break
                if not auth:
                    continue
                try:
                    host = (httpx.URL(url).host or "").lower()
                except Exception:
                    continue
                if _DESIGNER_AUTH_HOST_RE.search(host):
                    if not designer:
                        designer = auth  # raw JWE, verbatim (no Bearer prefix)
                        seen_hosts.append(host)
                elif _MEDIA_AUTH_HOST_RE.search(host):
                    m = re.match(r"^Bearer\s+(.+)$", auth, re.IGNORECASE)
                    if m:
                        if "asyncgw" in host:
                            if not media_asyncgw:
                                media_asyncgw = m.group(1).strip()
                                seen_hosts.append(host)
                        elif not media_teams:
                            media_teams = m.group(1).strip()
                            seen_hosts.append(host)
                if designer and media_asyncgw:
                    break
    except Exception:
        pass

    if media_asyncgw:
        result["media"] = media_asyncgw
    elif media_teams:
        result["media"] = media_teams
    if designer:
        result["designer"] = designer
    if seen_hosts:
        print(f"CDP media-auth capture hosts seen: {seen_hosts[:8]}", flush=True)
    return result


