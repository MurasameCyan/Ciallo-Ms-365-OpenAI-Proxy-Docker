from __future__ import annotations

import asyncio
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

from .account_store import AccountStore


# How many seconds before token expiry we proactively refresh. Matches the
# single-tenant --refresh-before-seconds default so behaviour stays familiar.
_REFRESH_BEFORE_SECONDS = 300
# Max seconds to wait for the on-demand Chromium to expose the M365 tab + token.
_LAUNCH_TIMEOUT_SECONDS = 30


def _chromium_path() -> str:
    """Locate a Chromium/Edge binary for the current platform."""
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return shutil.which("chromium") or shutil.which("chrome") or "chromium"
    if platform.system() == "Darwin":
        return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    # Linux (container default): prefer chromium.
    return (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("microsoft-edge")
        or shutil.which("microsoft-edge-stable")
        or "chromium"
    )


class RefreshScheduler:
    """On-demand, serial token refresh for the multi-tenant account pool.

    Each account owns its own Chromium profile + CDP port. To keep peak memory
    close to the single-tenant footprint, we never keep browsers resident: when
    an account's token is about to expire we bring its browser up, capture a
    fresh token via CDP, then tear it down. A single asyncio.Lock serialises the
    whole thing so at most one Chromium is alive at any instant.

    Only accounts whose token_source == "cdp" are auto-refreshed; "manual"
    accounts have no signed-in profile to capture from and are left untouched
    (their tokens are pushed by the user via the Tampermonkey script / paste).
    """

    def __init__(self, account_store: AccountStore, profile_root: str | Path):
        self._accounts = account_store
        self._profile_root = Path(profile_root)
        self._lock = asyncio.Lock()
        # Per-account locks avoid piling up duplicate refreshes for one account
        # while still letting the global lock serialise across accounts.
        self._account_locks: dict[str, asyncio.Lock] = {}

    def _account_lock(self, account_id: str) -> asyncio.Lock:
        lock = self._account_locks.get(account_id)
        if lock is None:
            lock = asyncio.Lock()
            self._account_locks[account_id] = lock
        return lock

    def _needs_refresh(self, token: str) -> bool:
        if not token:
            return True
        try:
            from .token_store import decode_jwt_payload

            claims = decode_jwt_payload(token)
            return time.time() > int(claims.get("exp", 0)) - _REFRESH_BEFORE_SECONDS
        except Exception:
            return True

    async def ensure_fresh(self, account_id: str) -> bool:
        """Ensure the account's token is valid, refreshing on demand if needed.

        Returns True if the token is usable afterwards, False otherwise. Safe to
        call on every request: it's a cheap no-op when the token is still valid.
        """
        account = self._accounts.get(account_id)
        if account is None:
            return False
        if account.token_source != "cdp":
            # Manual accounts: trust whatever token the user pushed.
            return bool(account.token)
        if not self._needs_refresh(account.token):
            return True

        # Coalesce concurrent refreshes for the same account.
        async with self._account_lock(account_id):
            account = self._accounts.get(account_id) or account
            if not self._needs_refresh(account.token):
                return True
            # Global serialisation: only one Chromium alive at a time.
            async with self._lock:
                return await self._refresh_one(account_id)

    async def inject_cookies(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        account = self._accounts.get(account_id)
        if account is None or not cookies:
            return 0, len(cookies or [])
        async with self._account_lock(account_id):
            async with self._lock:
                return await self._inject_cookies_one(account_id, cookies)

    async def _inject_cookies_one(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        account = self._accounts.get(account_id)
        if account is None:
            return 0, len(cookies or [])
        profile_dir = self._profile_root / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        proc = None
        try:
            proc = subprocess.Popen([
                _chromium_path(),
                f"--remote-debugging-port={account.cdp_port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--headless=new",
                "https://m365.cloud.microsoft/chat",
            ])
        except Exception:
            return 0, len(cookies or [])
        try:
            import httpx
            import websockets

            deadline = time.time() + _LAUNCH_TIMEOUT_SECONDS
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
            async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Network.clearBrowserCookies"}))
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2)
                except Exception:
                    pass
                pending: set[int] = set()
                attempted = 0
                for i, cookie in enumerate(cookies):
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    domain = cookie.get("domain", "") or ".microsoft.com"
                    if not name or value is None or "microsoft" not in domain.lower() and "office.com" not in domain.lower():
                        continue
                    params = {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": cookie.get("path", "/"),
                        "secure": cookie.get("secure", True),
                        "httpOnly": cookie.get("httpOnly", False),
                    }
                    ss = cookie.get("sameSite", "")
                    if ss:
                        ss_cap = str(ss).capitalize()
                        if ss_cap in ("Strict", "Lax", "None"):
                            params["sameSite"] = ss_cap
                    if params.get("sameSite") == "None":
                        params["secure"] = True
                    if cookie.get("expirationDate") or cookie.get("expires"):
                        params["expires"] = cookie.get("expirationDate") or cookie.get("expires")
                    attempted += 1
                    req_id = 100 + i
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
                await ws.send(json.dumps({"id": 9999, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
            if attempted > 0 and injected == attempted:
                self._accounts.set_cookie_status(account_id, True, token_source="cdp")
            else:
                self._accounts.set_cookie_status(account_id, False)
            return injected, attempted
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    async def _refresh_one(self, account_id: str) -> bool:
        account = self._accounts.get(account_id)
        if account is None:
            return False
        profile_dir = self._profile_root / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        proc = None
        try:
            proc = subprocess.Popen([
                _chromium_path(),
                f"--remote-debugging-port={account.cdp_port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--headless=new",
                "https://m365.cloud.microsoft/chat",
            ])
        except Exception:
            return False

        try:
            # Lazy import to avoid a cli <-> app <-> scheduler import cycle.
            from .cli import _cdp_extract_token, _wait_for_m365_page

            loop = asyncio.get_running_loop()
            ready = await loop.run_in_executor(
                None, _wait_for_m365_page, account.cdp_port, _LAUNCH_TIMEOUT_SECONDS
            )
            if not ready:
                return False
            token = await _cdp_extract_token(account.cdp_port, allow_nudge=True)
            if not token:
                return False
            self._accounts.update_token(account_id, token, token_source="cdp")
            return True
        except Exception:
            return False
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
