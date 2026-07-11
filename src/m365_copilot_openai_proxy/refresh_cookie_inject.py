from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time

from .account_store import extract_identity
from .refresh_browser_helpers import _identity_conflict, _is_login_url, _is_logged_out_shell
from .refresh_cookies import _SESSION_COOKIE_PERSIST_SECONDS, _cdp_cookie_params, _critical_cookie_report

# Verbose cookie-injection diagnostics (critical-cookie report + MSAL
# localStorage dump). Off by default to keep logs clean; set
# COOKIE_INJECT_DEBUG=1 to re-enable when troubleshooting NoAccountOnStart /
# session-establishment problems.
_COOKIE_INJECT_DEBUG = bool(int(os.environ.get("COOKIE_INJECT_DEBUG", "0")))

# Read-only page probe: m365 is an MSAL SPA that keeps the signed-in account in
# localStorage, NOT just cookies. "NoAccountOnStart" means MSAL found no account
# in its local cache. This dumps the final URL, any MSAL/account localStorage
# keys, and the client-visible cookie names so we can tell whether the session
# failed because (a) MSAL has no cached account, or (b) an auth cookie is missing.
_CDP_LOGIN_DIAG_JS = """
(() => {
    const out = {url: location.href, msalKeys: [], cookieNames: []};
    try {
        for (const k of Object.keys(localStorage)) {
            const lk = k.toLowerCase();
            if (lk.includes('login.windows') || lk.includes('msal') ||
                lk.includes('authority') || lk.includes('account') ||
                lk.includes('.microsoft') || lk.includes('clientinfo')) {
                out.msalKeys.push(k.slice(0, 100));
            }
        }
    } catch (e) {}
    try {
        out.cookieNames = document.cookie.split(';')
            .map(s => s.trim().split('=')[0]).filter(Boolean);
    } catch (e) {}
    return JSON.stringify(out).slice(0, 1500);
})()
"""


def _apply_opportunistic_token(accounts, account_id: str, account_email: str, grabbed: str | None) -> bool:
    """Decide whether an opportunistically grabbed token may be written.

    Pure/synchronous so it is unit-testable without a Chromium session. The
    identity guard is mandatory: a shared profile can retain another tenant's
    session, so a mismatched token must never be written to this account.
    Returns True only when a token was actually written.
    """
    if not grabbed:
        return False
    if _identity_conflict(account_email, grabbed):
        _, captured_email = extract_identity(grabbed)
        print(f"Cookie injection skipped opportunistic token for {account_id}: identity mismatch (account={account_email!r}, captured={captured_email!r})", flush=True)
        return False
    accounts.update_token(account_id, grabbed, token_source="cdp")
    accounts.set_cookie_status(account_id, True, token_source="cdp", expires_at=time.time() + _SESSION_COOKIE_PERSIST_SECONDS)
    print(f"Cookie injection opportunistically captured token for {account_id} (no nudge, same session)", flush=True)
    return True


