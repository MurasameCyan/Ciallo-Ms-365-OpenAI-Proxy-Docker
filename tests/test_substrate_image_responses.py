from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy import substrate_client
from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient, _message_content, _remaining_fallback_text


def test_message_content_includes_adaptive_card_image_markdown():
    entry = {
        "author": "bot",
        "text": "Loading image",
        "adaptiveCards": [
            {
                "body": [
                    {"type": "TextBlock", "text": "preview"},
                    {"type": "Image", "url": "https://images.example/generated.png"},
                ]
            }
        ],
    }

    assert _message_content(entry) == "Loading image\n\n![image](https://images.example/generated.png)"


def test_message_content_includes_attachment_content_url_image_markdown():
    entry = {
        "author": "bot",
        "attachments": [
            {
                "contentType": "image/png",
                "contentUrl": "https://images.example/generated-image",
            }
        ],
    }

    assert _message_content(entry) == "![image](https://images.example/generated-image)"


def test_remaining_fallback_text_appends_image_after_loading_stream_delta():
    assert (
        _remaining_fallback_text(
            "Loading image",
            "Loading image\n\n![image](https://images.example/generated.png)",
        )
        == "\n\n![image](https://images.example/generated.png)"
    )


def test_remaining_fallback_text_avoids_repeating_identical_stream_text():
    assert _remaining_fallback_text("Loading image", "Loading image") == ""


def test_chat_stream_appends_final_image_markdown_after_loading_delta(monkeypatch):
    image_url = "https://images.example/generated.png"
    update = {
        "type": 1,
        "target": "update",
        "arguments": [{"writeAtCursor": "Loading image"}],
    }
    complete = {
        "type": 2,
        "item": {
            "messages": [
                {
                    "author": "bot",
                    "text": "Loading image",
                    "adaptiveCards": [{"body": [{"type": "Image", "url": image_url}]}],
                }
            ]
        },
    }

    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            self.sent.append(data)

        async def recv(self):
            return "{}" + SIGNALR_SEP

        def __aiter__(self):
            self._messages = iter(
                [
                    json.dumps(update) + SIGNALR_SEP,
                    json.dumps(complete) + SIGNALR_SEP,
                    json.dumps({"type": 3}) + SIGNALR_SEP,
                ]
            )
            return self

        async def __anext__(self):
            try:
                return next(self._messages)
            except StopIteration:
                raise StopAsyncIteration

    monkeypatch.setattr(substrate_client.websockets, "connect", lambda *args, **kwargs: FakeWebSocket())
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._tone = "Magic"
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"

    async def collect():
        return [
            chunk
            async for chunk in client._chat_stream_for_turn(
                text="帮我生成图片",
                conv_id="conv",
                session_id="session",
                is_start_of_session=True,
            )
        ]

    assert asyncio.run(collect()) == ["Loading image", f"\n\n![image]({image_url})"]
