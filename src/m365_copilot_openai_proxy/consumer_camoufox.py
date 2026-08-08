"""Re-mint consumer-Copilot credentials on demand with a Camoufox browser.

The Edge/CDP gate in consumer_gate.py drives a real chat turn through interactive
Cloudflare verification, which needs a human to click. This gate does something
narrower and unattended: it launches a Firefox-based browser against a persisted
profile, lets MSAL's silent SSO re-mint the ChatAI access token, exports the
cookie jar, and shuts the browser down. Nothing is clicked and no chat turn is
sent, so there is nothing for Turnstile to gate.

Two settings are load-bearing, both established by measurement:

1. Cookie partitioning must be off. MSAL's silent flow is an iframe to
   login.live.com, and Firefox's default Total Cookie Protection partitions
   third-party state by top-level site, so the iframe cannot see the
   `__Host-MSAAUTHP` / `WLSSC` cookies that prove the MSA session. The page then
   falls back to the sign-in wall and no token is ever minted. Chromium has no
   equivalent behaviour, which is why this only bites the Firefox path.

2. Cloudflare cookies must not cross between clients, in either direction.
   `__cf_bm` is bound to the UA that earned it, so a Chromium-issued one replayed
   under Firefox is a mismatch rather than a help -- and by the same rule the one
   this browser earns must not be handed to the curl_cffi client, which
   impersonates a different Firefox version and earns its own on the warmup GET
   that opens every turn.

A cold launch against a warm profile re-mints in ~6.7s end to end, and it is a
real mint rather than a cache read: wiping the MSAL cache out of localStorage and
reloading produces a new token value without any redirect to a login page. That
is what makes this viable as a refresh -- it keeps working after the cached token
expires, for as long as the MSA session in the profile stays alive.

Camoufox is an optional dependency (a ~936 MB browser). When it is not installed
this module raises CamoufoxUnavailable and callers fall back to the existing
"user re-pushes from the userscript" flow.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
import weakref
from pathlib import Path

from .consumer_client import ConsumerCopilotError
from .consumer_gate import _pick_cookies
from .runtime_flags import elog, ulog

COPILOT_URL = "https://copilot.microsoft.com/"

# Firefox prefs that undo Total Cookie Protection for this profile. Scoped to a
# purpose-built automation profile, so this weakens nothing a user browses with.
_UNPARTITIONED_PREFS: dict[str, object] = {
    "network.cookie.cookieBehavior": 0,
    "privacy.partition.network_state": False,
    "privacy.partition.always_partition_third_party_non_cookie_storage": False,
    "privacy.trackingprotection.enabled": False,
}

# Mirrors consumer_gate._FIND_CHAT_TOKEN_JS: the MSAL cache keys are opaque, so
# find the AccessToken entry whose target names the ChatAI scope.
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

# Firefox allows one process per profile and enforces it with an on-disk lock, so
# concurrent refreshes for one account must serialise rather than race.
_GATE_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

_LOCK_FILES = (".parentlock", "lock", "parent.lock")

# Cloudflare's bot-management cookies are bound to the client that earned them.
# _pick_cookies filters by domain alone, so they survive it; drop them by name.
_CLOUDFLARE_COOKIE_PREFIXES = ("__cf", "cf_clearance")


def _drop_cloudflare_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Strip Cloudflare cookies from a jar about to change hands.

    The consumer HTTP client impersonates firefox147 while this browser is
    Firefox 152, so handing over a `__cf_bm` minted here means replaying it under
    a UA that did not earn it -- the same mismatch that makes injecting Edge's
    copy actively harmful. The client's per-turn warmup GET earns its own.
    """
    return {
        name: value
        for name, value in cookies.items()
        if not name.startswith(_CLOUDFLARE_COOKIE_PREFIXES)
    }


class CamoufoxUnavailable(ConsumerCopilotError):
    """Camoufox is not installed, so the unattended refresh path is disabled."""


def _gate_lock(profile_dir: Path) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _GATE_LOCKS.setdefault(loop, {})
    return locks.setdefault(str(profile_dir.resolve()), asyncio.Lock())


def camoufox_available() -> bool:
    """True if the Camoufox package is importable."""
    try:
        import camoufox.async_api  # noqa: F401
    except Exception:  # noqa: BLE001 - a broken install is as good as absent
        return False
    return True


