from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .account_crypto import SENSITIVE_FIELDS, AccountCipher, load_or_create_key
from .atomic_write import write_text_atomic
from .token_store import decode_jwt_payload, is_substrate_token_claims


# Base CDP port for per-account Chromium profiles. Global admin CDP uses 9222,
# so account profiles live in a separate range to avoid writing to the wrong
# browser profile.
_CDP_PORT_BASE = 9322
_RESERVED_CDP_PORTS = {9222}
_EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)
_CONSUMER_ACCOUNT_ID_RE = re.compile(r"^(?:home|local):[a-z0-9._-]{1,512}$")
_STUDIO_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{3,512}$")


def _normalize_consumer_account_id(value: object) -> str:
    account_id = str(value or "").strip().lower()
    return account_id if _CONSUMER_ACCOUNT_ID_RE.fullmatch(account_id) else ""


def normalize_studio_agent_id(value: object) -> str:
    agent_id = str(value or "").strip()
    return agent_id if _STUDIO_AGENT_ID_RE.fullmatch(agent_id) else ""


def _studio_subject(token: str) -> tuple[str, str]:
    try:
        claims = decode_jwt_payload(token)
    except Exception:
        return "", ""
    if not is_substrate_token_claims(claims):
        return "", ""
    tenant_id = str(claims.get("tid") or "").strip()
    object_id = str(claims.get("oid") or "").strip()
    return (tenant_id, object_id) if tenant_id and object_id else ("", "")


def _clear_studio_agent_binding(account: "Account") -> None:
    account.studio_agent_id = ""
    account.studio_agent_tenant_id = ""
    account.studio_agent_object_id = ""


def _clear_studio_binding_if_subject_changed(account: "Account", token: str) -> None:
    if not account.studio_agent_id:
        return
    tenant_id, object_id = _studio_subject(token)
    if (
        tenant_id != account.studio_agent_tenant_id
        or object_id != account.studio_agent_object_id
    ):
        _clear_studio_agent_binding(account)


def extract_identity(token: str) -> tuple[str, str]:
    """Best-effort (display_name, email) from a Substrate JWT's claims.

    The Tampermonkey push and CDP capture both carry a token whose claims hold
    the signed-in identity, so we can label pool accounts without extra input.
    Returns empty strings when nothing usable is found.
    """
    if not token:
        return "", ""
    try:
        claims = decode_jwt_payload(token)
    except Exception:
        return "", ""
    email = ""
    for key in ("email", "upn", "unique_name", "preferred_username"):
        val = claims.get(key)
        if isinstance(val, str) and "@" in val:
            email = val.strip()
            break
    name = claims.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name and email:
        name = email.split("@")[0]
    return name, email


