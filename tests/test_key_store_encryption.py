from __future__ import annotations

import json

import pytest

from m365_copilot_openai_proxy import account_crypto
from m365_copilot_openai_proxy.key_store import KeyStore

pytestmark = pytest.mark.skipif(
    not account_crypto._HAVE_CRYPTO,
    reason="cryptography not installed; encryption degrades to plaintext",
)


def test_keys_sensitive_fields_encrypted_on_disk(tmp_path):
    persist = tmp_path / "keys.json"
    store = KeyStore(persist)
    k = store.add(name="U", username="proxyuser", password="super-secret-pw")

    raw = json.loads(persist.read_text(encoding="utf-8"))
    record = raw[k.id]
    for fname in ("key", "password", "password_hash", "password_salt"):
        assert record[fname].get("__enc__") == 1, f"{fname} must be an envelope on disk"

    blob = persist.read_text(encoding="utf-8")
    assert "super-secret-pw" not in blob
    assert k.key not in blob  # the raw sk-... secret must not be greppable
    # Non-sensitive metadata stays plaintext.
    assert record["id"] == k.id
    assert record["username"] == "proxyuser"


def test_keys_round_trip_after_reload(tmp_path):
    persist = tmp_path / "keys.json"
    store = KeyStore(persist)
    k = store.add(name="U", username="proxyuser", password="super-secret-pw")
    raw_key = k.key

    reloaded = KeyStore(persist)
    got = reloaded.get(k.id)
    assert got is not None
    assert got.key == raw_key
    assert got.password == "super-secret-pw"
    # The secret index must be rebuilt from the decrypted key so auth still works.
    assert reloaded.resolve(raw_key) is not None
    assert reloaded.resolve_by_login("proxyuser", "super-secret-pw") is not None


def test_keys_read_legacy_plaintext_then_encrypt_on_save(tmp_path):
    persist = tmp_path / "keys.json"
    # Simulate a pre-encryption deployment: plaintext keys.json, no key yet.
    legacy = {
        "key_legacy": {
            "id": "key_legacy",
            "key": "sk-legacy-plain",
            "username": "olduser",
            "password": "old-plain-pw",
            "password_hash": "abc",
            "password_salt": "def",
        }
    }
    persist.write_text(json.dumps(legacy), encoding="utf-8")

    store = KeyStore(persist)
    got = store.get("key_legacy")
    assert got is not None
    assert got.key == "sk-legacy-plain"
    assert got.password == "old-plain-pw"
    assert store.resolve("sk-legacy-plain") is not None

    # A mutation triggers a save that rewrites the file encrypted.
    store.update("key_legacy", name="renamed")
    blob = persist.read_text(encoding="utf-8")
    assert "sk-legacy-plain" not in blob
    assert "old-plain-pw" not in blob
    record = json.loads(blob)["key_legacy"]
    assert record["key"].get("__enc__") == 1
    assert record["password"].get("__enc__") == 1
