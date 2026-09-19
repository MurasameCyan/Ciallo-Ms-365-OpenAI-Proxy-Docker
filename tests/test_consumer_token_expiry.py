from __future__ import annotations

import json
import time

import pytest

from m365_copilot_openai_proxy.account_store import AccountStore


INVALID_EXPIRIES = [
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(-1, id="negative"),
    pytest.param(0, id="zero"),
    pytest.param(10**400, id="overflow"),
    pytest.param("invalid", id="malformed"),
    pytest.param(True, id="boolean"),
    pytest.param({}, id="object"),
    pytest.param(None, id="unknown"),
]


def _store(tmp_path):
    path = tmp_path / "accounts.json"
    store = AccountStore(path)
    account = store.add(name="Personal")
    store.set_consumer_auth(
        account.id,
        [],
        "old-token",
        consumer_account_id="home:account-a",
        expires_at=time.time() + 3600,
        consumer_refresh_token="old-refresh-token",
    )
    return path, store, account


def test_consumer_rt_result_is_persisted_before_success(tmp_path):
    path, store, account = _store(tmp_path)
    store.defer_consumer_refresh_token(account.id, "old-refresh-token", time.time() + 900)
    expiry = time.time() + 7200

    result = store.apply_consumer_refresh_result(
        account.id,
        expected_refresh_token="old-refresh-token",
        expected_consumer_token="old-token",
        consumer_token="fresh-token",
        rotated_refresh_token="rotated-refresh-token",
        expires_at=expiry,
    )

    assert result is not None
    reopened = AccountStore(path).get(account.id)
    assert reopened.consumer_token == "fresh-token"
    assert reopened.consumer_refresh_token == "rotated-refresh-token"
    assert reopened.consumer_token_expires_at == expiry
    assert reopened.consumer_refresh_token_retry_after == 0.0
    assert reopened.consumer_updated_at == result.consumer_updated_at
    assert reopened.consumer_refresh_token_updated_at == result.consumer_refresh_token_updated_at
    assert "fresh-token" not in path.read_text(encoding="utf-8")
    assert "rotated-refresh-token" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("expiry", INVALID_EXPIRIES)
def test_consumer_push_store_treats_invalid_expiry_as_unknown(tmp_path, expiry):
    path, store, account = _store(tmp_path)

    store.set_consumer_auth(
        account.id, [], "fresh-token", consumer_account_id="home:account-a", expires_at=expiry
    )

    reopened = AccountStore(path).get(account.id)
    assert reopened.consumer_token == "fresh-token"
    assert reopened.consumer_token_expires_at == 0.0


@pytest.mark.parametrize("expiry", INVALID_EXPIRIES)
def test_consumer_rt_result_treats_invalid_expiry_as_unknown(tmp_path, expiry):
    path, store, account = _store(tmp_path)

    result = store.apply_consumer_refresh_result(
        account.id,
        expected_refresh_token="old-refresh-token",
        expected_consumer_token="old-token",
        consumer_token="fresh-token",
        expires_at=expiry,
    )

    assert result is not None
    reopened = AccountStore(path).get(account.id)
    assert reopened.consumer_token == "fresh-token"
    assert reopened.consumer_token_expires_at == 0.0


@pytest.mark.parametrize("expiry", INVALID_EXPIRIES)
def test_consumer_load_keeps_credentials_with_invalid_expiry(tmp_path, expiry):
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps({"account-a": {
            "id": "account-a",
            "provider": "consumer",
            "consumer_token": "stored-token",
            "consumer_token_expires_at": expiry,
        }}),
        encoding="utf-8",
    )

    account = AccountStore(path).get("account-a")

    assert account is not None
    assert account.consumer_token == "stored-token"
    assert account.consumer_token_expires_at == 0.0


@pytest.mark.parametrize("changed_field", ["consumer_token", "refresh_token"])
def test_consumer_rt_result_does_not_overwrite_a_newer_snapshot(tmp_path, changed_field):
    path, store, account = _store(tmp_path)
    expected = {
        "expected_consumer_token": "old-token",
        "expected_refresh_token": "old-refresh-token",
    }
    expected[f"expected_{changed_field}"] = "stale-token"
    before = path.read_bytes()

    result = store.apply_consumer_refresh_result(
        account.id, **expected, consumer_token="late-token", expires_at=time.time() + 7200
    )

    assert result is None
    assert account.consumer_token == "old-token"
    assert path.read_bytes() == before
