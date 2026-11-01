from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.consumer_adapter import ConsumerClientAdapter
from m365_copilot_openai_proxy.consumer_client import AccountThrottled


_QUOTA_MESSAGE = "Consumer account quota exceeded"


class _ThrottledConsumer:
    mode = "reasoning"

    def __init__(self, prefix: str):
        self.prefix = prefix

    async def chat_stream(self, prompt, conversation_id="", images=None):
        if self.prefix:
            yield self.prefix
        raise AccountThrottled(_QUOTA_MESSAGE, "2026-11-02T15:04:57+00:00")


@pytest.mark.parametrize("protocol", ["chat", "messages", "responses"])
@pytest.mark.parametrize("with_tools", [False, True], ids=["text", "tools"])
@pytest.mark.parametrize("prefix", ["", "partial answer"], ids=["before-text", "after-text"])
def test_consumer_stream_quota_terminates_as_protocol_error(
    tmp_path, protocol, with_tools, prefix,
):
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="test-key", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **_kwargs: ConsumerClientAdapter(_ThrottledConsumer(prefix)),
    )
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    function = {"name": "Read", "description": "Read a file", "parameters": schema}
    headers = {"Authorization": "Bearer test-key"}
    payload = {"model": "m365-copilot", "stream": True}
    if protocol == "responses":
        path = "/v1/responses"
        payload["input"] = "Read a file"
        if with_tools:
            payload["tools"] = [{"type": "function", **function}]
            payload["tool_choice"] = "required"
    else:
        path = "/v1/messages" if protocol == "messages" else "/v1/chat/completions"
        payload["messages"] = [{"role": "user", "content": "Read a file"}]
        if protocol == "messages":
            headers = {"x-api-key": "test-key", "anthropic-version": "2023-06-01"}
            payload["max_tokens"] = 64
            if with_tools:
                payload["tools"] = [{"name": "Read", "description": "Read a file", "input_schema": schema}]
                payload["tool_choice"] = {"type": "tool", "name": "Read"}
        elif with_tools:
            payload["tools"] = [{"type": "function", "function": function}]
            payload["tool_choice"] = "required"

    with TestClient(app) as client:
        response = client.post(path, headers=headers, json=payload)

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    if protocol == "messages":
        errors = [event for event in events if event["type"] == "error"]
        assert errors == [{"type": "error", "error": {"type": "rate_limit_error", "message": _QUOTA_MESSAGE}}]
        assert events[-1]["type"] == "error"
        assert not any(event["type"] == "message_stop" for event in events)
        assert not any(event.get("content_block", {}).get("type") == "tool_use" for event in events)
    elif protocol == "responses":
        errors = [event for event in events if event["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["code"] == "rate_limit_error"
        assert errors[0]["message"] == _QUOTA_MESSAGE
        assert events[-1]["type"] == "response.failed"
        assert events[-1]["response"]["status"] == "failed"
        assert events[-1]["response"]["error"] == {"code": "rate_limit_exceeded", "message": _QUOTA_MESSAGE}
        assert not any(event["type"] == "response.completed" for event in events)
        assert not any(event.get("item", {}).get("type") == "function_call" for event in events)
    else:
        assert response.text.endswith("data: [DONE]\n\n")
        assert all("choices" in event and "error" not in event for event in events)
        markers = [event["m365_error"] for event in events if "m365_error" in event]
        assert markers == [{"type": "rate_limit_error", "message": _QUOTA_MESSAGE}]
        assert not any(choice["delta"].get("tool_calls") for event in events for choice in event["choices"])
