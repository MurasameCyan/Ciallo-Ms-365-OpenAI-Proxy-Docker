from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.dependencies import create_api_dependencies


def test_create_api_dependencies_returns_settings_and_client_dependencies(tmp_path):
    app = FastAPI()
    settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    sentinel_client = object()

    app.state.settings = settings
    app.state.copilot_client_factory = lambda: sentinel_client

    get_settings, get_copilot_client = create_api_dependencies(app)

    request = SimpleNamespace(state=SimpleNamespace())

    assert get_settings() is settings
    assert get_copilot_client(request) is sentinel_client


def test_create_api_dependencies_wires_response_debug_sink_to_captured_payloads(tmp_path):
    app = FastAPI()
    settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    sentinel_client = SimpleNamespace()

    app.state.settings = settings
    app.state.copilot_client_factory = lambda: sentinel_client
    app.state.capture_enabled = True
    app.state.captured_payloads = []
    app.state.capture_payload_version = 0

    _, get_copilot_client = create_api_dependencies(app)

    request = SimpleNamespace(state=SimpleNamespace())

    assert get_copilot_client(request) is sentinel_client
    assert callable(sentinel_client._response_debug_sink)

    payload = {"type": "response.event", "payload": {"id": "evt-1"}}
    sentinel_client._response_debug_sink(payload)

    assert app.state.captured_payloads == [{"source": "copilot_response", "payload": payload}]
    assert app.state.capture_payload_version == 1


def test_get_copilot_client_dispatches_consumer_account_through_adapter(tmp_path):
    """A consumer account must not build a Substrate client: dispatch picks the
    consumer factory, flattens cookies via the shared _pick_cookies keep-list,
    and hands back a ConsumerClientAdapter -- the seam the /v1 routes see."""
    from m365_copilot_openai_proxy.consumer_adapter import ConsumerClientAdapter

    app = FastAPI()
    app.state.settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    app.state.copilot_client_factory = lambda **kw: pytest.fail("consumer must not build a Substrate client")

    sentinel_consumer = object()
    captured: dict = {}

    def fake_consumer_factory(**kwargs):
        captured.update(kwargs)
        return sentinel_consumer

    app.state.consumer_client_factory = fake_consumer_factory

    _, get_copilot_client = create_api_dependencies(app)

    account = SimpleNamespace(
        id="acct-1",
        provider="consumer",
        token=None,
        cookies=[
            {"name": "_C_Auth", "value": "abc", "domain": ".copilot.microsoft.com"},
            {"name": "junk", "value": "x", "domain": ".example.com"},  # off keep-list
        ],
        consumer_token="chatai-token",
        consumer_identity_type="MSA",
    )
    request = SimpleNamespace(state=SimpleNamespace(account=account, api_key_obj=None))

    client = get_copilot_client(request)

    assert isinstance(client, ConsumerClientAdapter)
    assert client._client is sentinel_consumer
    # _pick_cookies dropped the off-keep-list cookie and flattened to name->value.
    assert captured["cookies"] == {"_C_Auth": "abc"}
    assert captured["access_token"] == "chatai-token"
    assert captured["identity_type"] == "MSA"
    # No scheduler on app.state here, so no gate is attached and the client's own
    # ClearanceRequired reaches the caller unchanged.
    assert captured["gate"] is None
    assert captured["idle_timeout"] is None


def test_a_typeerror_in_the_consumer_branch_is_not_downgraded_to_m365(tmp_path):
    """The kwargs-less retry belongs to the Substrate factory alone. While it
    covered the whole dispatch, a TypeError from the consumer factory fell through
    to an anonymous M365 client, and the turn failed with an M365 error naming
    nothing about the real cause."""
    from fastapi import HTTPException

    app = FastAPI()
    app.state.settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    app.state.copilot_client_factory = lambda **kw: pytest.fail(
        "a consumer account must never fall back to a Substrate client"
    )

    def broken_consumer_factory(**kwargs):
        raise TypeError("unexpected keyword argument 'proxy'")

    app.state.consumer_client_factory = broken_consumer_factory

    _, get_copilot_client = create_api_dependencies(app)

    account = SimpleNamespace(
        id="acct-1",
        provider="consumer",
        token=None,
        cookies=[{"name": "_C_Auth", "value": "abc", "domain": ".copilot.microsoft.com"}],
        consumer_token="chatai-token",
        consumer_identity_type="MSA",
    )
    request = SimpleNamespace(state=SimpleNamespace(account=account, api_key_obj=None))

    with pytest.raises(HTTPException) as error:
        get_copilot_client(request)
    assert error.value.status_code == 503
    assert "proxy" in str(error.value.detail)
