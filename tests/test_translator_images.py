from __future__ import annotations

from m365_copilot_openai_proxy.models import (
    ContentPart,
    OpenAIChatRequest,
    OpenAIMessage,
)
from m365_copilot_openai_proxy.translator import (
    extract_images,
    extract_images_from_dicts,
    translate_openai_request,
)

# "hello" base64-encoded; content value is irrelevant to extraction.
_B64 = "aGVsbG8="
_PNG_DATA_URL = f"data:image/png;base64,{_B64}"


def test_extract_images_openai_image_url_data_url():
    parts = [
        ContentPart(type="text", text="what is this"),
        ContentPart(type="image_url", image_url={"url": _PNG_DATA_URL}),
    ]

    images = extract_images(parts)

    assert len(images) == 1
    assert images[0].base64 == _B64
    assert images[0].media_type == "image/png"
    assert images[0].file_name.endswith(".png")


def test_extract_images_skips_remote_http_url():
    """M365 UploadFile only accepts inline base64; remote URLs cannot be
    forwarded and must be dropped rather than sent as a broken reference."""
    parts = [
        ContentPart(type="image_url", image_url={"url": "https://example.com/cat.png"}),
    ]

    assert extract_images(parts) == []


def test_extract_images_anthropic_base64_source():
    parts = [
        ContentPart(
            type="image",
            source={"type": "base64", "media_type": "image/jpeg", "data": _B64},
        ),
    ]

    images = extract_images(parts)

    assert len(images) == 1
    assert images[0].base64 == _B64
    assert images[0].media_type == "image/jpeg"
    assert images[0].file_name.endswith(".jpg")


def test_extract_images_text_only_returns_empty():
    assert extract_images("just a string") == []
    assert extract_images([ContentPart(type="text", text="hi")]) == []


def test_extract_images_from_dicts_responses_input_image():
    content = [
        {"type": "input_text", "text": "describe"},
        {"type": "input_image", "image_url": {"url": _PNG_DATA_URL}},
    ]

    images = extract_images_from_dicts(content)

    assert len(images) == 1
    assert images[0].base64 == _B64
    assert images[0].media_type == "image/png"


def test_translate_openai_request_carries_images_on_last_user_message():
    request = OpenAIChatRequest(
        model="m365-copilot",
        messages=[
            OpenAIMessage(
                role="user",
                content=[
                    ContentPart(type="text", text="what is in this image"),
                    ContentPart(type="image_url", image_url={"url": _PNG_DATA_URL}),
                ],
            )
        ],
    )

    translated = translate_openai_request(request)

    assert translated.prompt == "what is in this image"
    assert len(translated.images) == 1
    assert translated.images[0].base64 == _B64
