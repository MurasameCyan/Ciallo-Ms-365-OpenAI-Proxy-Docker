from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import shutil
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from .account_store import AccountStore


# How many seconds before token expiry we proactively refresh. Matches the
# single-tenant --refresh-before-seconds default so behaviour stays familiar.
_REFRESH_BEFORE_SECONDS = 300
# Max seconds to wait for the on-demand Chromium to expose the M365 tab + token.
_LAUNCH_TIMEOUT_SECONDS = 30
_SESSION_COOKIE_PERSIST_SECONDS = 12 * 60 * 60


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


def _is_login_url(url: str) -> bool:
    return url.startswith(("https://login.microsoftonline.com/", "https://login.live.com/"))


def _cookie_header_for_url(cookies: list[dict], url: str) -> str:
    host = urlsplit(url).hostname or ""
    now = time.time()
    pairs: list[str] = []
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        expires = cookie.get("expirationDate") or cookie.get("expires") or 0
        try:
            if expires and float(expires) < now:
                continue
        except (TypeError, ValueError):
            pass
        if not name or not value:
            continue
        if domain and host != domain and not host.endswith("." + domain):
            continue
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


async def _close_chromium_gracefully(cdp_port: int, proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        import httpx
        import websockets
        async with httpx.AsyncClient(timeout=2) as client:
            info = (await client.get(f"http://localhost:{cdp_port}/json/version")).json()
        ws_url = info.get("webSocketDebuggerUrl")
        if ws_url:
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
        await asyncio.to_thread(proc.wait, timeout=10)
    except Exception:
        try:
            proc.terminate()
            await asyncio.to_thread(proc.wait, timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _cleanup_profile_locks(profile_dir: Path) -> None:
    """Stop stale Chromium processes for this profile and remove Singleton locks."""
    profile = str(profile_dir.resolve())
    profile_arg = str(profile_dir)
    if platform.system() != "Windows":
        proc_root = Path("/proc")
        if proc_root.exists():
            for entry in proc_root.iterdir():
                if not entry.name.isdigit() or int(entry.name) == os.getpid():
                    continue
                try:
                    raw = (entry / "cmdline").read_bytes().decode("utf-8", "ignore")
                except Exception:
                    continue
                if "--user-data-dir=" in raw and (profile in raw or profile_arg in raw):
                    pid = int(entry.name)
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
            time.sleep(0.3)
            for entry in proc_root.iterdir():
                if not entry.name.isdigit() or int(entry.name) == os.getpid():
                    continue
                try:
                    raw = (entry / "cmdline").read_bytes().decode("utf-8", "ignore")
                except Exception:
                    continue
                if "--user-data-dir=" in raw and (profile in raw or profile_arg in raw):
                    try:
                        os.kill(int(entry.name), signal.SIGKILL)
                    except Exception:
                        pass
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile_dir / name).unlink(missing_ok=True)
        except Exception:
            pass


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

    async def ensure_fresh(self, account_id: str, force: bool = False) -> bool:
        """Ensure the account's token is valid, refreshing on demand if needed.

        Returns True if the token is usable afterwards, False otherwise. Safe to
        call on every request: it's a cheap no-op when the token is still valid.
        """
        account = self._accounts.get(account_id)
        if account is None:
            print(f"Refresh skipped: account {account_id} not found", flush=True)
            return False
        if account.token_source != "cdp":
            # Manual accounts: trust whatever token the user pushed.
            return bool(account.token)
        if not force and not self._needs_refresh(account.token):
            return True

        # Coalesce concurrent refreshes for the same account.
        async with self._account_lock(account_id):
            account = self._accounts.get(account_id) or account
            if not force and not self._needs_refresh(account.token):
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

    async def fetch_image(self, account_id: str, url: str) -> tuple[bytes, str]:
        account = self._accounts.get(account_id)
        if account is None:
            raise RuntimeError(f"account {account_id} not found")
        cookie_header = _cookie_header_for_url(account.cookies, url)
        if cookie_header:
            try:
                return await self._fetch_image_with_cookies(url, cookie_header)
            except Exception:
                pass
        async with self._account_lock(account_id):
            async with self._lock:
                return await self._fetch_image_one(account_id, url)

    async def _fetch_image_with_cookies(self, url: str, cookie_header: str) -> tuple[bytes, str]:
        import httpx

        headers = {
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://designerapp.officeapps.live.com/",
        }
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"upstream image returned HTTP {response.status_code}")
        return response.content, response.headers.get("content-type", "application/octet-stream")

    async def _fetch_image_one(self, account_id: str, url: str) -> tuple[bytes, str]:
        account = self._accounts.get(account_id)
        if account is None:
            raise RuntimeError(f"account {account_id} not found")
        profile_dir = self._profile_root / account_id
        if not profile_dir.exists():
            raise RuntimeError("account browser profile is missing; push cookies again")
        _cleanup_profile_locks(profile_dir)
        proc = None
        try:
            proc = subprocess.Popen([
                _chromium_path(),
                f"--remote-debugging-port={account.cdp_port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-breakpad",
                "--disable-extensions",
                "--headless=new",
                "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import httpx
            import websockets

            deadline = time.time() + _LAUNCH_TIMEOUT_SECONDS
            tab = None
            while time.time() < deadline:
                try:
                    async with httpx.AsyncClient(timeout=2) as client:
                        tabs = (await client.get(f"http://localhost:{account.cdp_port}/json/list")).json()
                    tab = next((t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
                    if tab:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.3)
            if not tab:
                raise RuntimeError("Chromium CDP tab did not become ready")

            async with websockets.connect(tab["webSocketDebuggerUrl"]) as ws:
                next_id = 1

                async def cdp_call(method: str, params: dict | None = None) -> dict:
                    nonlocal next_id
                    msg_id = next_id
                    next_id += 1
                    payload = {"id": msg_id, "method": method}
                    if params is not None:
                        payload["params"] = params
                    await ws.send(json.dumps(payload))
                    while True:
                        msg = json.loads(await ws.recv())
                        if msg.get("id") == msg_id:
                            return msg

                await cdp_call("Network.enable")
                await cdp_call("Page.enable")
                await cdp_call("Page.navigate", {"url": url})
                request_id = ""
                content_type = "application/octet-stream"
                status = 0
                deadline = time.time() + 25
                while time.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(raw)
                    method = msg.get("method")
                    params = msg.get("params") or {}
                    if method == "Network.responseReceived":
                        response = params.get("response") or {}
                        response_url = str(response.get("url") or "")
                        if response_url.startswith("https://designerapp.officeapps.live.com/designerapp/document.ashx"):
                            request_id = str(params.get("requestId") or "")
                            status = int(response.get("status") or 0)
                            content_type = str(response.get("mimeType") or "application/octet-stream")
                            if status >= 400:
                                raise RuntimeError(f"upstream image returned HTTP {status}")
                    elif method == "Network.loadingFinished" and request_id and params.get("requestId") == request_id:
                        break
                    elif method == "Network.loadingFailed" and request_id and params.get("requestId") == request_id:
                        raise RuntimeError(str(params.get("errorText") or "image loading failed"))
                if not request_id:
                    raise RuntimeError("image response was not observed in Chromium")
                if status >= 400:
                    raise RuntimeError(f"upstream image returned HTTP {status}")
                body_response = await cdp_call("Network.getResponseBody", {"requestId": request_id})
                result = body_response.get("result") or {}
                body = str(result.get("body") or "")
                if result.get("base64Encoded"):
                    return base64.b64decode(body), content_type
                return body.encode("utf-8"), content_type
        finally:
            await _close_chromium_gracefully(account.cdp_port, proc)
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass

    async def _inject_cookies_one(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        account = self._accounts.get(account_id)
        if account is None:
            return 0, len(cookies or [])
        profile_dir = self._profile_root / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_profile_locks(profile_dir)
        proc = None
        try:
            proc = subprocess.Popen([
                _chromium_path(),
                f"--remote-debugging-port={account.cdp_port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-breakpad",
                "--disable-features=InfiniteRestore,MediaRouter,DialMediaRouteProvider,TranslateUI",
                "--log-level=3",
                "--headless=new",
                "https://m365.cloud.microsoft/chat",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                for i, cookie in enumerate(cookies):
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    domain = cookie.get("domain", "") or ".microsoft.com"
                    domain_l = domain.lower()
                    if not name or value is None or not any(d in domain_l for d in ("microsoft", "office.com", "live.com")):
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
                    else:
                        params["expires"] = now + _SESSION_COOKIE_PERSIST_SECONDS
                        session_persisted += 1
                    attempted += 1
                    req_id = 100 + i
                    exp = params.get("expires")
                    if isinstance(exp, (int, float)) and exp > now:
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
            if attempted > 0 and injected == attempted and not _is_login_url(final_url):
                self._accounts.set_cookie_status(account_id, True, token_source="cdp", expires_at=min(successful_expires) if successful_expires else 0.0)
                print(f"Cookie injection established login for {account_id}: {injected}/{attempted}, persisted session cookies={session_persisted}, final_url={final_url}", flush=True)
            else:
                self._accounts.set_cookie_status(account_id, False)
                if attempted > 0 and injected == attempted and _is_login_url(final_url):
                    print(f"Cookie injection did not establish login for {account_id}: redirected to {final_url}", flush=True)
            return injected, attempted
        finally:
            await _close_chromium_gracefully(account.cdp_port, proc)
            await asyncio.sleep(1)
            _cleanup_profile_locks(profile_dir)

    async def _refresh_one(self, account_id: str) -> bool:
        account = self._accounts.get(account_id)
        if account is None:
            print(f"Refresh failed: account {account_id} not found", flush=True)
            return False
        profile_dir = self._profile_root / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_profile_locks(profile_dir)
        proc = None
        try:
            proc = subprocess.Popen([
                _chromium_path(),
                f"--remote-debugging-port={account.cdp_port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-breakpad",
                "--disable-features=InfiniteRestore,MediaRouter,DialMediaRouteProvider,TranslateUI",
                "--log-level=3",
                "--headless=new",
                "https://m365.cloud.microsoft/chat",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            print(f"Refresh failed for {account_id}: Chromium launch error: {exc}", flush=True)
            return False

        try:
            # Lazy import to avoid a cli <-> app <-> scheduler import cycle.
            from .cli import _cdp_extract_token, _cdp_tab_summary, _wait_for_m365_page

            loop = asyncio.get_running_loop()
            ready = await loop.run_in_executor(
                None, _wait_for_m365_page, account.cdp_port, _LAUNCH_TIMEOUT_SECONDS
            )
            if not ready:
                tabs = _cdp_tab_summary(account.cdp_port)
                if "login.microsoftonline.com" in tabs or "login.live.com" in tabs:
                    self._accounts.set_cookie_status(account_id, False)
                print(f"Refresh failed for {account_id}: M365 page not ready on CDP port {account.cdp_port}; tabs: {tabs}", flush=True)
                return False
            token = await _cdp_extract_token(account.cdp_port, allow_nudge=True)
            if not token:
                tabs = _cdp_tab_summary(account.cdp_port)
                if "login.microsoftonline.com" in tabs or "login.live.com" in tabs:
                    self._accounts.set_cookie_status(account_id, False)
                print(f"Refresh failed for {account_id}: no fresh substrate token captured from CDP port {account.cdp_port}; tabs: {tabs}", flush=True)
                return False
            self._accounts.update_token(account_id, token, token_source="cdp")
            cookie_expires_at = account.cookie_expires_at if account.cookie_expires_at > time.time() else time.time() + _SESSION_COOKIE_PERSIST_SECONDS
            self._accounts.set_cookie_status(account_id, True, token_source="cdp", expires_at=cookie_expires_at)
            print(f"Refresh succeeded for {account_id}: token updated from CDP", flush=True)
            return True
        except Exception as exc:
            print(f"Refresh failed for {account_id}: {exc}", flush=True)
            return False
        finally:
            await _close_chromium_gracefully(account.cdp_port, proc)
            await asyncio.sleep(1)
            _cleanup_profile_locks(profile_dir)
