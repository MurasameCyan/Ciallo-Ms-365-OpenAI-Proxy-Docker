from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from .account_store import AccountStore, extract_identity
from .media_proxy import asyncgw_object_fetch_url, designer_file_token, designer_object_fetch_url


# How many seconds before token expiry we proactively refresh. Matches the
# single-tenant --refresh-before-seconds default so behaviour stays familiar.
_REFRESH_BEFORE_SECONDS = 300
# Max seconds to wait for the on-demand Chromium to expose the M365 tab + token.
_LAUNCH_TIMEOUT_SECONDS = 30
_SESSION_COOKIE_PERSIST_SECONDS = 12 * 60 * 60
# Media (and future video) bodies are returned base64-encoded over the CDP
# WebSocket and can far exceed the websockets 1 MB default frame limit (a 2 MB
# image already triggers HTTP 1009 "message too big"). Media sizes are
# unpredictable, so disable the frame cap for the media-fetch socket only; the
# upstream is the trusted M365 endpoint.
_CDP_MEDIA_MAX_MESSAGE_BYTES = None  # None = no size limit


_LOGGED_CHROMIUM_PATH: str | None = None


def _chromium_path() -> str:
    """Locate a Chromium/Edge binary and log the resolved path once per change."""
    resolved = _resolve_chromium_path()
    global _LOGGED_CHROMIUM_PATH
    if resolved != _LOGGED_CHROMIUM_PATH:
        _LOGGED_CHROMIUM_PATH = resolved
        print(f"Chromium binary resolved to: {resolved}", flush=True)
    return resolved


def _resolve_chromium_path() -> str:
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
    configured = os.environ.get("CHROME_BIN")
    if configured and shutil.which(configured):
        return configured
    # Linux (container default): prefer full Chromium. The headless-shell build
    # cannot complete the Microsoft SSO redirect chain (it lands on
    # login.microsoftonline.com and fails to capture a fresh substrate token),
    # so it must never be preferred for the refresh flow.
    return (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("microsoft-edge")
        or shutil.which("microsoft-edge-stable")
        or "chromium"
    )


def _is_login_url(url: str) -> bool:
    return url.startswith(("https://login.microsoftonline.com/", "https://login.live.com/"))


def _is_logged_out_shell(url: str) -> bool:
    """True when M365 loaded the chat shell but WITHOUT a signed-in account.

    m365.cloud.microsoft redirects to `...chat?from=NoAccountOnStart` (and
    similar markers) when the injected cookies did not actually establish a
    session. The URL is not a login page, so `_is_login_url` misses it, yet the
    page has no usable identity -- treating it as "logged in" produces a false
    "cookie valid" state that later fails on refresh. Detect those markers so
    the caller can treat the shell as logged-out.
    """
    lowered = url.lower()
    return any(marker in lowered for marker in ("noaccountonstart", "from=noaccount"))


def _identity_conflict(existing_email: str, new_token: str) -> bool:
    """True when a freshly captured token belongs to a DIFFERENT identity.

    The persistent Chromium profile can retain another Microsoft account's
    session (e.g. a previously injected account), so an on-demand refresh may
    capture a token for the wrong identity and silently overwrite the record.
    Reject the swap when both the stored account and the new token carry an
    email and they differ. When either side has no email we cannot compare, so
    we do not block (first-time capture / opaque token stays permissive).
    """
    existing = (existing_email or "").strip().lower()
    if not existing:
        return False
    _, new_email = extract_identity(new_token)
    new_email = (new_email or "").strip().lower()
    if not new_email:
        return False
    return existing != new_email


# Names of the Microsoft auth cookies that actually carry the signed-in session.
# Used only for diagnostic logging so we can see, after a failed injection,
# whether the critical cookies even reached the refresh browser.
_CRITICAL_AUTH_COOKIE_PREFIXES = (
    "ESTSAUTH", "SignInStateCookie", "ESTSSC", "buid", "esctx",
    "x-ms-gateway-slice", "stsservicecookie", "CCState", "wlidperf",
)

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


