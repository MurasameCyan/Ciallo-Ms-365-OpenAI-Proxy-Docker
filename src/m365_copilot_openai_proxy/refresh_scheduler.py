from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from .account_store import AccountStore, extract_identity
from .media_proxy import asyncgw_object_fetch_url, designer_file_token, designer_object_fetch_url
from .refresh_browser_helpers import (
    _identity_conflict,
    _is_login_url,
    _is_logged_out_shell,
    _refresh_launch_url,
)
from .refresh_chromium import (
    _chromium_path,
    _cleanup_profile_locks,
    _close_chromium_gracefully,
    _resolve_chromium_path,
)
from .refresh_cookies import (
    _SESSION_COOKIE_PERSIST_SECONDS,
    _cdp_cookie_params,
    _cookie_header_for_url,
    _cookie_names_for_url,
    _critical_cookie_report,
    _normalize_cookie_expires,
    _normalize_cookie_same_site,
)
from .refresh_media import (
    UpstreamMediaNotFound,
    _auth_headers_for_account,
    _auth_headers_for_token,
    _body_preview,
    _is_designer_media_url,
    _is_teams_media_url,
)
from .refresh_image_fetch import fetch_image_one as _fetch_image_one_impl
from .refresh_cookie_inject import inject_cookies_one as _inject_cookies_one_impl