@dataclass
class Account:
    """A single M365 Copilot account in the multi-tenant pool.

    Each account owns an isolated Substrate token plus a dedicated Chromium
    profile / CDP port so the refresh scheduler can bring its debug browser up
    on demand (and tear it down afterwards) without colliding with others.
    """

    id: str = field(default_factory=lambda: "acct_" + uuid.uuid4().hex[:12])
    name: str = ""
    email: str = ""
    token: str = ""
    cookie_valid: bool = False
    cookie_updated_at: float = 0.0
    cookie_expires_at: float = 0.0
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, Any] = field(default_factory=dict)
    media_auth_token: str = ""
    media_auth_updated_at: float = 0.0
    designer_auth_token: str = ""
    designer_auth_updated_at: float = 0.0
    # OAuth2 refresh_token (captured by the userscript from the token response).
    # Lets the scheduler refresh the substrate token over plain HTTP without a
    # headless browser. Rotated on every successful exchange. Never exposed via
    # public serializers (only has_refresh_token bool).
    refresh_token: str = ""
    refresh_token_updated_at: float = 0.0
    # Binding captured from the exact AAD token request/response that issued the
    # RT. A refresh token is opaque, so these fields are the only way to prevent
    # a token from another Microsoft client, tenant, or browser account from
    # being attached to this pool account.
    refresh_token_client_id: str = ""
    refresh_token_authority: str = ""
    refresh_token_tenant_id: str = ""
    refresh_token_object_id: str = ""
    refresh_token_retry_after: float = 0.0
    # A specific chat conversation URL (m365.cloud.microsoft/chat/conversation/..)
    # that contains media. The refresh flow navigates here to re-trigger the
    # asyncgw/teams/designer media fetches so their Authorization headers can be
    # captured. Never exposed via public serializers (only has_media_seed bool).
    media_seed_url: str = ""
    cdp_port: int = _CDP_PORT_BASE
    # Per-account outbound proxy. Empty => inherit the process-global proxy env
    # that apply_proxy_env() publishes from the admin setting. Exists because the
    # consumer and M365 providers need different egresses: measured 2026-08-12, a
    # real Firefox on this host's direct egress gets `challenge method=None` from
    # consumer Copilot, while M365 works direct. A process-global env var cannot
    # express that split.
    proxy_url: str = ""
    # Explicitly provisioned Copilot Studio agent for this real AAD subject.
    # All three values are encrypted at rest; serializers expose only readiness.
    studio_agent_id: str = ""
    studio_agent_tenant_id: str = ""
    studio_agent_object_id: str = ""
    # "m365" = enterprise Substrate account (everything above applies).
    # "consumer" = personal-account Copilot, authenticated by the ChatAI access
    # token + browser cookies below instead of a substrate JWT. None of the M365
    # refresh machinery applies; ensure_fresh short-circuits on this field.
    provider: str = "m365"
    # Opaque ChatAI access token lifted from the consumer chat WebSocket URL (or
    # the MSAL localStorage cache). Never exposed via public serializers (only
    # has_consumer_token bool).
    consumer_token: str = ""
    consumer_identity_type: str = ""
    # Stable MSAL subject (normally home:<homeAccountId>) used to keep one
    # proxy account pinned to the same personal Microsoft identity.
    consumer_account_id: str = ""
    consumer_updated_at: float = 0.0
    # Epoch seconds until which upstream said it will refuse this account's turns,
    # from the throttle frame's own nextAvailableAt. 0 = nothing recorded (and M365
    # never records: its throttle frame names no time). Persisted because the value
    # arrives inside one failed turn and is otherwise gone the moment that response
    # is written -- rediscovering the window costs another turn, which on consumer
    # is a real quota unit.
    throttled_until: float = 0.0
    # "manual" = token pushed by user (Tampermonkey / paste); "cdp" = auto-captured.
    token_source: str = "manual"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def studio_agent_ready(self) -> bool:
        if self.provider != "m365" or not normalize_studio_agent_id(self.studio_agent_id):
            return False
        tenant_id, object_id = _studio_subject(self.token)
        return bool(
            tenant_id
            and object_id
            and tenant_id == self.studio_agent_tenant_id
            and object_id == self.studio_agent_object_id
        )

    def token_status(self) -> dict[str, Any]:
        """Decode the JWT and report validity / expiry, mirroring AccessTokenStore.status()."""
        if self.provider == "consumer":
            # The ChatAI token is opaque to us -- no verifiable exp claim -- so
            # "valid" only means one is stored. Real expiry surfaces upstream as
            # a ClearanceRequired, which the unattended re-mint recovers from
            # (RefreshScheduler.refresh_consumer); age since capture is what
            # keepalive schedules on, since there is no exp to read.
            if not self.consumer_token:
                return {"valid": False, "error": "No consumer token", "expires_at": None, "seconds_remaining": 0}
            return {"valid": True, "expires_at": None, "seconds_remaining": 0}
        token = self.token
        now = time.time()
        if not token:
            return {"valid": False, "error": "No token", "expires_at": None, "seconds_remaining": 0}
        try:
            claims = decode_jwt_payload(token)
            if not is_substrate_token_claims(claims):
                return {
                    "valid": False,
                    "error": "Token is not a substrate.office.com token.",
                    "expires_at": None,
                    "seconds_remaining": 0,
                }
            expires_at = int(claims["exp"])
        except Exception as exc:  # noqa: BLE001 - report any decode failure to the UI
            return {"valid": False, "error": f"Cannot decode token: {exc}", "expires_at": None, "seconds_remaining": 0}
        seconds_remaining = max(0, expires_at - int(now))
        from datetime import datetime, timezone

        return {
            "valid": seconds_remaining > 0,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
            "seconds_remaining": seconds_remaining,
        }


