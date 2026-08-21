from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.substrate_client import SubstrateThrottled


class _ThrottledClient:
    async def chat(self, prompt, additional_context, session=None, images=None):
        raise SubstrateThrottled("upstream result: Throttled")


@pytest.mark.parametrize(
    ("path", "headers", "payload", "expected"),
    [
        pytest.param(
            "/v1/chat/completions",
            {"Authorization": "Bearer test-key"},
            {
                "model": "m365-copilot",
                "messages": [{"role": "user", "content": "ping"}],
            },
            {
                "error": {
                    "message": "upstream result: Throttled",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
            id="chat",
        ),
        pytest.param(
            "/v1/messages",
            {"x-api-key": "test-key", "anthropic-version": "2023-06-01"},
            {
                "model": "m365-copilot",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "ping"}],
            },
            {
                "type": "error",
                "error": {
                    "type": "rate_limit_error",
                    "message": "upstream result: Throttled",
                },
            },
            id="messages",
        ),
        pytest.param(
            "/v1/responses",
            {"Authorization": "Bearer test-key"},
            {"model": "m365-copilot", "input": "ping"},
            {
                "error": {
                    "message": "upstream result: Throttled",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
            id="responses",
        ),
    ],
)
def test_nonstream_upstream_throttle_uses_protocol_rate_limit_envelope(
    tmp_path, path, headers, payload, expected,
):
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="test-key", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **_kwargs: _ThrottledClient(),
    )

    response = TestClient(app).post(path, headers=headers, json=payload)

    assert response.status_code == 429
    assert response.json() == expected