# How many seconds before token expiry we proactively refresh. Matches the
# single-tenant --refresh-before-seconds default so behaviour stays familiar.
_REFRESH_BEFORE_SECONDS = 300
# Max seconds to wait for the on-demand Chromium to expose the M365 tab + token.
_LAUNCH_TIMEOUT_SECONDS = 30
# Background keepalive: how often the loop scans the account pool, and how long
# before a cookie's expiry we proactively refresh it. The scan is cheap (a list
# walk); actual refreshes are serialised through the same global lock so at most
# one Chromium is ever alive. Refreshing well before the 12h cookie window keeps
# cdp accounts warm so a cold /v1 request never lands on an expired session.
_KEEPALIVE_CHECK_INTERVAL_SECONDS = 300
_COOKIE_KEEPALIVE_BEFORE_SECONDS = 2 * 60 * 60
# Min gap between self-heal cookie re-injections for one stuck account, so a
# genuinely dead session does not relaunch Chromium every keepalive tick.
_RECOVERY_RETRY_SECONDS = 30 * 60


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
        # Background keepalive task handle + stop flag (set on app shutdown).
        self._keepalive_task: asyncio.Task | None = None
        self._keepalive_stop: asyncio.Event | None = None
        # Tunable keepalive params (seconds); default to the module constants and
        # are overridden from admin runtime settings via set_keepalive_params().
        self._keepalive_interval_seconds: float = _KEEPALIVE_CHECK_INTERVAL_SECONDS
        self._cookie_keepalive_before_seconds: float = _COOKIE_KEEPALIVE_BEFORE_SECONDS
        # Last self-heal (cookie re-inject) attempt per account, for backoff.
        self._recovery_attempted_at: dict[str, float] = {}

    def set_keepalive_params(self, check_interval_seconds: float | None = None, cookie_before_seconds: float | None = None) -> None:
        """Update keepalive tunables from admin runtime settings (seconds)."""
        if check_interval_seconds and check_interval_seconds > 0:
            self._keepalive_interval_seconds = float(check_interval_seconds)
        if cookie_before_seconds and cookie_before_seconds > 0:
            self._cookie_keepalive_before_seconds = float(cookie_before_seconds)

    def start_keepalive(self) -> None:
        """Launch the background cookie-keepalive loop (idempotent).

        Called once at app startup. The loop always runs while the app is alive
        (it does NOT pause on idle), so cdp accounts stay warm even with no /v1
        traffic and a cold request never hits an expired cookie.
        """
        if self._keepalive_task is not None and not self._keepalive_task.done():
            return
        self._keepalive_stop = asyncio.Event()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def stop_keepalive(self) -> None:
        """Signal the keepalive loop to stop and await its exit (best-effort)."""
        if self._keepalive_stop is not None:
            self._keepalive_stop.set()
        task = self._keepalive_task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
            except Exception:
                pass
        self._keepalive_task = None

    def _keepalive_due(self, account) -> bool:
        """True if a cdp account's cookie is close enough to expiry to refresh."""
        if account.token_source != "cdp":
            return False
        if not account.cookie_valid:
            return False
        # A never-set expiry (0.0) means we have no positive signal the cookie is
        # alive; leave those to on-demand refresh rather than spinning Chromium.
        if account.cookie_expires_at <= 0:
            return False
        return account.cookie_expires_at - time.time() < self._cookie_keepalive_before_seconds

    def _recovery_due(self, account) -> bool:
        """True for a cdp account stuck at cookie_valid=False that still holds
        stored cookies we can replay to self-heal.

        A failed refresh marks the cookie invalid, which then makes _keepalive_due
        skip the account forever -- it can only recover via a manual cookie push.
        When the stored cookies are still present we can replay them (exactly what
        the admin "cookie refresh" button does) to re-establish the session, so
        keepalive heals the account on its own. Backoff via _RECOVERY_RETRY_SECONDS
        keeps a genuinely dead session from relaunching Chromium every tick.
        """
        if account.token_source != "cdp":
            return False
        if account.cookie_valid:
            return False
        if not getattr(account, "cookies", None):
            return False
        last = self._recovery_attempted_at.get(account.id, 0.0)
        return time.time() - last >= _RECOVERY_RETRY_SECONDS

    async def _keepalive_loop(self) -> None:
        stop = self._keepalive_stop
        assert stop is not None
        while not stop.is_set():
            try:
                for account in self._accounts.list():
                    if stop.is_set():
                        break
                    if self._keepalive_due(account):
                        print(f"Keepalive: refreshing {account.id} (cookie near expiry)", flush=True)
                        try:
                            # force=True so a still-valid-but-soon-to-expire token is
                            # refreshed now. ensure_fresh serialises via the global lock.
                            await self.ensure_fresh(account.id, force=True)
                        except Exception as exc:
                            print(f"Keepalive refresh error for {account.id}: {exc}", flush=True)
                    elif self._recovery_due(account):
                        # Self-heal a stuck (cookie_valid=False) account. force=True
                        # routes into _refresh_one, which now re-injects the stored
                        # cookies AND captures a token in that same live session --
                        # the same proven path as the manual cookie-refresh button
                        # the user confirmed recovers the session (not just a bare
                        # cookie re-inject: this also gets a usable token back).
                        self._recovery_attempted_at[account.id] = time.time()
                        print(f"Keepalive: self-heal refreshing {account.id} (cookie invalid)", flush=True)
                        try:
                            ok = await self.ensure_fresh(account.id, force=True)
                            print(f"Keepalive self-heal for {account.id}: {'recovered' if ok else 'still failing'}", flush=True)
                        except Exception as exc:
                            print(f"Keepalive self-heal error for {account.id}: {exc}", flush=True)
            except Exception as exc:
                print(f"Keepalive loop iteration error: {exc}", flush=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._keepalive_interval_seconds)
            except asyncio.TimeoutError:
                pass

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

    def _is_expired(self, token: str) -> bool:
        """True once the token is actually past its exp (no proactive window).

        Distinct from _needs_refresh (which fires _REFRESH_BEFORE_SECONDS early):
        a profile-less manual account cannot auto-refresh, so we only reject it
        on the /v1 passive path once the token is genuinely dead. An empty token
        counts as expired, but an undecodable one does NOT: pushed tokens are
        validated as substrate JWTs at the routes, so a decode failure here means
        an opaque/test token we should keep trusting rather than 503 spuriously.
        """
        if not token:
            return True
        try:
            from .token_store import decode_jwt_payload

            claims = decode_jwt_payload(token)
            return time.time() >= int(claims.get("exp", 0))
        except Exception:
            return False

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
            # Manual accounts have no auto-refresh profile of their own. On the
            # passive /v1 path (force=False) we trust a still-valid token and
            # reject only once it is genuinely expired, so the middleware can
            # surface a 503 instead of forwarding a dead token silently. A
            # forced refresh (the account "Refresh" button / keepalive) still
            # falls through to _refresh_one: if the account actually carries a
            # signed-in cookie session the capture succeeds and promotes it to
            # "cdp"; otherwise it logs a real failure instead of a silent no-op.
            if not force:
                if self._is_expired(account.token):
                    print(f"Refresh skipped: account {account_id} is manual and its token is expired (no auto-refresh profile)", flush=True)
                    return False
                return bool(account.token)
            print(f"Forced refresh on manual account {account_id}: attempting CDP capture from its profile", flush=True)
            async with self._account_lock(account_id):
                async with self._lock:
                    return await self._refresh_one(account_id)
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
        # Thin delegator to refresh_image_fetch.fetch_image_one. The chromium
        # helpers are looked up as module globals here (not passed as defaults)
        # so tests monkeypatching refresh_scheduler._chromium_path etc. still win.
        return await _fetch_image_one_impl(
            self._accounts,
            self._profile_root,
            account_id,
            url,
            event_sink=event_sink,
            chromium_path=_chromium_path,
            cleanup_profile_locks=_cleanup_profile_locks,
            close_chromium_gracefully=_close_chromium_gracefully,
            launch_timeout_seconds=_LAUNCH_TIMEOUT_SECONDS,
        )

    async def _inject_cookies_one(self, account_id: str, cookies: list[dict], *, allow_nudge: bool = False) -> tuple[int, int]:
        # Thin delegator to refresh_cookie_inject.inject_cookies_one. Same
        # module-global resolution of the chromium helpers as _fetch_image_one.
        # allow_nudge=True drives a full token capture in the same session (used
        # by the CDP refresh path so it reuses this proven cookie re-injection
        # instead of reopening a bare profile that dead-ends on a login popup).
        return await _inject_cookies_one_impl(
            self._accounts,
            self._profile_root,
            account_id,
            cookies,
            chromium_path=_chromium_path,
            cleanup_profile_locks=_cleanup_profile_locks,
            close_chromium_gracefully=_close_chromium_gracefully,
            launch_timeout_seconds=_LAUNCH_TIMEOUT_SECONDS,
            allow_nudge=allow_nudge,
        )

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
                # login_hint biases silent SSO to this account so refresh
                # resolves the intended identity even when the profile/cookies
                # carry more than one Microsoft session (see cli._m365_chat_url).
                _refresh_launch_url(account.email),
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
            token = await _cdp_extract_token(account.cdp_port, allow_nudge=True, expected_email=account.email)
            if not token:
                tabs = _cdp_tab_summary(account.cdp_port)
                if "login.microsoftonline.com" in tabs or "login.live.com" in tabs:
                    self._accounts.set_cookie_status(account_id, False)
                # Read-only diagnostic: dump the stuck page's MSAL localStorage
                # account keys. Empty msalAccountKeys means the injected-cookie
                # profile has no cached MSAL account, so silent SSO cannot run and
                # the SPA dead-ends on an interactive popup (spalanding#code) --
                # which is the actual reason no substrate token appears. This
                # distinguishes that from a missing-cookie problem. Never mutates.
                try:
                    from .cli_cdp import _cdp_login_diagnostic

                    diag = await _cdp_login_diagnostic(account.cdp_port)
                    if diag:
                        print(f"Refresh login diagnostic for {account_id}: {diag}", flush=True)
                except Exception as exc:
                    print(f"Refresh login diagnostic skipped for {account_id}: {exc}", flush=True)
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
            # A successful CDP refresh means Microsoft just re-established the
            # session, so slide the cookie expiry forward every time. (Previously
            # the expiry was only advanced when already past, which left the
            # keepalive trigger stuck near an old expiry and re-firing forever.)
            cookie_expires_at = time.time() + _SESSION_COOKIE_PERSIST_SECONDS
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
