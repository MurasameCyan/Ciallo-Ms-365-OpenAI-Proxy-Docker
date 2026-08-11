from __future__ import annotations

import json

import pytest

from m365_copilot_openai_proxy import account_crypto
from m365_copilot_openai_proxy.account_crypto import (
    AccountCipher,
    load_or_create_key,
)
from m365_copilot_openai_proxy.account_store import AccountStore

pytestmark = pytest.mark.skipif(
    not account_crypto._HAVE_CRYPTO,
    reason="cryptography not installed; encryption degrades to plaintext",
)


def test_cipher_round_trips_str_list_and_dict(tmp_path):
    key = load_or_create_key(tmp_path / ".enc_key")
    cipher = AccountCipher(key)
    assert cipher.enabled

    for value in ["a-token", ["c1", "c2"], {"k": "v", "n": 1}]:
        env = cipher.encrypt_value(value)
        assert cipher.is_envelope(env)
        assert env != value
        assert cipher.decrypt_value(env) == value


def test_decrypt_passes_through_legacy_plaintext(tmp_path):
    key = load_or_create_key(tmp_path / ".enc_key")
    cipher = AccountCipher(key)
    # A pre-encryption plaintext value is not an envelope -> returned as-is.
    assert cipher.decrypt_value("legacy-plaintext-token") == "legacy-plaintext-token"


def test_load_or_create_key_is_stable_across_calls(tmp_path):
    key_path = tmp_path / ".enc_key"
    first = load_or_create_key(key_path)
    second = load_or_create_key(key_path)
    assert first == second
    assert key_path.exists()


def test_disabled_cipher_is_identity_passthrough():
    cipher = AccountCipher(None)
    assert not cipher.enabled
    assert cipher.encrypt_value("x") == "x"
    assert cipher.decrypt_value("x") == "x"


def test_store_persists_sensitive_fields_encrypted_on_disk(tmp_path):
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="acct", token="secret-substrate-token")
    store.set_cookies(
        acc.id,
        [{"name": "ESTSAUTH", "value": "super-secret"}],
        {"msal": "cached"},
    )
    store.set_refresh_token(acc.id, "secret-refresh-token")

    raw = json.loads(persist.read_text(encoding="utf-8"))
    record = raw[acc.id]
    # Sensitive fields must be envelopes on disk, and the secret text must not
    # appear anywhere in the serialized file.
    for fname in ("token", "cookies", "local_storage", "refresh_token"):
        assert record[fname].get("__enc__") == 1
    blob = persist.read_text(encoding="utf-8")
    assert "secret-substrate-token" not in blob
    assert "super-secret" not in blob
    assert "secret-refresh-token" not in blob
    # Non-sensitive metadata stays plaintext / greppable.
    assert record["id"] == acc.id


def test_store_persists_proxy_credentials_encrypted_on_disk(tmp_path):
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="acct")
    # normalize_proxy_url accepts embedded credentials, so a proxy URL can carry
    # a password -- it must not land in accounts.json as plaintext.
    assert store.set_proxy_url(acc.id, "http://user:proxy-secret-pass@proxy.example.com:3128") is not None

    raw = json.loads(persist.read_text(encoding="utf-8"))
    assert raw[acc.id]["proxy_url"].get("__enc__") == 1
    blob = persist.read_text(encoding="utf-8")
    assert "proxy-secret-pass" not in blob
    assert "proxy.example.com" not in blob

    reloaded = AccountStore(persist_path=persist)
    assert reloaded.get(acc.id).proxy_url == "http://user:proxy-secret-pass@proxy.example.com:3128"


def test_store_reloads_encrypted_accounts(tmp_path):
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="acct", token="round-trip-token")
    store.set_refresh_token(acc.id, "round-trip-refresh")

    reloaded = AccountStore(persist_path=persist)
    got = reloaded.get(acc.id)
    assert got is not None
    assert got.token == "round-trip-token"
    assert got.refresh_token == "round-trip-refresh"


def test_store_reads_legacy_plaintext_accounts_then_encrypts_on_save(tmp_path):
    persist = tmp_path / "accounts.json"
    # Simulate a pre-encryption deployment: plaintext accounts.json, no key yet.
    legacy = {
        "acct_legacy": {
            "id": "acct_legacy",
            "token": "plaintext-token",
            "refresh_token": "plaintext-refresh",
            "cookies": [{"name": "ESTSAUTH", "value": "plain"}],
        }
    }
    persist.write_text(json.dumps(legacy), encoding="utf-8")

    store = AccountStore(persist_path=persist)
    got = store.get("acct_legacy")
    assert got is not None
    assert got.token == "plaintext-token"
    assert got.refresh_token == "plaintext-refresh"

    # A save (triggered by any mutation) must rewrite the file encrypted.
    store.set_refresh_token("acct_legacy", "rotated-refresh")
    blob = persist.read_text(encoding="utf-8")
    assert "plaintext-token" not in blob
    assert "rotated-refresh" not in blob
    record = json.loads(blob)["acct_legacy"]
    assert record["token"].get("__enc__") == 1