async def inject_cookies_one(
    accounts,
    profile_root,
    account_id: str,
    cookies: list[dict],
    *,
    chromium_path,
    cleanup_profile_locks,
    close_chromium_gracefully,
    launch_timeout_seconds,
) -> tuple[int, int]:
    account = accounts.get(account_id)
    if account is None:
        return 0, len(cookies or [])
    profile_dir = profile_root / account_id
    # Wipe the persistent profile before injecting the freshly pushed cookies.
    # The profile is isolated per account_id, so this only clears THIS account's
    # residual session -- other users' profiles (profile_root/<their id>) are
    # untouched. Without this, a previous identity's session cookies linger in
    # the profile and the refresh browser can pick the wrong account, causing
    # cross-account pollution. This makes the last pushed cookie the sole
    # session for this account.
    shutil.rmtree(profile_dir, ignore_errors=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    cleanup_profile_locks(profile_dir)
    proc = None
    try:
        proc = subprocess.Popen([
            chromium_path(),
            f"--remote-debugging-port={account.cdp_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-breakpad",
            "--disable-features=InfiniteRestore,MediaRouter,DialMediaRouteProvider,TranslateUI",
            "--log-level=3",
            "--disable-software-rasterizer",
            "--headless=new",
            "https://m365.cloud.microsoft/chat",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return 0, len(cookies or [])
    try:
        import httpx
        import websockets

        deadline = time.time() + launch_timeout_seconds
        tab = None
        async with httpx.AsyncClient(timeout=2) as client:
            while time.time() < deadline:
                try:
                    tabs = (await client.get(f"http://localhost:{account.cdp_port}/json")).json()
                    tab = next((t for t in tabs if t.get("type") == "page"), None)
                    if tab:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
        if not tab:
            return 0, len(cookies or [])
        injected = 0
        final_url = tab.get("url", "")
        async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
            if "m365.cloud.microsoft" not in tab.get("url", ""):
                await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
                await asyncio.sleep(3)
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2)
                except Exception:
                    pass
            pending: set[int] = set()
            expires_by_id: dict[int, float] = {}
            successful_expires: list[float] = []
            now = time.time()
            session_persisted = 0
            attempted = 0
            failures: list[str] = []
            if _COOKIE_INJECT_DEBUG:
                crit = _critical_cookie_report(cookies)
                print(f"Cookie inject diag [{account_id}] pushed={len(cookies)} critical={crit or 'NONE'}", flush=True)
            for i, cookie in enumerate(cookies):
                domain = str(cookie.get("domain", "") or ".microsoft.com")
                domain_l = domain.lower()
                if not any(d in domain_l for d in ("microsoft", "office.com", "live.com")):
                    continue
                try:
                    params, exp, was_session = _cdp_cookie_params(cookie, now)
                except (TypeError, ValueError):
                    continue
                if was_session:
                    session_persisted += 1
                attempted += 1
                req_id = 100 + i
                if exp > now:
                    expires_by_id[req_id] = float(exp)
                pending.add(req_id)
                await ws.send(json.dumps({"id": req_id, "method": "Network.setCookie", "params": params}))
            deadline = time.time() + 6
            while pending and time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except Exception:
                    continue
                msg = json.loads(raw)
                msg_id = msg.get("id")
                if msg_id in pending:
                    pending.remove(msg_id)
                    if msg.get("result", {}).get("success"):
                        injected += 1
                        if msg_id in expires_by_id:
                            successful_expires.append(expires_by_id[msg_id])
                    elif len(failures) < 5:
                        failures.append(json.dumps(msg.get("error") or msg.get("result") or {}, ensure_ascii=False))
            await ws.send(json.dumps({"id": 9999, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
            await asyncio.sleep(8)
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=0.5)
            except Exception:
                pass
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    tabs = (await client.get(f"http://localhost:{account.cdp_port}/json")).json()
                cur = next((t for t in tabs if t.get("type") == "page"), None)
                if cur:
                    final_url = cur.get("url", final_url)
            except Exception:
                pass
            # Read-only login diagnostic: dump MSAL localStorage account keys
            # and visible cookie names so we can tell whether NoAccountOnStart
            # is caused by MSAL having no cached account vs a missing cookie.
            # Gated behind COOKIE_INJECT_DEBUG to avoid running the probe and
            # spamming logs during normal operation.
            if _COOKIE_INJECT_DEBUG:
                try:
                    await ws.send(json.dumps({
                        "id": 8888,
                        "method": "Runtime.evaluate",
                        "params": {"expression": _CDP_LOGIN_DIAG_JS, "returnByValue": True},
                    }))
                    diag = None
                    diag_deadline = time.time() + 3
                    while time.time() < diag_deadline:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        msg = json.loads(raw)
                        if msg.get("id") == 8888:
                            diag = msg.get("result", {}).get("result", {}).get("value")
                            break
                    if diag:
                        print(f"Cookie inject diag [{account_id}] page={diag}", flush=True)
                except Exception:
                    pass
        if attempted > 0 and injected == attempted and not _is_login_url(final_url):
            # Legacy (v7 / single-tenant) behaviour: a completed cookie
            # injection that is NOT redirected to a login page arms CDP
            # auto-refresh (token_source="cdp"), even when the SPA first
            # paint shows NoAccountOnStart. The persisted cookies still
            # drive silent SSO token capture inside _refresh_one, so this
            # is what enables on-demand /v1 wake-up refresh. Treating
            # NoAccountOnStart as a failure here (previous behaviour) left
            # token_source="manual" and permanently disabled auto-refresh.
            accounts.set_cookie_status(account_id, True, token_source="cdp", expires_at=min(successful_expires) if successful_expires else 0.0)
            if _is_logged_out_shell(final_url):
                print(f"Cookie injection armed CDP refresh for {account_id} (NoAccountOnStart shell, SSO capture deferred to refresh): {injected}/{attempted}, persisted session cookies={session_persisted}, final_url={final_url}", flush=True)
            else:
                print(f"Cookie injection established login for {account_id}: {injected}/{attempted}, persisted session cookies={session_persisted}, final_url={final_url}", flush=True)
                # Opportunistic token grab: the login is established and Chromium
                # is still alive (closes in finally), so try to read a substrate
                # token from the same session WITHOUT nudging (nudge can block up
                # to 45s and would stall the awaited push response). On success
                # this gives the account a real token + 12h expiry immediately,
                # so the background ensure_fresh(force=False) becomes a no-op and
                # no second Chromium launch is needed. Any failure is silently
                # left to that background refresh, so this never regresses the
                # existing behaviour. The write/identity decision lives in
                # _apply_opportunistic_token so it is unit-testable without a
                # Chromium session.
                try:
                    from .cli import _cdp_extract_token

                    grabbed = await _cdp_extract_token(account.cdp_port, allow_nudge=False, expected_email=account.email)
                    _apply_opportunistic_token(accounts, account_id, account.email, grabbed)
                except Exception as exc:
                    print(f"Cookie injection opportunistic token skipped for {account_id}: {exc}", flush=True)
        else:
            accounts.set_cookie_status(account_id, False)
            if failures:
                print(f"Cookie injection CDP failures for {account_id}: {' | '.join(failures)}", flush=True)
            if attempted > 0 and injected == attempted and _is_login_url(final_url):
                print(f"Cookie injection did not establish login for {account_id}: redirected to {final_url}", flush=True)
        return injected, attempted
    finally:
        await close_chromium_gracefully(account.cdp_port, proc)
        await asyncio.sleep(1)
        cleanup_profile_locks(profile_dir)