def _clear_profile_locks(profile_dir: Path) -> None:
    """Drop stale Firefox profile locks left by a killed browser.

    Without this a crashed refresh poisons the profile: the next launch waits on
    the lock until Playwright's 180s timeout instead of failing fast.
    """
    for name in _LOCK_FILES:
        try:
            (profile_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def _default_headless() -> bool | str:
    """Pick the headless mode that fits the host.

    True headless Firefox is itself a detectable signal, and not being detected
    is the whole reason this path uses Firefox, so a virtual display is the
    better choice where one can exist. That means Linux: the image installs xvfb,
    which Camoufox drives for "virtual". Windows and macOS have no xvfb, so they
    get real headless -- and a developer box is not what needs to slip past
    detection anyway.
    """
    return "virtual" if sys.platform.startswith("linux") else True


def _proxy_option() -> dict | None:
    """Playwright proxy config from the same env the Chromium paths read.

    socks5h/socks4a are a curl convention meaning "resolve DNS at the proxy";
    Firefox does not parse those schemes, and its socks5 already resolves
    remotely, so mapping them across is an equivalence rather than a downgrade.
    """
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if not proxy:
        return None
    scheme, sep, rest = proxy.partition("://")
    mapped = {"socks5h": "socks5", "socks4a": "socks4"}.get(scheme.lower())
    if sep and mapped:
        proxy = f"{mapped}://{rest}"
    return {"server": proxy}


class CamoufoxConsumerGate:
    """Unattended consumer-credential refresh, shaped like ConsumerBrowserGate.

    Returns the same ``{cookies, access_token, identity_type}`` mapping so it can
    stand in wherever that gate is accepted.
    """

    def __init__(
        self,
        profile_dir: Path | str,
        *,
        headless: bool | str | None = None,
        timeout: float = 60.0,
        token_timeout: float = 45.0,
        poll_interval: float = 0.25,
    ):
        self._profile_dir = Path(profile_dir)
        self._headless = _default_headless() if headless is None else headless
        self._timeout = timeout
        self._token_timeout = token_timeout
        self._poll_interval = poll_interval

    async def __call__(self) -> dict:
        async with _gate_lock(self._profile_dir):
            return await self._refresh()

    async def _refresh(self) -> dict:
        try:
            from camoufox.async_api import AsyncCamoufox
        except Exception as exc:  # noqa: BLE001 - import errors vary by platform
            raise CamoufoxUnavailable(
                "Camoufox is not installed, so consumer credentials cannot be "
                "refreshed without a human. Re-push them from the userscript, or "
                "install the camoufox extra to enable unattended refresh."
            ) from exc

        self._profile_dir.mkdir(parents=True, exist_ok=True)
        _clear_profile_locks(self._profile_dir)
        started = time.monotonic()
        try:
            auth = await asyncio.wait_for(
                self._run(AsyncCamoufox), timeout=self._timeout
            )
        except asyncio.TimeoutError as exc:
            # A timeout leaves the browser mid-shutdown; clear the lock so the
            # next attempt is not stuck behind it.
            _clear_profile_locks(self._profile_dir)
            raise ConsumerCopilotError(
                f"Camoufox consumer refresh timed out after {self._timeout:.0f}s."
            ) from exc
        ulog(
            f"Camoufox consumer refresh: token {len(auth['access_token'])} chars, "
            f"{len(auth['cookies'])} cookies in {time.monotonic() - started:.1f}s"
        )
        return auth

    async def _run(self, browser_factory) -> dict:
        async with browser_factory(
            headless=self._headless,
            persistent_context=True,
            user_data_dir=str(self._profile_dir.resolve()),
            os="windows",
            humanize=True,
            geoip=True,
            firefox_user_prefs=dict(_UNPARTITIONED_PREFS),
            proxy=_proxy_option(),
        ) as browser:
            page = await browser.new_page()
            await page.goto(COPILOT_URL, wait_until="domcontentloaded", timeout=60_000)
            token = await self._await_token(page)
            if not token:
                raise ConsumerCopilotError(
                    "Camoufox loaded Copilot but MSAL minted no ChatAI token within "
                    f"{self._token_timeout:.0f}s. The signed-in session in "
                    f"{self._profile_dir.name} has most likely lapsed and needs one "
                    "interactive sign-in."
                )
            cookies = _drop_cloudflare_cookies(_pick_cookies(await browser.cookies()))
        return {
            "cookies": cookies,
            "access_token": token,
            # The token is minted by MSAL rather than lifted from a chat socket
            # URL, so no X-UserIdentityType is observed here. Callers keep the
            # value they already hold.
            "identity_type": "",
        }

    async def _await_token(self, page) -> str:
        deadline = asyncio.get_running_loop().time() + self._token_timeout
        while True:
            try:
                token = await page.evaluate(_FIND_CHAT_TOKEN_JS)
            except Exception as exc:  # noqa: BLE001 - navigation can race evaluate
                elog(f"Camoufox token read failed, retrying: {exc}")
                token = ""
            if token:
                return str(token)
            if asyncio.get_running_loop().time() >= deadline:
                return ""
            await asyncio.sleep(self._poll_interval)


def reset_consumer_profile(profile_dir: Path | str) -> None:
    """Delete a consumer automation profile so the next sign-in starts clean."""
    path = Path(profile_dir)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
