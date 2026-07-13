from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.login_guard import LoginRateLimiter


def make_app(tmp_path):
    return create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))


def test_limiter_locks_after_limit_and_clears():
    lim = LoginRateLimiter(limit=3, lockout_sec=60.0)
    ip = "1.2.3.4"
    assert not lim.is_locked(ip)
    for _ in range(3):
        lim.record_failure(ip)
    assert lim.is_locked(ip)
    lim.clear(ip)
    assert not lim.is_locked(ip)


def test_limiter_prunes_stale_failures():
    lim = LoginRateLimiter(limit=2, lockout_sec=0.0)  # everything is immediately stale
    ip = "5.6.7.8"
    lim.record_failure(ip)
    lim.record_failure(ip)
    # With a 0s window every prior failure is stale, so the ip is never locked
    # and the internal map is pruned back to empty.
    assert not lim.is_locked(ip)
    assert ip not in lim._failures


def test_user_login_locks_out_after_five_failures(tmp_path):
    app = make_app(tmp_path)
    app.state.key_store.add(name="U", username="proxyuser", password="password1")
    client = TestClient(app)

    for _ in range(5):
        r = client.post("/user/login", json={"username": "proxyuser", "password": "wrong"})
        assert r.status_code == 401
    # 6th attempt is locked out even with the CORRECT password.
    r = client.post("/user/login", json={"username": "proxyuser", "password": "password1"})
    assert r.status_code == 429


def test_user_login_success_resets_counter(tmp_path):
    app = make_app(tmp_path)
    app.state.key_store.add(name="U", username="proxyuser", password="password1")
    client = TestClient(app)

    for _ in range(4):
        client.post("/user/login", json={"username": "proxyuser", "password": "wrong"})
    ok = client.post("/user/login", json={"username": "proxyuser", "password": "password1"})
    assert ok.status_code == 200
    # After a success the counter is cleared, so a fresh wrong attempt is a 401
    # (not an immediate 429 from a still-full window).
    again = client.post("/user/login", json={"username": "proxyuser", "password": "wrong"})
    assert again.status_code == 401


def test_repassword_has_independent_window(tmp_path):
    app = make_app(tmp_path)
    k = app.state.key_store.add(name="U", username="proxyuser", password="password1")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {k.key}"}

    # Exhaust the repassword window with wrong old-passwords.
    for _ in range(5):
        r = client.post("/user/repassword", json={"old_password": "wrong", "new_password": "newpass1"}, headers=headers)
        assert r.status_code == 401
    r = client.post("/user/repassword", json={"old_password": "password1", "new_password": "newpass1"}, headers=headers)
    assert r.status_code == 429
    # The /user/login window is untouched (independent key), so login still works.
    login = client.post("/user/login", json={"username": "proxyuser", "password": "password1"})
    assert login.status_code == 200
