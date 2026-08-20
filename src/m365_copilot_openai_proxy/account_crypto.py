"""At-rest encryption for sensitive account fields (AES-256-GCM).

The account pool is persisted to ``accounts.json`` inside the Docker data
volume. It holds high-value credentials -- OAuth2 refresh tokens, SSO cookies,
MSAL localStorage, and media/designer auth tokens -- that would let anyone who
reads the file impersonate the account. This module encrypts those field values
with AES-256-GCM so a leaked/backed-up/accidentally-committed ``accounts.json``
is useless without the key.

Design (see project decision -- "Scheme 2: key file in data dir"):

* Key lives in ``data/.enc_key`` (32 raw bytes, chmod 600 best-effort),
  auto-generated on first use. This protects against file leakage / accidental
  git commits, NOT against an attacker who can read the whole data volume (they
  get both key and ciphertext). That trade-off was accepted for zero-config UX.
* Only sensitive *field values* are encrypted; metadata (id, label, timestamps,
  cdp_port, ...) stays plaintext so ``accounts.json`` remains greppable and the
  ``has_*`` serializers keep working.
* Each encrypted value becomes an envelope dict ``{"__enc__": 1, "n": <nonce>,
  "ct": <ciphertext>}`` (both base64). ``_load`` transparently accepts either an
  envelope (decrypt) or a legacy plaintext value (use as-is), so upgrading an
  existing deployment needs no manual migration -- the next ``_save`` rewrites
  everything encrypted.
* Graceful degradation: if the ``cryptography`` package is missing or the key
  cannot be created/read, encryption is disabled and values are stored/read as
  plaintext (same as today). Persistence must never break a running request.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

try:  # cryptography is an optional dependency; degrade gracefully if absent.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _HAVE_CRYPTO = True
except Exception:  # noqa: BLE001 - any import failure means "no encryption"
    AESGCM = None  # type: ignore[assignment]
    _HAVE_CRYPTO = False


_ENVELOPE_MARKER = "__enc__"
_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # GCM standard nonce size

# Account field names whose values must be encrypted at rest. Everything else on
# the dataclass is non-sensitive metadata and stays plaintext.
SENSITIVE_FIELDS = (
    "token",
    "cookies",
    "local_storage",
    "media_auth_token",
    "designer_auth_token",
    "refresh_token",
    "media_seed_url",
    "consumer_token",
    "consumer_account_id",
    # An outbound proxy URL may embed credentials (http://user:pass@host:port),
    # which normalize_proxy_url explicitly accepts -- so it is at-rest sensitive.
    "proxy_url",
    # A Studio binding is an account-scoped cloud resource reference. Keep both
    # the opaque agent id and the AAD subject it was bound under out of backups
    # and accidental diffs; public serializers expose a presence boolean only.
    "studio_agent_id",
    "studio_agent_tenant_id",
    "studio_agent_object_id",
)


class AccountCipher:
    """Encrypts/decrypts individual account field values with AES-256-GCM.

    A single instance is created per AccountStore. When encryption is disabled
    (no cryptography lib, or key unavailable) ``enabled`` is False and the
    encrypt/decrypt helpers become identity passthroughs.
    """

    def __init__(self, key: bytes | None):
        self._key = key
        self.enabled = bool(key) and _HAVE_CRYPTO

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def is_envelope(value: Any) -> bool:
        """True if ``value`` is an encrypted envelope produced by this module."""
        return isinstance(value, dict) and value.get(_ENVELOPE_MARKER) == 1

    def encrypt_value(self, value: Any) -> Any:
        """Return an encrypted envelope for ``value``.

        ``value`` may be any JSON-serialisable type (str/list/dict). It is JSON
        encoded, encrypted, and wrapped in an envelope. When encryption is
        disabled the value is returned unchanged (plaintext passthrough).
        """
        if not self.enabled:
            return value
        plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(_NONCE_BYTES)
        ct = AESGCM(self._key).encrypt(nonce, plaintext, None)
        return {
            _ENVELOPE_MARKER: 1,
            "n": base64.b64encode(nonce).decode("ascii"),
            "ct": base64.b64encode(ct).decode("ascii"),
        }

    def decrypt_value(self, value: Any) -> Any:
        """Return the plaintext for an envelope, or ``value`` if not an envelope.

        Legacy plaintext values (pre-encryption deployments) are passed through
        untouched. A malformed/undecryptable envelope raises ValueError so the
        caller can decide how to handle it (AccountStore treats it as absent).
        """
        if not self.is_envelope(value):
            return value  # legacy plaintext or already-decrypted
        if not self.enabled:
            raise ValueError("encrypted account field found but encryption is disabled")
        try:
            nonce = base64.b64decode(value["n"])
            ct = base64.b64decode(value["ct"])
            plaintext = AESGCM(self._key).decrypt(nonce, ct, None)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - surface as a clean ValueError
            raise ValueError(f"cannot decrypt account field: {exc}") from exc


def load_or_create_key(key_path: str | Path) -> bytes | None:
    """Load the 32-byte key from ``key_path``, creating it on first use.

    Returns None (encryption disabled) when the cryptography package is missing
    or the key file cannot be read/created -- persistence then falls back to
    plaintext, exactly like the pre-encryption behaviour.
    """
    if not _HAVE_CRYPTO:
        return None
    path = Path(key_path)
    try:
        if path.exists():
            raw = path.read_bytes()
            # File stores base64 for readability; tolerate raw bytes too.
            try:
                decoded = base64.b64decode(raw, validate=True)
            except Exception:  # noqa: BLE001
                decoded = raw
            if len(decoded) == _KEY_BYTES:
                return decoded
            # Corrupt/short key: do NOT overwrite (would orphan existing data).
            return None
        key = os.urandom(_KEY_BYTES)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64encode(key))
        try:
            os.chmod(path, 0o600)  # best-effort; ignored on platforms w/o POSIX perms
        except OSError:
            pass
        return key
    except OSError:
        return None
