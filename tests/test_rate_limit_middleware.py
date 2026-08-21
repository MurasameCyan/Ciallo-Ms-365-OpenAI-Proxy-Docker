from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


def make_client(tmp_path, api_key: str = "admin-key", **runtime) -> TestClient:
    client = TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY=api_key, ADMIN_PASSWORD="admin-pass")))
    client.app.state.runtime_settings.update(runtime)
    return client


def test_requests_within_burst_are_allowed(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=5)

    for _ in range(5):
        assert client.get("/v1/models", headers={"x-api-key": "admin-key"}).status_code == 200


def test_exceeding_burst_returns_429_with_retry_after(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=2)
    for _ in range(2):
        client.get("/v1/models", headers={"x-api-key": "admin-key"})

    response = client.get("/v1/models", headers={"x-api-key": "admin-key"})

    assert response.status_code == 429
    assert response.json()["error"]["type"] == "rate_limit_error"
    assert int(response.headers["retry-after"]) >= 1


def test_messages_rate_limit_uses_anthropic_error_envelope(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=1)
    client.get("/v1/models", headers={"x-api-key": "admin-key"})

    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "admin-key"},
        json={"model": "m365-copilot", "messages": []},
    )

    assert response.status_code == 429
    assert response.json() == {
        "type": "error",
        "error": {
            "type": "rate_limit_error",
            "message": response.json()["error"]["message"],
        },
    }
    assert int(response.headers["retry-after"]) >= 1


def test_zero_rpm_disables_limiting(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=0, rate_limit_burst=1)

    for _ in range(20):
        assert client.get("/v1/models", headers={"x-api-key": "admin-key"}).status_code == 200


def test_limit_is_per_key_not_global(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=1)
    alice = client.app.state.key_store.add(name="Alice", username="alice", password="password1")
    bob = client.app.state.key_store.add(name="Bob", username="bob", password="password1")

    assert client.get("/v1/models", headers={"x-api-key": alice.key}).status_code == 200
    assert client.get("/v1/models", headers={"x-api-key": alice.key}).status_code == 429
    # Bob is untouched by Alice draining her own bucket.
    assert client.get("/v1/models", headers={"x-api-key": bob.key}).status_code == 200


def test_per_key_rpm_overrides_the_global_ceiling(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=1)
    key = client.app.state.key_store.add(name="Heavy", username="heavy", password="password1")
    client.app.state.key_store.update(key.id, rate_limit_rpm=600)

    # burst still 1 from the global setting, but the bucket refills 10x faster,
    # so the override is visible in the retry-after rather than the first refusal.
    assert client.get("/v1/models", headers={"x-api-key": key.key}).status_code == 200
    response = client.get("/v1/models", headers={"x-api-key": key.key})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) == 1


def test_negative_per_key_rpm_waives_the_limit(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=1)
    key = client.app.state.key_store.add(name="Unlimited", username="unlimited", password="password1")
    client.app.state.key_store.update(key.id, rate_limit_rpm=-1)

    for _ in range(20):
        assert client.get("/v1/models", headers={"x-api-key": key.key}).status_code == 200


def test_admin_paths_are_not_rate_limited(tmp_path):
    """Throttling the admin UI would lock an operator out of raising the limit."""
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=1)

    for _ in range(10):
        assert client.get("/healthz").status_code == 200


def test_key_edit_preserves_the_accrued_bucket(tmp_path):
    """KeyStore.update() replaces the dataclass; the bucket must not reset with it."""
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=1)
    key = client.app.state.key_store.add(name="Alice", username="alice", password="password1")

    assert client.get("/v1/models", headers={"x-api-key": key.key}).status_code == 200
    client.app.state.key_store.update(key.id, name="Alice Renamed")

    assert client.get("/v1/models", headers={"x-api-key": key.key}).status_code == 429


def test_rate_limit_survives_a_runtime_settings_save(tmp_path):
    """POST /admin/runtime-settings rebuilds the dict; the limits must persist."""
    client = make_client(tmp_path)
    client.post("/admin/login", json={"password": "admin-pass"})

    response = client.post("/admin/runtime-settings", json={"rate_limit_rpm": 30, "rate_limit_burst": 3})

    assert response.status_code == 200
    assert response.json()["settings"]["rate_limit_rpm"] == 30
    assert response.json()["settings"]["rate_limit_burst"] == 3
    assert client.app.state.runtime_settings["rate_limit_rpm"] == 30