def _critical_cookie_report(cookies: list[dict]) -> list[str]:
    """Summarise which critical MS auth cookies are present in the pushed set."""
    report: list[str] = []
    for c in cookies:
        name = str(c.get("name", "") or "")
        if not any(name.upper().startswith(p.upper()) for p in _CRITICAL_AUTH_COOKIE_PREFIXES):
            continue
        exp_raw = c.get("expires") or c.get("expirationDate")
        report.append(
            f"{name}@{c.get('domain', '')}"
            f"(httpOnly={bool(c.get('httpOnly'))},session={not bool(exp_raw)})"
        )
    return report


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
            if expires and _normalize_cookie_expires(expires) < now:
                continue
        except (TypeError, ValueError):
            pass
        if not name or not value:
            continue
        if domain and host != domain and not host.endswith("." + domain):
            continue
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _auth_headers_for_token(token: str) -> dict[str, str]:
    token = token.strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _is_teams_media_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "teams.microsoft.com" or host.endswith(".teams.microsoft.com")


def _is_designer_media_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "designerapp.officeapps.live.com" or host.endswith(".officeapps.live.com")


def _designer_fetch_expression(url: str, headers: dict[str, str]) -> str:
    """Build a JS expression that replays the browser's designer image fetch.

    designerapp rejects both plain httpx GETs and top-level document navigations
    (HTTP 400); the M365 page loads the image with an in-page ``fetch`` whose
    ``Sec-Fetch-Dest`` is ``empty``. Running the same fetch inside Chromium (from
    the designerapp origin) reproduces that exact request shape, including the
    Authorization + FileToken headers and same-origin cookies. The body is
    returned base64-encoded so binary image bytes survive the CDP round trip.
    """
    url_literal = json.dumps(url)
    headers_literal = json.dumps(headers or {})
    return (
        "(async () => {"
        "  try {"
        f"    const r = await fetch({url_literal}, {{headers: {headers_literal}, credentials: 'include'}});"
        "    const buf = await r.arrayBuffer();"
        "    const bytes = new Uint8Array(buf);"
        "    let bin = '';"
        "    const chunk = 0x8000;"
        "    for (let i = 0; i < bytes.length; i += chunk) {"
        "      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));"
        "    }"
        "    return {ok: true, status: r.status, contentType: r.headers.get('content-type') || '', body: btoa(bin)};"
        "  } catch (e) { return {ok: false, error: String(e)}; }"
        "})()"
    )


def _auth_headers_for_account(account, url: str) -> tuple[dict[str, str], str]:
    media_token = str(getattr(account, "media_auth_token", "") or "").strip()
    if media_token and _is_teams_media_url(url):
        return _auth_headers_for_token(media_token), "media"
    if _is_designer_media_url(url):
        # designerapp uses a dedicated Authorization token (a raw JWE) that the
        # browser sends WITHOUT a "Bearer " prefix; replay it verbatim. It also
        # moves the fileToken out of the query string into a FileToken request
        # header, so extract and replay that too. The substrate account token has
        # the wrong audience (HTTP 401), so only fall back to cookies-only when we
        # have not captured the designer token yet.
        headers: dict[str, str] = {}
        file_token = designer_file_token(url)
        if file_token:
            headers["FileToken"] = file_token
        designer_token = str(getattr(account, "designer_auth_token", "") or "").strip()
        if designer_token:
            headers["Authorization"] = designer_token
            return headers, "designer"
        return headers, "designer_cookie"
    if account.token:
        return _auth_headers_for_token(account.token), "account"
    return {}, ""


def _cookie_names_for_url(cookies: list[dict[str, Any]], url: str) -> list[str]:
    host = urlsplit(url).hostname or ""
    names: list[str] = []
    for cookie in cookies:
        name = str(cookie.get("name") or "").strip()
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if name and domain and (host == domain or host.endswith("." + domain)):
            names.append(name)
    return names


class UpstreamMediaNotFound(RuntimeError):
    pass


def _body_preview(content: bytes, limit: int = 300) -> str:
    return content[:limit].decode("utf-8", errors="replace")


def _normalize_cookie_expires(value: object) -> float:
    expires = float(value)
    if expires > 10_000_000_000:
        expires = expires / 1000
    return expires


def _normalize_cookie_same_site(value: object) -> str | None:
    same_site = str(value or "").strip().lower().replace("-", "_")
    if same_site in ("", "unspecified", "no_restriction_unspecified"):
        return None
    if same_site in ("none", "no_restriction"):
        return "None"
    if same_site == "lax":
        return "Lax"
    if same_site == "strict":
        return "Strict"
    return None


