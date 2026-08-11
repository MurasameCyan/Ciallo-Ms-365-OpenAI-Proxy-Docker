"""Re-mint consumer-Copilot credentials on demand with a Camoufox browser.

The Edge/CDP gate in consumer_gate.py drives a real chat turn through interactive
Cloudflare verification, which needs a human to click. This gate does something
narrower and unattended: it launches a Firefox-based browser seeded from the
latest stored cookie snapshot, lets MSAL's silent SSO re-mint the ChatAI access
token, exports the refreshed cookie jar, and shuts the browser down. Nothing is
clicked and no chat turn is sent, so there is nothing for Turnstile to gate.

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

A cold launch re-mints in ~6.7s end to end, and it is a real mint rather than a
cache read: wiping the ChatAI token from MSAL localStorage and reloading produces
a new token value without any redirect to a login page. The scheduler keys each
profile by a hash of the MSAL account id and rejects a mint from any other id,
so one proxy binding cannot silently cross into another personal account.

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

from .account_store import _normalize_consumer_account_id
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
      if (token && token.secret && token.target && token.target.includes('ChatAI')) {
        const home = String(token.homeAccountId || token.home_account_id || '').toLowerCase();
        const local = String(token.localAccountId || token.local_account_id || '').toLowerCase();
        return {
          access_token: token.secret,
          account_id: home ? 'home:' + home : (local ? 'local:' + local : ''),
        };
      }
    } catch (error) {}
  }
  return {access_token: '', account_id: ''};
})() /* consumer:chat-token */
"""

_CLEAR_CHAT_TOKEN_JS = """
(() => {
  const keys = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    const value = localStorage.getItem(key);
    if (!value || !value.includes('"credentialType":"AccessToken"')) continue;
    try {
      const token = JSON.parse(value);
      if (token && token.credentialType === 'AccessToken' &&
          token.target && token.target.includes('ChatAI')) keys.push(key);
    } catch (error) {}
  }
  for (const key of keys) localStorage.removeItem(key);
  return keys.length;
})() /* consumer:clear-chat-token */
"""

# Firefox allows one process per profile and enforces it with an on-disk lock, so
# concurrent refreshes for one account must serialise rather than race.
_GATE_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

_LOCK_FILES = (".parentlock", "lock", "parent.lock")

# Cloudflare's bot-management cookies are bound to the client that earned them.
# _pick_cookies filters by domain alone, so they survive it; drop them by name.
_CLOUDFLARE_COOKIE_PREFIXES = ("__cf", "cf_clearance")
_CONSUMER_COOKIE_DOMAINS = (
    "copilot.microsoft.com",
    "microsoft.com",
    "microsoftonline.com",
    "bing.com",
    "live.com",
)


def _drop_cloudflare_cookies(cookies: list[dict]) -> list[dict]:
    """Strip Cloudflare cookies from a jar about to change hands.

    The consumer HTTP client impersonates firefox147 while this browser is
    Firefox 152, so handing over a `__cf_bm` minted here means replaying it under
    a UA that did not earn it -- the same mismatch that makes injecting Edge's
    copy actively harmful. The client's per-turn warmup GET earns its own.
    """
    return [
        dict(cookie)
        for cookie in cookies
        if not str(cookie.get("name") or "").startswith(_CLOUDFLARE_COOKIE_PREFIXES)
    ]


def _consumer_cookie_records(cookies: list[dict]) -> list[dict]:
    """Return Playwright-compatible consumer cookies without losing replay metadata."""
    records: list[dict] = []
    for raw in _drop_cloudflare_cookies(cookies):
        name = str(raw.get("name") or "")
        value = str(raw.get("value") or "")
        domain = str(raw.get("domain") or "").lower()
        bare_domain = domain.lstrip(".")
        if not name or not value or not domain:
            continue
        if not any(
            bare_domain == suffix or bare_domain.endswith(f".{suffix}")
            for suffix in _CONSUMER_COOKIE_DOMAINS
        ):
            continue
        record: dict[str, object] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": str(raw.get("path") or "/"),
        }
        for field in ("secure", "httpOnly"):
            if field in raw:
                record[field] = bool(raw[field])
        same_site = {
            "strict": "Strict",
            "lax": "Lax",
            "none": "None",
            "no_restriction": "None",
        }.get(str(raw.get("sameSite") or "").strip().lower().replace("-", "_"))
        if same_site:
            record["sameSite"] = same_site
        expires = raw.get("expires")
        if isinstance(expires, (int, float)):
            record["expires"] = expires
        records.append(record)
    return records


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


