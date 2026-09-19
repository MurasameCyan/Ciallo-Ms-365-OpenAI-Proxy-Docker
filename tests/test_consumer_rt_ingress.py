from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy import routes_user
from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


SUBJECT = "home:personal-a.9188040d-6c67-4c5b-b112-36a304b66dad"
CLIENT_ID = "14638111-3389-403d-b206-a6a71d9f8f16"
SCOPE = "140e65af-45d1-4427-bf08-3e7295db6836/ChatAI.ReadWrite"
COOKIES = [{"name": "WLSSC", "value": "session", "domain": ".live.com", "path": "/"}]


def _app(tmp_path, monkeypatch):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    # These tests exercise ingress atomicity and public expiry, not background I/O.
    monkeypatch.setattr(routes_user, "_spawn_post_push_refresh", lambda *args, **kwargs: None)
    account = app.state.account_store.add(name="Personal")
    app.state.account_store.set_consumer_auth(
        account.id, COOKIES, "original-consumer-access-token", "MSA",
        consumer_account_id=SUBJECT,
    )
    key = app.state.key_store.add(name="Personal", account_id=account.id)
    return app, account, {"Authorization": f"Bearer {key.key}"}


def test_mixed_subject_rt_push_is_rejected_without_replacing_working_credentials(tmp_path, monkeypatch):
    app, account, headers = _app(tmp_path, monkeypatch)
    response = TestClient(app).post("/user/account/consumer", headers=headers, json={
        "cookies": COOKIES,
        "access_token": "replacement-consumer-access-token",
        "consumer_account_id": SUBJECT,
        "refresh_token": "other-person-refresh-token-" + "x" * 32,
        "refresh_token_client_id": CLIENT_ID,
        "refresh_token_scope": SCOPE,
        "refresh_token_account_id": "home:personal-b.9188040d-6c67-4c5b-b112-36a304b66dad",
    })

    assert response.status_code == 400
    assert app.state.account_store.get(account.id).consumer_token == "original-consumer-access-token"


def test_known_expired_consumer_token_is_not_advertised_as_valid(tmp_path, monkeypatch):
    app, _, headers = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    response = client.post("/user/account/consumer", headers=headers, json={
        "cookies": COOKIES,
        "access_token": "expired-consumer-access-token",
        "consumer_account_id": SUBJECT,
        "expires_at": time.time() - 60,
    })
    assert response.status_code == 200

    status = client.get("/user/me", headers=headers).json()["account"]["token_status"]
    assert status["valid"] is False
    assert status["seconds_remaining"] == 0


@pytest.mark.parametrize("field", ["expires_at", "expires_in"])
@pytest.mark.parametrize("expiry", [
    pytest.param(float("inf"), id="infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(10**400, id="overflow"),
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
])
def test_consumer_push_rejects_nonfinite_expiry(tmp_path, monkeypatch, field, expiry):
    app, account, headers = _app(tmp_path, monkeypatch)
    body = {
        "cookies": COOKIES,
        "access_token": "replacement-consumer-access-token",
        "consumer_account_id": SUBJECT,
        field: expiry,
    }
    response = TestClient(app).post(
        "/user/account/consumer",
        headers={**headers, "Content-Type": "application/json"},
        content=json.dumps(body),
    )

    assert response.status_code == 400
    assert app.state.account_store.get(account.id).consumer_token == "original-consumer-access-token"


def test_consumer_push_persists_relative_expiry(tmp_path, monkeypatch):
    app, account, headers = _app(tmp_path, monkeypatch)
    before = time.time()

    response = TestClient(app).post("/user/account/consumer", headers=headers, json={
        "cookies": COOKIES,
        "access_token": "replacement-consumer-access-token",
        "consumer_account_id": SUBJECT,
        "expires_in": 3600,
    })

    assert response.status_code == 200
    expiry = app.state.account_store.get(account.id).consumer_token_expires_at
    assert before + 3600 <= expiry <= time.time() + 3600