def _cdp_cookie_params(cookie: dict, now: float) -> tuple[dict, float, bool]:
    name = str(cookie.get("name") or "")
    raw_value = cookie.get("value")
    if not name or raw_value is None:
        raise ValueError("cookie name and value are required")
    value = str(raw_value)
    domain = str(cookie.get("domain") or ".microsoft.com").strip()
    host = domain.lstrip(".")
    if not host:
        host = "microsoft.com"
    params = {
        "name": name,
        "value": value,
        "url": f"https://{host}/",
        "path": cookie.get("path", "/") or "/",
        "secure": bool(cookie.get("secure", True)),
        "httpOnly": bool(cookie.get("httpOnly", False)),
    }
    if name.startswith("__Host-"):
        params["path"] = "/"
        params["secure"] = True
    else:
        params["domain"] = domain
        if name.startswith("__Secure-"):
            params["secure"] = True
    same_site = _normalize_cookie_same_site(cookie.get("sameSite"))
    if same_site:
        params["sameSite"] = same_site
    if params.get("sameSite") == "None":
        params["secure"] = True
    raw_expires = cookie.get("expirationDate") or cookie.get("expires")
    if raw_expires:
        expires = _normalize_cookie_expires(raw_expires)
        params["expires"] = expires
        return params, expires, False
    expires = now + _SESSION_COOKIE_PERSIST_SECONDS
    params["expires"] = expires
    return params, expires, True


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

    async def fetch_image(self, account_id: str, url: str, event_sink=None) -> tuple[bytes, str]:
        account = self._accounts.get(account_id)
        if account is None:
            raise RuntimeError(f"account {account_id} not found")
        # asyncgw serves the object at the bare /views/original path; the model's
        # trailing display filename triggers an upstream 404, so strip it before
        # any (direct or Chromium) request. Cookie/auth matching only uses host.
        fetch_url = asyncgw_object_fetch_url(url)
        if event_sink and fetch_url != url:
            event_sink("asyncgw_url_normalized", original_path=urlsplit(url).path, fetch_path=urlsplit(fetch_url).path)
        # designerapp rejects requests that still carry the model's fileToken query
        # param; the browser moves it into a FileToken header instead. Compute auth
        # from the URL that STILL carries the fileToken (so it can be lifted into the
        # header), then request the stripped URL. The Chromium fallback receives the
        # unstripped URL and strips it internally for the same reason.
        auth_headers, auth_source = _auth_headers_for_account(account, fetch_url)
        # designerapp rejects plain httpx GETs (no browser context, HTTP 400), so
        # skip the direct path entirely and let Chromium replay the browser's
        # in-page fetch. asyncgw audio still tries the fast direct path first.
        if _is_designer_media_url(fetch_url):
            if event_sink:
                event_sink("direct_skip", reason="designer_requires_browser_fetch")
                event_sink("chromium_fallback_start")
            async with self._account_lock(account_id):
                async with self._lock:
                    return await self._fetch_image_one(account_id, fetch_url, event_sink=event_sink)
        designer_url = designer_object_fetch_url(fetch_url)
        if event_sink and designer_url != fetch_url:
            event_sink("designer_url_normalized", original_query=urlsplit(fetch_url).query, fetch_query=urlsplit(designer_url).query)
        cookie_header = _cookie_header_for_url(account.cookies, designer_url)
        cookie_names = _cookie_names_for_url(account.cookies, designer_url)
        if cookie_header or auth_headers:
            if event_sink:
                event_sink(
                    "direct_start",
                    cookie_count=cookie_header.count(";") + 1 if cookie_header else 0,
                    cookie_names=cookie_names,
                    token_header=bool(auth_headers),
                    auth_source=auth_source,
                )
            try:
                return await self._fetch_image_with_cookies(designer_url, cookie_header, auth_headers=auth_headers, event_sink=event_sink)
            except UpstreamMediaNotFound as exc:
                if event_sink:
                    event_sink("direct_error", error_type=type(exc).__name__, error=str(exc))
            except Exception as exc:
                if event_sink:
                    event_sink("direct_error", error_type=type(exc).__name__, error=str(exc))
        elif event_sink:
            event_sink("direct_skip", reason="no_matching_cookies_or_auth")
        if event_sink:
            event_sink("chromium_fallback_start")
        async with self._account_lock(account_id):
            async with self._lock:
                return await self._fetch_image_one(account_id, fetch_url, event_sink=event_sink)

    async def _fetch_image_with_cookies(self, url: str, cookie_header: str, auth_headers: dict[str, str] | None = None, event_sink=None) -> tuple[bytes, str]:
        import httpx

        headers = {
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,audio/*,video/*,*/*;q=0.8",
            "Referer": "https://designerapp.officeapps.live.com/",
            **(auth_headers or {}),
        }
        if cookie_header:
            headers["Cookie"] = cookie_header
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
        if event_sink:
            response_url = urlsplit(str(response.url))
            fields = {
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "bytes": len(response.content),
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "response_host": response_url.hostname or "",
                "response_path": response_url.path,
                "www_authenticate": response.headers.get("www-authenticate", ""),
            }
            if response.status_code >= 400:
                fields["body_preview"] = _body_preview(response.content)
            event_sink("direct_response", **fields)
        if response.status_code == 404:
            raise UpstreamMediaNotFound("upstream media returned HTTP 404")
        if response.status_code >= 400:
            raise RuntimeError(f"upstream image returned HTTP {response.status_code}")
        return response.content, response.headers.get("content-type", "application/octet-stream")

    async def _fetch_image_one(self, account_id: str, url: str, event_sink=None) -> tuple[bytes, str]:
        account = self._accounts.get(account_id)
        if account is None:
            raise RuntimeError(f"account {account_id} not found")
        account_profile_dir = self._profile_root / account_id
        if not account_profile_dir.exists():
            raise RuntimeError("account browser profile is missing; push cookies again")
        self._profile_root.mkdir(parents=True, exist_ok=True)
        profile_dir = Path(tempfile.mkdtemp(prefix=f"{account_id}-media-", dir=self._profile_root))
        _cleanup_profile_locks(profile_dir)
        proc = None
        try:
            chrome_bin = _chromium_path()
            cdp_port = account.cdp_port
            if event_sink:
                event_sink("chromium_launch", cdp_port=cdp_port, browser=chrome_bin)
            proc = subprocess.Popen([
                chrome_bin,
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-breakpad",
                "--disable-extensions",
                "--disable-software-rasterizer",
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
                        tabs = (await client.get(f"http://localhost:{cdp_port}/json/list")).json()
                    tab = next((t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
                    if tab:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.3)
            if not tab:
                if event_sink:
                    event_sink("chromium_cdp_timeout", cdp_port=cdp_port)
                raise RuntimeError("Chromium CDP tab did not become ready")
            if event_sink:
                event_sink("chromium_cdp_ready", cdp_port=cdp_port)

            async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=_CDP_MEDIA_MAX_MESSAGE_BYTES) as ws:
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
                injected_cookies = 0
                now = time.time()
                for cookie in account.cookies:
                    domain = str(cookie.get("domain", "") or ".microsoft.com")
                    domain_l = domain.lower()
                    if not any(d in domain_l for d in ("microsoft", "office.com", "live.com")):
                        continue
                    try:
                        params, _, _ = _cdp_cookie_params(cookie, now)
                    except (TypeError, ValueError):
                        continue
                    result = await cdp_call("Network.setCookie", params)
                    if result.get("result", {}).get("success"):
                        injected_cookies += 1
                if event_sink:
                    event_sink("chromium_cookies", cookie_count=injected_cookies)
                # Auth is derived from the URL that still carries the fileToken so it
                # can be lifted into the FileToken header; the request itself must use
                # the stripped URL, or designerapp rejects it.
                auth_headers, auth_source = _auth_headers_for_account(account, url)
                if _is_designer_media_url(url):
                    # A top-level document navigation to document.ashx is rejected
                    # with HTTP 400 (Sec-Fetch-Dest: document); the M365 page loads
                    # the image with an in-page fetch (Sec-Fetch-Dest: empty). Load
                    # the designerapp origin first so the fetch is same-origin, then
                    # replay the browser's request verbatim (Authorization + FileToken
                    # headers, fileToken stripped from the query, cookies included).
                    fetch_target = designer_object_fetch_url(url)
                    if event_sink and fetch_target != url:
                        event_sink("designer_url_normalized", original_query=urlsplit(url).query, fetch_query=urlsplit(fetch_target).query)
                    parsed_target = urlsplit(fetch_target)
                    origin = f"{parsed_target.scheme}://{parsed_target.netloc}/"
                    await cdp_call("Page.enable")
                    await cdp_call("Runtime.enable")
                    await cdp_call("Page.navigate", {"url": origin})
                    if event_sink:
                        event_sink("chromium_fetch_start", token_header=bool(auth_headers), auth_source=auth_source)
                    eval_result = await cdp_call(
                        "Runtime.evaluate",
                        {
                            "expression": _designer_fetch_expression(fetch_target, auth_headers),
                            "awaitPromise": True,
                            "returnByValue": True,
                        },
                    )
                    result_obj = eval_result.get("result") or {}
                    if result_obj.get("exceptionDetails"):
                        raise RuntimeError(str(result_obj.get("exceptionDetails")))
                    value = (result_obj.get("result") or {}).get("value") or {}
                    if not value.get("ok"):
                        raise RuntimeError(str(value.get("error") or "designer fetch failed in Chromium"))
                    status = int(value.get("status") or 0)
                    content_type = str(value.get("contentType") or "application/octet-stream")
                    decoded = base64.b64decode(str(value.get("body") or ""))
                    if event_sink:
                        event_sink(
                            "chromium_response",
                            status_code=status,
                            content_type=content_type,
                            response_host=parsed_target.hostname or "",
                            response_path=parsed_target.path,
                            www_authenticate="",
                        )
                        event_sink("chromium_body", bytes=len(decoded), base64_encoded=True, body_preview=_body_preview(decoded) if status >= 400 else "")
                    if status == 404:
                        raise UpstreamMediaNotFound("upstream media returned HTTP 404")
                    if status >= 400:
                        raise RuntimeError(f"upstream media returned HTTP {status}")
                    return decoded, content_type
                nav_url = url
                if auth_headers:
                    await cdp_call("Network.setExtraHTTPHeaders", {"headers": auth_headers})
                await cdp_call("Page.enable")
                if event_sink:
                    event_sink("chromium_navigate", token_header=bool(auth_headers), auth_source=auth_source)
                navigate_id = next_id
                next_id += 1
                await ws.send(json.dumps({"id": navigate_id, "method": "Page.navigate", "params": {"url": nav_url}}))
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
                        if response_url == nav_url or response_url.startswith("https://designerapp.officeapps.live.com/designerapp/document.ashx"):
                            request_id = str(params.get("requestId") or "")
                            status = int(response.get("status") or 0)
                            content_type = str(response.get("mimeType") or "application/octet-stream")
                            response_headers = response.get("headers") or {}
                            if event_sink:
                                event_sink(
                                    "chromium_response",
                                    status_code=status,
                                    content_type=content_type,
                                    response_host=urlsplit(response_url).hostname or "",
                                    response_path=urlsplit(response_url).path,
                                    www_authenticate=str(response_headers.get("www-authenticate") or response_headers.get("WWW-Authenticate") or ""),
                                )
                    elif method == "Network.loadingFinished" and request_id and params.get("requestId") == request_id:
                        break
                    elif method == "Network.loadingFailed" and request_id and params.get("requestId") == request_id:
                        raise RuntimeError(str(params.get("errorText") or "image loading failed"))
                if not request_id:
                    raise RuntimeError("image response was not observed in Chromium")
                body_response = await cdp_call("Network.getResponseBody", {"requestId": request_id})
                result = body_response.get("result") or {}
                body = str(result.get("body") or "")
                if result.get("base64Encoded"):
                    decoded = base64.b64decode(body)
                    if event_sink:
                        event_sink("chromium_body", bytes=len(decoded), base64_encoded=True, body_preview=_body_preview(decoded) if status >= 400 else "")
                    if status == 404:
                        raise UpstreamMediaNotFound("upstream media returned HTTP 404")
                    if status >= 400:
                        raise RuntimeError(f"upstream media returned HTTP {status}")
                    return decoded, content_type
                encoded = body.encode("utf-8")
                if event_sink:
                    event_sink("chromium_body", bytes=len(encoded), base64_encoded=False, body_preview=_body_preview(encoded) if status >= 400 else "")
                if status == 404:
                    raise UpstreamMediaNotFound("upstream media returned HTTP 404")
                if status >= 400:
                    raise RuntimeError(f"upstream media returned HTTP {status}")
                return encoded, content_type
        finally:
            await _close_chromium_gracefully(account.cdp_port, proc)
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            shutil.rmtree(profile_dir, ignore_errors=True)

    async def _inject_cookies_one(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        account = self._accounts.get(account_id)
        if account is None:
            return 0, len(cookies or [])
        profile_dir = self._profile_root / account_id
        # Wipe the persistent profile before injecting the freshly pushed cookies.
        # The profile is isolated per account_id, so this only clears THIS account's
        # residual session -- other users' profiles (profile_root/<their id>) are
        # untouched. Without this, a previous identity's session cookies linger in
        # the profile and the refresh browser can pick the wrong account, causing
        # cross-account pollution. This makes the last pushed cookie the sole
        # session for this account.
        shutil.rmtree(profile_dir, ignore_errors=True)
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
                failures: list[str] = []
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
                self._accounts.set_cookie_status(account_id, True, token_source="cdp", expires_at=min(successful_expires) if successful_expires else 0.0)
                if _is_logged_out_shell(final_url):
                    print(f"Cookie injection armed CDP refresh for {account_id} (NoAccountOnStart shell, SSO capture deferred to refresh): {injected}/{attempted}, persisted session cookies={session_persisted}, final_url={final_url}", flush=True)
                else:
                    print(f"Cookie injection established login for {account_id}: {injected}/{attempted}, persisted session cookies={session_persisted}, final_url={final_url}", flush=True)
            else:
                self._accounts.set_cookie_status(account_id, False)
                if failures:
                    print(f"Cookie injection CDP failures for {account_id}: {' | '.join(failures)}", flush=True)
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
                "--disable-background-networking",
                "--disable-sync",
                "--disable-breakpad",
                "--disable-features=InfiniteRestore,MediaRouter,DialMediaRouteProvider,TranslateUI",
                "--log-level=3",
                "--disable-software-rasterizer",
                "--headless=new",
                "https://m365.cloud.microsoft/chat",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            print(f"Refresh failed for {account_id}: Chromium launch error: {exc}", flush=True)
            return False

        try:
            # Lazy import to avoid a cli <-> app <-> scheduler import cycle.
            from .cli import _cdp_extract_resource_tokens, _cdp_extract_token, _cdp_tab_summary, _wait_for_m365_page

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
            # Identity guard: the persistent profile can retain another account's
            # session, so a captured token may belong to the wrong identity. Never
            # overwrite an established account with a mismatched identity.
            if _identity_conflict(account.email, token):
                _, captured_email = extract_identity(token)
                self._accounts.set_cookie_status(account_id, False)
                print(f"Refresh rejected for {account_id}: identity mismatch (account={account.email!r}, captured={captured_email!r})", flush=True)
                return False
            self._accounts.update_token(account_id, token, token_source="cdp")
            cookie_expires_at = account.cookie_expires_at if account.cookie_expires_at > time.time() else time.time() + _SESSION_COOKIE_PERSIST_SECONDS
            self._accounts.set_cookie_status(account_id, True, token_source="cdp", expires_at=cookie_expires_at)
            # Best-effort: harvest media/designer auth tokens from the MSAL cache so
            # they refresh alongside the cookie without a manual re-push. Only stores
            # what is actually present; a missing resource leaves the old value intact.
            try:
                resources = await _cdp_extract_resource_tokens(account.cdp_port)
                if resources.get("media"):
                    self._accounts.set_media_auth_token(account_id, resources["media"])
                if resources.get("designer"):
                    self._accounts.set_designer_auth_token(account_id, resources["designer"])
                if resources:
                    print(f"Refresh harvested resource tokens for {account_id}: {sorted(resources.keys())}", flush=True)
            except Exception as exc:
                print(f"Refresh resource-token harvest skipped for {account_id}: {exc}", flush=True)
            print(f"Refresh succeeded for {account_id}: token updated from CDP", flush=True)
            return True
        except Exception as exc:
            print(f"Refresh failed for {account_id}: {exc}", flush=True)
            return False
        finally:
            await _close_chromium_gracefully(account.cdp_port, proc)
            await asyncio.sleep(1)
            _cleanup_profile_locks(profile_dir)