def _proxy_option(proxy_url: str = "") -> dict | None:
    """Playwright proxy config: the explicit override, else the proxy env.

    An account-level proxy must win over the env here. The credentials this
    browser mints are scored against the IP that earned them, so a re-mint has
    to leave through the same egress the chat turns will use.

    socks5h/socks4a are a curl convention meaning "resolve DNS at the proxy";
    Firefox does not parse those schemes, and its socks5 already resolves
    remotely, so mapping them across is an equivalence rather than a downgrade.
    """
    proxy = str(proxy_url or "") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if not proxy:
        return None
    scheme, sep, rest = proxy.partition("://")
    mapped = {"socks5h": "socks5", "socks4a": "socks4"}.get(scheme.lower())
    if sep and mapped:
        proxy = f"{mapped}://{rest}"
    return {"server": proxy}


class CamoufoxConsumerGate:
    """Unattended consumer-credential refresh, shaped like ConsumerBrowserGate.

    Returns ``{cookies, access_token, identity_type}``, keeping cookies as full
    browser records so a later refresh can seed a fresh profile again.
    """

    def __init__(
        self,
        profile_dir: Path | str,
        *,
        headless: bool | str | None = None,
        timeout: float = 60.0,
        token_timeout: float = 45.0,
        poll_interval: float = 0.25,
        seed_cookies: list[dict] | None = None,
        previous_token: str = "",
        proxy_url: str = "",
    ):
        self._profile_dir = Path(profile_dir)
        self._headless = _default_headless() if headless is None else headless
        self._timeout = timeout
        self._token_timeout = token_timeout
        self._poll_interval = poll_interval
        self._seed_cookies = [dict(cookie) for cookie in (seed_cookies or [])]
        self._previous_token = str(previous_token or "")
        self._proxy_url = str(proxy_url or "")

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
            proxy=_proxy_option(self._proxy_url),
        ) as browser:
            seed_cookies = _consumer_cookie_records(self._seed_cookies)
            if seed_cookies:
                await browser.add_cookies(seed_cookies)
            page = await browser.new_page()
            await page.goto(COPILOT_URL, wait_until="domcontentloaded", timeout=60_000)
            await page.evaluate(_CLEAR_CHAT_TOKEN_JS)
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
            token, account_id = await self._await_token(page)
            if not token:
                raise ConsumerCopilotError(
                    "Camoufox loaded Copilot but MSAL minted no ChatAI token within "
                    f"{self._token_timeout:.0f}s. The signed-in session in "
                    f"{self._profile_dir.name} has most likely lapsed and needs one "
                    "interactive sign-in."
                )
            cookies = _consumer_cookie_records(await browser.cookies())
            if not _pick_cookies(cookies):
                raise ConsumerCopilotError(
                    "Camoufox minted a token but returned no reusable consumer cookies."
                )
        return {
            "cookies": cookies,
            "access_token": token,
            "account_id": account_id,
            # The token is minted by MSAL rather than lifted from a chat socket
            # URL, so no X-UserIdentityType is observed here. Callers keep the
            # value they already hold.
            "identity_type": "",
        }

    async def _await_token(self, page) -> tuple[str, str]:
        deadline = asyncio.get_running_loop().time() + self._token_timeout
        while True:
            try:
                auth = await page.evaluate(_FIND_CHAT_TOKEN_JS)
            except Exception as exc:  # noqa: BLE001 - navigation can race evaluate
                elog(f"Camoufox token read failed, retrying: {exc}")
                auth = {}
            if isinstance(auth, dict):
                token = str(auth.get("access_token") or "")
                account_id = _normalize_consumer_account_id(auth.get("account_id"))
            else:
                token = str(auth or "")
                account_id = ""
            if token and str(token) != self._previous_token:
                return token, account_id
            if asyncio.get_running_loop().time() >= deadline:
                return "", ""
            await asyncio.sleep(self._poll_interval)


def reset_consumer_profile(profile_dir: Path | str) -> None:
    """Delete a consumer automation profile so the next sign-in starts clean."""
    path = Path(profile_dir)
    if path.exists():
        shutil.rmtree(path)