class AccountStore:
    """Thread-safe account pool with best-effort JSON persistence."""

    def __init__(self, persist_path: str | Path | None = None):
        self._accounts: dict[str, Account] = {}
        self._lock = threading.RLock()
        self._persist_path = Path(persist_path) if persist_path else None
        self._cdp_port_base = _CDP_PORT_BASE
        # At-rest encryption for sensitive fields. The key lives next to the
        # accounts file (data/.enc_key); when cryptography is unavailable the
        # cipher degrades to a plaintext passthrough (see account_crypto).
        if self._persist_path is not None:
            key = load_or_create_key(self._persist_path.parent / ".enc_key")
        else:
            key = None
        self._cipher = AccountCipher(key)
        if self._persist_path is not None:
            self._load()

    # ------------------------------------------------------------------ IO
    def _load(self) -> None:
        # Same trust boundary as _read_runtime_settings' proxy_url handling: the
        # persisted file is hand-editable (and encryption is a no-op when
        # cryptography or the key is unavailable), so revalidate here instead of
        # trusting whatever string is on disk. Imported inside the function to
        # match set_proxy_url and keep this low-level module's import graph free
        # of runtime_settings.
        from .runtime_settings import normalize_proxy_url

        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return
        changed = False
        for acc_id, raw in data.items():
            if not isinstance(raw, dict):
                continue
            # Decrypt sensitive fields in place. A field may be an encrypted
            # envelope (new format) or legacy plaintext (pre-encryption); a
            # field that fails to decrypt is dropped to its default rather than
            # crashing the whole load.
            for fname in SENSITIVE_FIELDS:
                if fname in raw and self._cipher.is_envelope(raw[fname]):
                    try:
                        raw[fname] = self._cipher.decrypt_value(raw[fname])
                    except ValueError:
                        raw.pop(fname, None)
            try:
                loaded_port = int(raw.get("cdp_port", _CDP_PORT_BASE))
                if loaded_port in _RESERVED_CDP_PORTS:
                    loaded_port = self._next_cdp_port()
                    changed = True
                self._accounts[acc_id] = Account(
                    id=raw.get("id", acc_id),
                    name=raw.get("name", ""),
                    email=raw.get("email", ""),
                    token=raw.get("token", ""),
                    cookie_valid=bool(raw.get("cookie_valid", False)),
                    cookie_updated_at=float(raw.get("cookie_updated_at", 0.0)),
                    cookie_expires_at=float(raw.get("cookie_expires_at", 0.0)),
                    cookies=list(raw.get("cookies", [])) if isinstance(raw.get("cookies", []), list) else [],
                    local_storage=dict(raw.get("local_storage", {})) if isinstance(raw.get("local_storage", {}), dict) else {},
                    media_auth_token=str(raw.get("media_auth_token", "") or ""),
                    media_auth_updated_at=float(raw.get("media_auth_updated_at", 0.0) or 0.0),
                    designer_auth_token=str(raw.get("designer_auth_token", "") or ""),
                    designer_auth_updated_at=float(raw.get("designer_auth_updated_at", 0.0) or 0.0),
                    refresh_token=str(raw.get("refresh_token", "") or ""),
                    refresh_token_updated_at=float(raw.get("refresh_token_updated_at", 0.0) or 0.0),
                    refresh_token_client_id=str(raw.get("refresh_token_client_id", "") or ""),
                    refresh_token_authority=str(raw.get("refresh_token_authority", "") or ""),
                    refresh_token_tenant_id=str(raw.get("refresh_token_tenant_id", "") or ""),
                    refresh_token_object_id=str(raw.get("refresh_token_object_id", "") or ""),
                    refresh_token_retry_after=float(raw.get("refresh_token_retry_after", 0.0) or 0.0),
                    media_seed_url=str(raw.get("media_seed_url", "") or ""),
                    cdp_port=loaded_port,
                    # An unusable value degrades to "" (fall back to the global
                    # proxy env) rather than failing the whole account: one bad
                    # field must not cost the user this account's credentials.
                    proxy_url=normalize_proxy_url(raw.get("proxy_url", "")),
                    studio_agent_id=normalize_studio_agent_id(
                        raw.get("studio_agent_id", "")
                    ),
                    studio_agent_tenant_id=str(
                        raw.get("studio_agent_tenant_id", "") or ""
                    ),
                    studio_agent_object_id=str(
                        raw.get("studio_agent_object_id", "") or ""
                    ),
                    token_source=raw.get("token_source", "manual"),
                    provider=str(raw.get("provider", "m365") or "m365"),
                    consumer_token=str(raw.get("consumer_token", "") or ""),
                    consumer_identity_type=str(raw.get("consumer_identity_type", "") or ""),
                    consumer_account_id=_normalize_consumer_account_id(
                        raw.get("consumer_account_id", "")
                    ),
                    consumer_updated_at=float(raw.get("consumer_updated_at", 0.0) or 0.0),
                    throttled_until=float(raw.get("throttled_until", 0.0) or 0.0),
                    created_at=float(raw.get("created_at", time.time())),
                    updated_at=float(raw.get("updated_at", time.time())),
                )
            except (TypeError, ValueError):
                continue
        if changed:
            self._save()
        self._backfill_email()

    def _backfill_email(self) -> None:
        """Populate email for accounts persisted before the field existed by
        re-reading their token's JWT claims. Runs once at load; saves if changed."""
        changed = False
        for acc in self._accounts.values():
            if acc.token:
                ident_name, email = extract_identity(acc.token)
                if email and acc.email != email:
                    acc.email = email
                    changed = True
                if ident_name and acc.name != ident_name:
                    acc.name = ident_name
                    changed = True
        if changed:
            self._save()

    def _save(self) -> None:
        if self._persist_path is None:
            return
        with self._lock:
            data = {acc_id: asdict(acc) for acc_id, acc in self._accounts.items()}
        # Encrypt sensitive field values before writing. asdict() returned fresh
        # dicts, so mutating them here does not touch the in-memory Accounts.
        # When encryption is disabled encrypt_value is an identity passthrough.
        for record in data.values():
            for fname in SENSITIVE_FIELDS:
                if fname in record:
                    record[fname] = self._cipher.encrypt_value(record[fname])
        try:
            write_text_atomic(
                self._persist_path,
                json.dumps(data, ensure_ascii=False, indent=2),
                durable=True,
            )
        except OSError:
            pass  # Persistence is best-effort; never break a request over a disk error

    # -------------------------------------------------------------- queries
    def get(self, acc_id: str) -> Account | None:
        with self._lock:
            return self._accounts.get(acc_id)

    def studio_client_snapshot(self, acc_id: str) -> tuple[str, str] | None:
        """Return one locked, subject-verified (token, agent id) snapshot."""
        with self._lock:
            account = self._accounts.get(acc_id)
            if account is None or not account.studio_agent_ready:
                return None
            return account.token, account.studio_agent_id

    def list(self) -> list[Account]:
        with self._lock:
            return list(self._accounts.values())

    def find_by_email(self, email: str) -> Account | None:
        """Find an existing account by (case-insensitive) email.

        Used to dedupe: when a user pushes a token whose identity matches an
        account already in the pool, we reuse that account instead of creating
        a duplicate record pointing at the same real M365 identity.
        """
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._lock:
            for acc in self._accounts.values():
                if acc.email and acc.email.lower() == email:
                    return acc
            return None

    def set_cdp_port_base(self, port: int) -> None:
        self._cdp_port_base = max(1, int(port))

    def _next_cdp_port(self) -> int:
        used = {acc.cdp_port for acc in self._accounts.values()} | _RESERVED_CDP_PORTS
        port = self._cdp_port_base
        while port in used:
            port += 1
        return port

    # -------------------------------------------------------------- mutations
    def add(self, name: str = "", token: str = "", token_source: str = "manual") -> Account:
        with self._lock:
            ident_name, email = extract_identity(token)
            acc = Account(
                name=ident_name or name,
                email=email,
                token=token,
                cdp_port=self._next_cdp_port(),
                token_source=token_source,
            )
            self._accounts[acc.id] = acc
            self._save()
            return acc

    def update_token(self, acc_id: str, token: str, token_source: str | None = None) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.token = token
            _clear_studio_binding_if_subject_changed(acc, token)
            ident_name, email = extract_identity(token)
            if email:
                acc.email = email
            if ident_name:
                acc.name = ident_name
            if token_source is not None:
                acc.token_source = token_source
            acc.updated_at = time.time()
            self._save()
            return acc

    def push_token(self, acc_id: str, token: str) -> Account | None:
        """Apply a user/admin-pushed token WITHOUT disabling on-demand refresh.

        A plain update_token(token_source="manual") permanently downgrades an
        account that already has a live signed-in Chromium session (cookies +
        token_source="cdp") back to "manual", which silently kills auto-refresh
        and makes the account's token-refresh button a no-op. So preserve "cdp"
        whenever the account still has a valid cookie session (token_source is
        left untouched); only genuinely profile-less accounts stay "manual".
        """
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            keep_cdp = acc.token_source == "cdp" and acc.cookie_valid
        return self.update_token(acc_id, token, token_source=None if keep_cdp else "manual")

    def clear_token(self, acc_id: str) -> Account | None:
        """Wipe a bound account's token while keeping the account record."""
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.token = ""
            _clear_studio_agent_binding(acc)
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_cookie_status(self, acc_id: str, valid: bool, token_source: str | None = None, expires_at: float = 0.0) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.cookie_valid = bool(valid)
            acc.cookie_updated_at = time.time() if valid else 0.0
            acc.cookie_expires_at = float(expires_at or 0.0) if valid else 0.0
            if token_source is not None:
                acc.token_source = token_source
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_cookies(self, acc_id: str, cookies: list[dict], local_storage: dict | None = None) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.cookies = [dict(cookie) for cookie in cookies if isinstance(cookie, dict)]
            if isinstance(local_storage, dict) and local_storage:
                acc.local_storage = {str(k): str(v) for k, v in local_storage.items()}
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_proxy_url(self, acc_id: str, proxy_url: str) -> Account | None:
        """Set this account's outbound proxy, or clear it with "".

        Returns None when the account is unknown or the URL is unusable, so a
        typo cannot silently drop an account onto the wrong egress. Validation is
        normalize_proxy_url's: it is the same trust boundary as the global
        setting (the value reaches httpx, curl_cffi and a Firefox argv).
        """
        from .runtime_settings import normalize_proxy_url

        raw = str(proxy_url or "").strip()
        normalized = normalize_proxy_url(raw)
        if raw and not normalized:
            return None
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.proxy_url = normalized
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_studio_agent_id(self, acc_id: str, agent_id: str) -> Account | None:
        """Bind an already-published Studio agent to this account's AAD subject.

        This stores metadata only. Provisioning and management-scope token minting
        deliberately live outside the request path.
        """
        raw = str(agent_id or "").strip()
        normalized = normalize_studio_agent_id(raw)
        if raw and not normalized:
            raise ValueError("Invalid Studio agent ID")
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            if not normalized:
                _clear_studio_agent_binding(acc)
                acc.updated_at = time.time()
                self._save()
                return acc
            if acc.provider != "m365":
                raise ValueError("Studio agent binding requires a valid M365 subject")
            tenant_id, object_id = _studio_subject(acc.token)
            if not tenant_id or not object_id:
                raise ValueError("Studio agent binding requires a valid M365 subject")
            acc.studio_agent_id = normalized
            acc.studio_agent_tenant_id = tenant_id
            acc.studio_agent_object_id = object_id
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_consumer_auth(
        self,
        acc_id: str,
        cookies: list[dict],
        access_token: str,
        identity_type: str = "",
        email: str = "",
        consumer_account_id: str | None = None,
        expected_snapshot: tuple[float, str, str] | None = None,
    ) -> Account | None:
        """Store a consumer-Copilot credential snapshot exported from a browser.

        Flips the account to the consumer provider, which excludes it from every
        M365 refresh path -- RT exchange, cookie replay, CDP capture are all
        meaningless for it (see RefreshScheduler.ensure_fresh). It is still
        scheduled, just through refresh_consumer instead.
        """
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            if expected_snapshot is not None:
                current_snapshot = (
                    acc.consumer_updated_at,
                    acc.consumer_token,
                    acc.consumer_account_id,
                )
                if current_snapshot != expected_snapshot:
                    return None
            previous_account_id = acc.consumer_account_id
            normalized_account_id = None
            if consumer_account_id is not None:
                normalized_account_id = _normalize_consumer_account_id(
                    consumer_account_id
                )
            acc.provider = "consumer"
            _clear_studio_agent_binding(acc)
            acc.cookies = [dict(cookie) for cookie in cookies if isinstance(cookie, dict)]
            acc.consumer_token = access_token.strip()
            acc.consumer_identity_type = (identity_type or "").strip()
            if normalized_account_id is not None:
                acc.consumer_account_id = normalized_account_id
            normalized_email = email.strip().lower() if isinstance(email, str) else ""
            if len(normalized_email) <= 254 and _EMAIL_RE.fullmatch(normalized_email):
                acc.email = normalized_email
            elif (
                normalized_account_id is not None
                and normalized_account_id != previous_account_id
            ):
                # A new/unknown Microsoft subject must never inherit the prior
                # account's display email.
                acc.email = ""
            now = time.time()
            acc.consumer_updated_at = now
            # Consumer login cookies are session cookies with no useful expiry of
            # their own, so cookie_expires_at stays 0 and the UI's binding state
            # rests on presence alone.
            acc.cookie_expires_at = 0.0
            acc.cookie_valid = bool(acc.cookies)
            acc.cookie_updated_at = now
            acc.updated_at = now
            self._save()
            return acc

    def set_throttled_until(self, acc_id: str, when: float) -> Account | None:
        """Record the reset time upstream named for this account's turns.

        Latest word wins, including a move backwards: the number comes from the
        backend, not from us, so a shorter window it reports later is the truth.
        """
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.throttled_until = max(0.0, float(when))
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_media_auth_token(self, acc_id: str, token: str) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.media_auth_token = token.strip()
            acc.media_auth_updated_at = time.time() if acc.media_auth_token else 0.0
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_designer_auth_token(self, acc_id: str, token: str) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.designer_auth_token = token.strip()
            acc.designer_auth_updated_at = time.time() if acc.designer_auth_token else 0.0
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_media_seed_url(self, acc_id: str, url: str) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.media_seed_url = url.strip()
            acc.updated_at = time.time()
            self._save()
            return acc

    def set_refresh_token(
        self,
        acc_id: str,
        token: str,
        *,
        client_id: str | None = None,
        authority: str | None = None,
        tenant_id: str | None = None,
        object_id: str | None = None,
        expected_refresh_token: str | None = None,
    ) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            if (
                expected_refresh_token is not None
                and acc.refresh_token != expected_refresh_token
            ):
                return None
            acc.refresh_token = token.strip()
            acc.refresh_token_updated_at = time.time() if acc.refresh_token else 0.0
            acc.refresh_token_retry_after = 0.0
            if not acc.refresh_token:
                acc.refresh_token_client_id = ""
                acc.refresh_token_authority = ""
                acc.refresh_token_tenant_id = ""
                acc.refresh_token_object_id = ""
            else:
                # None preserves the verified binding when AAD rotates the RT.
                if client_id is not None:
                    acc.refresh_token_client_id = client_id.strip()
                if authority is not None:
                    acc.refresh_token_authority = authority.strip()
                if tenant_id is not None:
                    acc.refresh_token_tenant_id = tenant_id.strip()
                if object_id is not None:
                    acc.refresh_token_object_id = object_id.strip()
            acc.updated_at = time.time()
            self._save()
            return acc

    def defer_refresh_token(
        self, acc_id: str, expected_refresh_token: str, retry_after: float
    ) -> bool:
        """Back off a failed RT without touching a newer userscript push."""
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None or acc.refresh_token != expected_refresh_token:
                return False
            acc.refresh_token_retry_after = max(
                acc.refresh_token_retry_after, float(retry_after)
            )
            acc.updated_at = time.time()
            self._save()
            return True

    def apply_refresh_token_result(
        self,
        acc_id: str,
        *,
        expected_refresh_token: str,
        expected_access_token: str,
        access_token: str,
        rotated_refresh_token: str = "",
    ) -> Account | None:
        """Atomically apply an RT response unless newer credentials won the race."""
        with self._lock:
            acc = self._accounts.get(acc_id)
            if (
                acc is None
                or acc.refresh_token != expected_refresh_token
                or acc.token != expected_access_token
            ):
                return None
            rotated = rotated_refresh_token.strip()
            if rotated and rotated != expected_refresh_token:
                acc.refresh_token = rotated
                acc.refresh_token_updated_at = time.time()
            acc.refresh_token_retry_after = 0.0
            acc.token = access_token
            _clear_studio_binding_if_subject_changed(acc, access_token)
            ident_name, email = extract_identity(access_token)
            if email:
                acc.email = email
            if ident_name:
                acc.name = ident_name
            acc.updated_at = time.time()
            self._save()
            return acc

    def clear_credentials(self, acc_id: str) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.token = ""
            acc.media_auth_token = ""
            acc.media_auth_updated_at = 0.0
            acc.designer_auth_token = ""
            acc.designer_auth_updated_at = 0.0
            acc.refresh_token = ""
            acc.refresh_token_updated_at = 0.0
            acc.refresh_token_client_id = ""
            acc.refresh_token_authority = ""
            acc.refresh_token_tenant_id = ""
            acc.refresh_token_object_id = ""
            acc.refresh_token_retry_after = 0.0
            _clear_studio_agent_binding(acc)
            acc.cookie_valid = False
            acc.cookie_updated_at = 0.0
            acc.cookie_expires_at = 0.0
            # A consumer account authenticates by its ChatAI token + cookies, not
            # the substrate token/refresh_token cleared above. Leaving provider and
            # consumer_token in place would keep request dispatch routing through
            # the consumer client on stale credentials -- a logout that never logs
            # out -- while binding_state reads "none". Reset it to a blank m365
            # account so routing, binding_state and token_status all agree it is
            # signed out.
            if acc.provider == "consumer":
                acc.provider = "m365"
                acc.consumer_token = ""
                acc.consumer_identity_type = ""
                acc.consumer_account_id = ""
                acc.consumer_updated_at = 0.0
                acc.cookies = []
            acc.updated_at = time.time()
            self._save()
            return acc

    def rename(self, acc_id: str, name: str) -> Account | None:
        with self._lock:
            acc = self._accounts.get(acc_id)
            if acc is None:
                return None
            acc.name = name
            acc.updated_at = time.time()
            self._save()
            return acc

    def remove(self, acc_id: str) -> bool:
        with self._lock:
            if acc_id in self._accounts:
                del self._accounts[acc_id]
                self._save()
                return True
            return False


def resolve_account_proxy(account: Account | None) -> str:
    """This account's outbound proxy, or "" to mean "use the proxy env vars".

    Returning "" rather than a direct-connection marker is deliberate: the
    global admin setting is already published to HTTP_PROXY/HTTPS_PROXY by
    apply_proxy_env(), and httpx / curl_cffi / Firefox all honour those by
    default. So "" preserves today's behaviour for every account that has not
    opted into its own egress.
    """
    return str(getattr(account, "proxy_url", "") or "")
