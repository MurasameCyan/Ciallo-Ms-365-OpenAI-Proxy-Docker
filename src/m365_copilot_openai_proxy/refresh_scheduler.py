from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from .account_store import (
    AccountStore,
    _normalize_consumer_account_id,
    extract_identity,
)
from .consumer_gate import _pick_cookies
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
    chromium_proxy_args,
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
from .refresh_via_rt import (
    M365_DESIGNER_SCOPE,
    M365_MEDIA_SCOPE,
    mint_scoped_token,
    refresh_via_rt,
)
from .runtime_flags import elog, ulog



# How many seconds before token expiry we proactively refresh. Matches the
# single-tenant --refresh-before-seconds default so behaviour stays familiar.
_REFRESH_BEFORE_SECONDS = 300
# Fallback TTL for the designer auth token (a raw JWE we cannot decode for its
# real exp): treat it as stale once it ages past this since last capture. media
# tokens are Bearer JWTs and use their own exp instead. Kept conservative so a
# lazy re-capture happens before the token actually lapses mid-session.
_MEDIA_TOKEN_TTL_SECONDS = 45 * 60
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
# How old a consumer credential may get before keepalive re-mints it. The ChatAI
# token is an opaque JWE with no readable exp, so age since capture is the only
# signal available; an hour keeps it well inside any plausible lifetime while
# costing one ~7s browser launch per account per hour.
_CONSUMER_KEEPALIVE_AGE_SECONDS = 60 * 60
# Backoff after a failed consumer refresh. Failure normally means the MSA session
# in the profile lapsed, which only an interactive sign-in fixes, so retrying
# hard would spin a browser for nothing.
_CONSUMER_RETRY_SECONDS = 30 * 60


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
        self._cdp_refresh_generation: dict[str, int] = {}
        self._cdp_refresh_result: dict[str, bool] = {}
        # Background keepalive task handle + stop flag (set on app shutdown).
        self._keepalive_task: asyncio.Task | None = None
        self._keepalive_stop: asyncio.Event | None = None
        # Tunable keepalive params (seconds); default to the module constants and
        # are overridden from admin runtime settings via set_keepalive_params().
        self._keepalive_interval_seconds: float = _KEEPALIVE_CHECK_INTERVAL_SECONDS
        self._cookie_keepalive_before_seconds: float = _COOKIE_KEEPALIVE_BEFORE_SECONDS
        # Last self-heal (cookie re-inject) attempt per account, for backoff.
        self._recovery_attempted_at: dict[str, float] = {}
        # Last consumer (Camoufox) refresh attempt per account, for backoff. A
        # lapsed MSA session cannot be recovered without a human, so a failing
        # account must not relaunch a browser on every keepalive tick.
        self._consumer_attempted_at: dict[str, float] = {}
        # Injected in tests; None means "build the real Camoufox gate on demand".
        self._consumer_gate_factory = None

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

    def _consumer_profile_dir(
        self, account_id: str, consumer_account_id: str = ""
    ) -> Path:
        """Per-Microsoft-subject Camoufox profile, apart from Chromium ones.

        Hashing keeps the private MSAL subject out of the filesystem while a
        subject change naturally selects a clean profile instead of reusing the
        previous personal account's cookies/localStorage.
        """
        subject = _normalize_consumer_account_id(consumer_account_id)
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
        return self._profile_root / f"{account_id}-consumer-{digest}"

    def _clear_consumer_profiles(self, account_id: str) -> None:
        """Remove current and legacy Camoufox profiles for one proxy account."""
        from .consumer_camoufox import reset_consumer_profile

        if not self._profile_root.exists():
            return
        prefix = f"{account_id}-consumer"
        for candidate in self._profile_root.iterdir():
            if candidate.name == prefix or candidate.name.startswith(f"{prefix}-"):
                reset_consumer_profile(candidate)

    async def clear_account_credentials(self, account_id: str) -> bool:
        """Clear stored credentials and any persisted consumer browser session."""
        async with self._account_lock(account_id):
            account = self._accounts.get(account_id)
            if account is None:
                return False
            self._clear_consumer_profiles(account_id)
            cleared = self._accounts.clear_credentials(account_id) is not None
            return cleared

    async def remove_account(
        self,
        account_id: str,
        *,
        can_remove: Callable[[], bool] | None = None,
    ) -> bool:
        """Remove an account without leaving its Microsoft session on disk."""
        async with self._account_lock(account_id):
            account = self._accounts.get(account_id)
            if account is None:
                return False
            if can_remove is not None and not can_remove():
                return False
            self._clear_consumer_profiles(account_id)
            removed = self._accounts.remove(account_id)
            return removed

    def _consumer_keepalive_due(self, account) -> bool:
        """True if a consumer account's credential is stale enough to re-mint."""
        if getattr(account, "provider", "m365") != "consumer":
            return False
        # Nothing captured yet means no MSA session to silently renew from; the
        # first credential has to arrive from the userscript push.
        if not getattr(account, "consumer_token", ""):
            return False
        if not _normalize_consumer_account_id(
            getattr(account, "consumer_account_id", "")
        ):
            return False
        last_attempt = self._consumer_attempted_at.get(account.id, 0.0)
        if time.time() - last_attempt < _CONSUMER_RETRY_SECONDS:
            return False
        captured = getattr(account, "consumer_updated_at", 0.0) or 0.0
        return time.time() - captured >= _CONSUMER_KEEPALIVE_AGE_SECONDS

    def _build_consumer_gate(self, account_id: str, account=None):
        if self._consumer_gate_factory is not None:
            return self._consumer_gate_factory(account_id)
        from .account_store import resolve_account_proxy
        from .consumer_camoufox import CamoufoxConsumerGate

        account = account or self._accounts.get(account_id)
        consumer_account_id = _normalize_consumer_account_id(
            getattr(account, "consumer_account_id", "")
        )
        return CamoufoxConsumerGate(
            self._consumer_profile_dir(account_id, consumer_account_id),
            seed_cookies=list(getattr(account, "cookies", []) or []),
            previous_token=str(getattr(account, "consumer_token", "") or ""),
            proxy_url=resolve_account_proxy(account),
        )

    async def refresh_consumer(self, account_id: str) -> bool:
        """Re-mint one consumer account's credentials with an unattended browser.

        Returns False (rather than raising) when the refresh cannot run or does
        not succeed: the stored credential may well still work, so a failure here
        is a missed opportunity, not a reason to fail the caller's request.
        """
        account = self._accounts.get(account_id)
        if account is None or getattr(account, "provider", "m365") != "consumer":
            return False
        from .consumer_camoufox import CamoufoxUnavailable, reset_consumer_profile

        ulog(f"Consumer refresh requested for {account_id}; waiting for browser slot")
        self._consumer_attempted_at[account_id] = time.time()
        # The global lock keeps this from running alongside a Chromium refresh --
        # two browsers at once is what the single-browser invariant exists to
        # avoid, and the box may not have RAM for both.
        async with self._account_lock(account_id):
            account = self._accounts.get(account_id)
            if account is None or getattr(account, "provider", "m365") != "consumer":
                return False
            expected_account_id = _normalize_consumer_account_id(
                getattr(account, "consumer_account_id", "")
            )
            if not expected_account_id:
                elog(
                    f"Consumer refresh skipped for {account_id}: no pinned Microsoft account id; re-push from the userscript"
                )
                return False
            snapshot = (
                account.consumer_updated_at,
                account.consumer_token,
                expected_account_id,
            )
            previous_identity_type = getattr(
                account, "consumer_identity_type", ""
            )
            gate = self._build_consumer_gate(account_id, account)
            async with self._lock:
                ulog(f"Consumer refresh starting Camoufox for {account_id}")
                try:
                    auth = await gate()
                except CamoufoxUnavailable as exc:
                    elog(f"Consumer refresh unavailable for {account_id}: {exc}")
                    return False
                except Exception as exc:  # noqa: BLE001 - browser failures vary
                    elog(f"Consumer refresh failed for {account_id}: {exc}")
                    return False
            token = str(auth.get("access_token") or "").strip()
            if not token:
                elog(f"Consumer refresh for {account_id} returned no token")
                return False
            if token == snapshot[1]:
                elog(f"Consumer refresh for {account_id} returned the previous token")
                return False
            actual_account_id = _normalize_consumer_account_id(
                auth.get("account_id")
            )
            if actual_account_id != expected_account_id:
                reset_consumer_profile(
                    self._consumer_profile_dir(account_id, expected_account_id)
                )
                elog(
                    f"Consumer refresh rejected for {account_id}: Microsoft account mismatch or missing identity"
                )
                return False
            cookies = auth.get("cookies") or []
            cookie_list = [
                dict(cookie) for cookie in cookies if isinstance(cookie, dict)
            ]
            if not _pick_cookies(cookie_list):
                elog(
                    f"Consumer refresh for {account_id} returned no reusable cookies"
                )
                return False
            stored = self._accounts.set_consumer_auth(
                account_id,
                cookie_list,
                token,
                str(auth.get("identity_type") or "") or previous_identity_type,
                consumer_account_id=expected_account_id,
                expected_snapshot=snapshot,
            )
            if stored is None:
                elog(
                    f"Consumer refresh discarded for {account_id}: credentials changed while the browser was running"
                )
                return False
            ulog(
                f"Consumer refresh for {account_id}: re-minted {len(cookie_list)} cookies"
            )
            return True

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
                    if self._consumer_keepalive_due(account):
                        # Consumer accounts hold an opaque token we cannot check
                        # for expiry, so keepalive re-mints on age instead. This
                        # is what keeps the MSA session in the profile warm.
                        ulog(f"Keepalive: re-minting consumer {account.id}")
                        try:
                            await self.refresh_consumer(account.id)
                        except Exception as exc:
                            elog(f"Keepalive consumer refresh error for {account.id}: {exc}")
                    elif self._keepalive_due(account):
                        ulog(f"Keepalive: refreshing {account.id} (cookie near expiry)")
                        try:
                            # force=True so a still-valid-but-soon-to-expire token is
                            # refreshed now. ensure_fresh serialises via the global lock.
                            await self.ensure_fresh(
                                account.id, force=True, allow_rt=False
                            )
                        except Exception as exc:
                            elog(f"Keepalive refresh error for {account.id}: {exc}")
                    elif self._recovery_due(account):
                        # Self-heal a stuck (cookie_valid=False) account. force=True
                        # routes into _refresh_one, which now re-injects the stored
                        # cookies AND captures a token in that same live session --
                        # the same proven path as the manual cookie-refresh button
                        # the user confirmed recovers the session (not just a bare
                        # cookie re-inject: this also gets a usable token back).
                        self._recovery_attempted_at[account.id] = time.time()
                        ulog(f"Keepalive: self-heal refreshing {account.id} (cookie invalid)")
                        try:
                            ok = await self.ensure_fresh(
                                account.id, force=True, allow_rt=False
                            )
                            ulog(f"Keepalive self-heal for {account.id}: {'recovered' if ok else 'still failing'}")
                        except Exception as exc:
                            elog(f"Keepalive self-heal error for {account.id}: {exc}")
            except Exception as exc:
                elog(f"Keepalive loop iteration error: {exc}")
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

    def _media_token_stale(self, token: str, updated_at: float) -> bool:
        """True when a media/designer auth token is missing or near/at expiry.

        media is a Bearer JWT (decodable -> use its exp); designer is a raw JWE
        that we cannot decode, so fall back to an age-based heuristic from when
        it was last captured. Either way an empty token is always stale.
        """
        if not token:
            return True
        try:
            from .token_store import decode_jwt_payload

            exp = int(decode_jwt_payload(token).get("exp", 0))
            if exp:
                return time.time() > exp - _REFRESH_BEFORE_SECONDS
        except Exception:
            pass
        # Undecodable (e.g. designer JWE): treat as stale once it ages past the
        # fallback TTL from its last capture.
        if updated_at <= 0:
            return True
        return time.time() - updated_at > _MEDIA_TOKEN_TTL_SECONDS

    async def ensure_media_fresh(self, account_id: str, url: str) -> None:
        """Lazily refresh the media/designer auth token before a media fetch.

        Preferred path: the media and designer tokens are the same client as the
        substrate token with a different audience, so a stored refresh token can
        mint them over plain HTTP (mint_scoped_token). Fallback, for accounts that
        only have a browser session: media/designer tokens only surface as live
        request headers when the SPA re-fetches media, so re-run the proven cookie
        re-injection (which navigates the seed conversation and captures the auth
        headers at the end). Best-effort: any failure just leaves the fetch to
        fall back to the Chromium image path as before.
        """
        account = self._accounts.get(account_id)
        if account is None:
            return
        is_designer = _is_designer_media_url(url)
        if is_designer:
            stale = self._media_token_stale(account.designer_auth_token, account.designer_auth_updated_at)
        else:
            stale = self._media_token_stale(account.media_auth_token, account.media_auth_updated_at)
        if not stale:
            return
        if await self._try_mint_media_token(account_id, is_designer=is_designer):
            return
        seed_url = (getattr(account, "media_seed_url", "") or "").strip()
        if not seed_url:
            return
        stored_cookies = list(getattr(account, "cookies", []) or [])
        if not stored_cookies:
            return
        ulog(
            f"Lazy media keepalive for {account_id}: "
            f"{'designer' if is_designer else 'media'} token stale, re-capturing via seed"
        )
        async with self._account_lock(account_id):
            async with self._lock:
                try:
                    await self._inject_cookies_one(account_id, stored_cookies, allow_nudge=True)
                except Exception as exc:
                    elog(f"Lazy media keepalive failed for {account_id}: {exc}")

    async def _try_mint_media_token(self, account_id: str, *, is_designer: bool) -> bool:
        """Mint one media/designer token from the stored RT. No browser involved.

        Returns False (quietly, for a missing RT) so the caller falls back to the
        cookie/CDP capture that browser-session accounts still depend on.
        """
        account = self._accounts.get(account_id)
        if account is None or not (getattr(account, "refresh_token", "") or "").strip():
            return False
        kind = "designer" if is_designer else "media"
        async with self._account_lock(account_id):
            token, error = await mint_scoped_token(
                self._accounts,
                account_id,
                M365_DESIGNER_SCOPE if is_designer else M365_MEDIA_SCOPE,
            )
            if error:
                elog(f"Minting {kind} token for {account_id} from the stored RT failed: {error}")
                return False
            if is_designer:
                self._accounts.set_designer_auth_token(account_id, token)
            else:
                self._accounts.set_media_auth_token(account_id, token)
        ulog(f"Lazy media keepalive for {account_id}: minted a {kind} token from the stored RT")
        return True

    async def _try_rt_refresh(self, account_id: str, *, force: bool = False) -> bool:
        """Attempt the fast HTTP refresh_token exchange (no browser).

        Serialised per-account (not through the global Chromium lock, since this
        is plain HTTP and never launches a browser). Returns True only when a
        fresh substrate token was obtained and persisted. A False result -- no
        stored RT, dead RT chain, or any error -- lets the caller fall back to
        the CDP refresh path.
        """
        account = self._accounts.get(account_id)
        if account is None or not (getattr(account, "refresh_token", "") or "").strip():
            return False
        refresh_token_snapshot = account.refresh_token
        access_token_snapshot = account.token
        if float(getattr(account, "refresh_token_retry_after", 0.0) or 0.0) > time.time():
            return False
        async with self._account_lock(account_id):
            current = self._accounts.get(account_id)
            if current is None:
                return False
            # A concurrent refresh or userscript push already changed the
            # credential snapshot while we waited. Reuse its fresh result rather
            # than exchanging the old RT a second time.
            if (
                current.refresh_token != refresh_token_snapshot
                or current.token != access_token_snapshot
            ):
                return bool(current.token) and not self._needs_refresh(current.token)
            if float(
                getattr(current, "refresh_token_retry_after", 0.0) or 0.0
            ) > time.time():
                return False
            if not force and not self._needs_refresh(current.token):
                return True
            return await refresh_via_rt(self._accounts, account_id)

    @staticmethod
    def _cdp_refresh_state(account) -> tuple[str, bool, float, float]:
        return (
            account.token,
            bool(account.cookie_valid),
            float(account.cookie_updated_at),
            float(account.cookie_expires_at),
        )

    async def _run_cdp_refresh(
        self,
        account_id: str,
        *,
        force: bool,
        expected_state: tuple[str, bool, float, float],
    ) -> bool:
        """Run one CDP fallback and coalesce concurrent waiters."""
        attempt_generation = self._cdp_refresh_generation.get(account_id, 0)
        async with self._account_lock(account_id):
            current = self._accounts.get(account_id)
            if current is None:
                return False
            if self._cdp_refresh_generation.get(account_id, 0) != attempt_generation:
                if (
                    current.token != expected_state[0]
                    and bool(current.token)
                    and not self._needs_refresh(current.token)
                ):
                    return True
                return self._cdp_refresh_result.get(account_id, False)
            if self._cdp_refresh_state(current) != expected_state:
                return bool(current.token) and not self._needs_refresh(current.token)
            if not force and not self._needs_refresh(current.token):
                return True
            result = False
            try:
                async with self._lock:
                    result = await self._refresh_one(account_id)
                return result
            finally:
                self._cdp_refresh_generation[account_id] = attempt_generation + 1
                self._cdp_refresh_result[account_id] = result

    async def ensure_fresh(
        self, account_id: str, force: bool = False, *, allow_rt: bool = True
    ) -> bool:
        """Ensure the account's token is valid, refreshing on demand if needed.

        Returns True if the token is usable afterwards, False otherwise. Safe to
        call on every request: it's a cheap no-op when the token is still valid.
        """
        account = self._accounts.get(account_id)
        if account is None:
            elog(f"Refresh skipped: account {account_id} not found")
            return False
        # Consumer (personal-account) Copilot has no substrate token and no
        # refresh_token grant, so every path below -- RT exchange, cookie replay,
        # CDP capture -- is meaningless for it. Guarding here rather than in the
        # keepalive predicates covers the admin "Refresh" button too, since this
        # is the single entry point all of them share.
        if getattr(account, "provider", "m365") != "m365":
            # A forced refresh (admin button / keepalive) re-mints through the
            # unattended browser gate. The passive /v1 path deliberately does not:
            # the stored token is opaque, so we have no reason to believe it is
            # dead, and a ~7s browser launch in front of a live request would be
            # a guaranteed cost against a speculative benefit. Expiry surfaces
            # upstream as ClearanceRequired, which is where recovery belongs.
            if force and await self.refresh_consumer(account_id):
                return True
            return bool(getattr(account, "consumer_token", ""))
        cdp_refresh_state = self._cdp_refresh_state(account)
        # Fast path: if the account carries an OAuth2 refresh_token, try the
        # plain-HTTP substrate exchange first (no headless Chromium, no Copilot
        # quota spend). Only runs when a refresh is actually due (or forced).
        # On success we're done; on failure we fall through to the CDP path.
        if (
            allow_rt
            and (getattr(account, "refresh_token", "") or "").strip()
            and (force or self._needs_refresh(account.token))
        ):
            if await self._try_rt_refresh(account_id, force=force):
                return True
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
                    elog(f"Refresh skipped: account {account_id} is manual and its token is expired (no auto-refresh profile)")
                    return False
                return bool(account.token)
            ulog(f"Forced refresh on manual account {account_id}: attempting CDP capture from its profile")
            return await self._run_cdp_refresh(
                account_id,
                force=force,
                expected_state=cdp_refresh_state,
            )
        if not force and not self._needs_refresh(account.token):
            return True

        return await self._run_cdp_refresh(
            account_id,
            force=force,
            expected_state=cdp_refresh_state,
        )

    async def inject_cookies(self, account_id: str, cookies: list[dict], *, allow_nudge: bool = False) -> tuple[int, int]:
        # allow_nudge=True drives a full token capture (substrate + media/designer
        # keys + media_seed navigation) in the SAME injected session, exactly like
        # the /v1 wake-up refresh. The admin "cookie refresh" button passes True so
        # it always re-mints all three keys regardless of the RT path; the user
        # self-service push keeps False so its awaited response returns fast (token
        # is filled in by the detached _spawn_post_push_refresh task instead).
        account = self._accounts.get(account_id)
        if account is None or not cookies:
            return 0, len(cookies or [])
        async with self._account_lock(account_id):
            async with self._lock:
                return await self._inject_cookies_one(account_id, cookies, allow_nudge=allow_nudge)

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
        # Lazy media keepalive: media/designer auth tokens are not produced by the
        # RT/HTTP substrate refresh, so top them up on demand right before we need
        # them (only fires when stale + a media_seed_url + cookies exist). Runs
        # before auth-header computation so a freshly captured token is used.
        await self.ensure_media_fresh(account_id, fetch_url)
        account = self._accounts.get(account_id) or account
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
            elog(f"Refresh failed: account {account_id} not found")
            return False
        # Preferred path: re-inject stored cookies + seed MSAL localStorage and
        # capture the token in that SAME live session. Runtime evidence: the
        # injection session (plain /chat + seeded MSAL account keys) reliably
        # reaches an established login (shell=False), while a bare profile reopen
        # navigates to chat?login_hint and degrades to an interactive popup that
        # dead-ends on spalanding#code (repeated /v1 503s). So capture HERE,
        # where the seeded account makes silent SSO work; bare reopen is fallback.
        stored_cookies = list(getattr(account, "cookies", []) or [])
        if stored_cookies:
            try:
                await self._inject_cookies_one(account_id, stored_cookies, allow_nudge=True)
            except Exception as exc:
                elog(f"Refresh via cookie re-injection errored for {account_id}: {exc}")
            refreshed = self._accounts.get(account_id) or account
            if refreshed.token and not self._needs_refresh(refreshed.token):
                ulog(f"Refresh succeeded for {account_id}: token captured during cookie re-injection")
                return True
            elog(f"Refresh via cookie re-injection did not yield a fresh token for {account_id}; falling back to bare profile reopen")
        profile_dir = self._profile_root / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_profile_locks(profile_dir)
        proc = None
        try:
            proc = subprocess.Popen([
                _chromium_path(),
                f"--remote-debugging-port={account.cdp_port}",
                f"--user-data-dir={profile_dir}",
                *chromium_proxy_args(),
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
            elog(f"Refresh failed for {account_id}: Chromium launch error: {exc}")
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
                elog(f"Refresh failed for {account_id}: M365 page not ready on CDP port {account.cdp_port}; tabs: {tabs}")
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
                        ulog(f"Refresh login diagnostic for {account_id}: {diag}")
                except Exception as exc:
                    elog(f"Refresh login diagnostic skipped for {account_id}: {exc}")
                elog(f"Refresh failed for {account_id}: no fresh substrate token captured from CDP port {account.cdp_port}; tabs: {tabs}")
                return False
            # Identity guard: the persistent profile can retain another account's
            # session, so a captured token may belong to the wrong identity. Never
            # overwrite an established account with a mismatched identity.
            if _identity_conflict(account.email, token):
                _, captured_email = extract_identity(token)
                self._accounts.set_cookie_status(account_id, False)
                elog(f"Refresh rejected for {account_id}: identity mismatch (account={account.email!r}, captured={captured_email!r})")
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
                    ulog(f"Refresh harvested resource tokens for {account_id}: {sorted(resources.keys())}")
            except Exception as exc:
                elog(f"Refresh resource-token harvest skipped for {account_id}: {exc}")
            ulog(f"Refresh succeeded for {account_id}: token updated from CDP")
            return True
        except Exception as exc:
            elog(f"Refresh failed for {account_id}: {exc}")
            return False
        finally:
            await _close_chromium_gracefully(account.cdp_port, proc)
            await asyncio.sleep(1)
            _cleanup_profile_locks(profile_dir)
