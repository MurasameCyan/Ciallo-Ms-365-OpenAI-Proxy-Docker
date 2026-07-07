from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy import substrate_client
from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient, _message_content, _remaining_fallback_text


def test_message_content_suppresses_loading_placeholder_when_image_exists():
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

    assert _message_content(entry) == "![image](https://images.example/generated.png)"


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


def test_message_content_normalizes_raw_bang_backtick_designer_image_text():
    image_url = "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fgenerated.png&fileToken=abc"
    entry = {
        "author": "bot",
        "text": f"! `{image_url}` ",
    }

    assert _message_content(entry) == f"![image]({image_url})"


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


def test_remaining_fallback_text_avoids_repeating_media_citation_variant():
    media_url = "https://kr-prod.asyncgw.teams.microsoft.com/v1/objects/0-ea-d6-7546f952f230bb9dd3cd0c17061b0ed3/views/original/bird_chirp.wav"
    streamed = f"已为你生成一段模拟小鸟叫声的 WAV 音频：\n\n `{media_url}` \n\n如果需要不同风格，我也可以生成对应版本。"
    fallback = "已为你生成一段模拟小鸟叫声的 WAV 音频：\n\n[下载小鸟叫声](\ue200cite\ue202turn3file1\ue201)\n\n如果需要不同风格，我也可以生成对应版本。"

    assert _remaining_fallback_text(streamed, fallback) == ""


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

    assert asyncio.run(collect()) == [f"![image]({image_url})"]


def test_chat_stream_appends_image_reference_url_from_final_progress_message(monkeypatch):
    image_url = "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fgenerated.png&fileToken=abc"
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
                    "contentType": "GraphicArt",
                    "contentGenerationProgressList": [
                        {
                            "contentType": "image",
                            "ImageReferenceUrls": [f" `{image_url}` "],
                            "status": 2,
                        }
                    ],
                }
            ]
        },
    }

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            return None

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

    assert asyncio.run(collect()) == [f"![image]({image_url})"]



def test_chat_stream_outputs_single_image_reference_url_without_loading_placeholder(monkeypatch):
    image_url = "https://designerapp.officeapps.live.com/designerapp/document.ashx?path=%2Fgenerated.png&fileToken=abc"
    progress_without_image = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {
                        "author": "bot",
                        "text": "Loading image",
                        "contentType": "GraphicArt",
                        "contentGenerationProgressList": [
                            {"contentType": "image", "ImageReferenceUrls": []}
                        ],
                    }
                ]
            }
        ],
    }
    progress_with_image = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {
                        "author": "bot",
                        "text": "Loading image",
                        "contentType": "GraphicArt",
                        "contentGenerationProgressList": [
                            {
                                "contentType": "image",
                                "ImageReferenceUrls": [f" `{image_url}` "],
                                "status": 2,
                            }
                        ],
                    }
                ]
            }
        ],
    }

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            return None

        async def recv(self):
            return "{}" + SIGNALR_SEP

        def __aiter__(self):
            self._messages = iter(
                [
                    json.dumps(progress_without_image) + SIGNALR_SEP,
                    json.dumps(progress_with_image) + SIGNALR_SEP,
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

    assert asyncio.run(collect()) == [f"![image]({image_url})"]



def test_chat_stream_captures_suspicious_signalr_event_for_debug(monkeypatch):
    captured = []
    event = {
        "type": 1,
        "target": "update",
        "arguments": [{"writeAtCursor": "Loading image", "operation": "imageGenerationProgress"}],
    }

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            return None

        async def recv(self):
            return "{}" + SIGNALR_SEP

        def __aiter__(self):
            self._messages = iter([json.dumps(event) + SIGNALR_SEP, json.dumps({"type": 3}) + SIGNALR_SEP])
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
    client._response_debug_sink = captured.append

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

    assert asyncio.run(collect()) == []
    assert captured == [event]



def test_chat_stream_appends_image_markdown_from_event_level_payload(monkeypatch):
    image_url = "https://images.example/generated-from-event.png"
    update = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "writeAtCursor": "Loading image",
                "renderedContent": {
                    "cards": [
                        {
                            "kind": "generatedImage",
                            "images": [{"url": image_url}],
                        }
                    ]
                },
            }
        ],
    }

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            return None

        async def recv(self):
            return "{}" + SIGNALR_SEP

        def __aiter__(self):
            self._messages = iter([json.dumps(update) + SIGNALR_SEP, json.dumps({"type": 3}) + SIGNALR_SEP])
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

    assert asyncio.run(collect()) == [f"![image]({image_url})"]
