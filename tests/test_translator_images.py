from __future__ import annotations

import pytest

from m365_copilot_openai_proxy.models import (
    AnthropicMessage,
    AnthropicMessagesRequest,
    ContentPart,
    OpenAIChatRequest,
    OpenAIMessage,
    OpenAIResponsesRequest,
)
from m365_copilot_openai_proxy.translator import (
    extract_images,
    extract_images_from_dicts,
    translate_anthropic_request,
    translate_openai_request,
    translate_responses_request,
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


def test_extract_images_carries_remote_http_url():
    """Remote http(s) URLs are carried on ImageData.url (base64 empty) and are
    downloaded later at upload time, rather than being dropped at extraction."""
    parts = [
        ContentPart(type="image_url", image_url={"url": "https://example.com/cat.png"}),
    ]

    images = extract_images(parts)

    assert len(images) == 1
    assert images[0].url == "https://example.com/cat.png"
    assert images[0].base64 == ""


def test_extract_images_skips_unusable_non_http_non_data_url():
    """A bare relative/unknown-scheme reference is neither inline nor fetchable
    and must be dropped rather than sent as a broken reference."""
    parts = [
        ContentPart(type="image_url", image_url={"url": "cat.png"}),
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


_JPG_DATA_URL = f"data:image/jpeg;base64,{_B64}"


def test_extract_images_multiple_preserves_order_and_indexes_filenames():
    """Multiple images in one message are all extracted, in order, and each gets
    a distinct index-based file_name so uploads don't collide."""
    parts = [
        ContentPart(type="text", text="compare these"),
        ContentPart(type="image_url", image_url={"url": _PNG_DATA_URL}),
        ContentPart(type="image_url", image_url={"url": _JPG_DATA_URL}),
    ]

    images = extract_images(parts)

    assert len(images) == 2
    assert images[0].media_type == "image/png"
    assert images[0].file_name == "upload-0.png"
    assert images[1].media_type == "image/jpeg"
    assert images[1].file_name == "upload-1.jpg"


def test_extract_images_multiple_mixed_inline_and_remote():
    """A mix of inline (data URL) and remote (http) images is fully preserved:
    inline carries base64, remote carries url for later download."""
    parts = [
        ContentPart(type="image_url", image_url={"url": _PNG_DATA_URL}),
        ContentPart(type="image_url", image_url={"url": "https://example.com/b.png"}),
    ]

    images = extract_images(parts)

    assert len(images) == 2
    assert images[0].base64 == _B64 and images[0].url == ""
    assert images[1].base64 == "" and images[1].url == "https://example.com/b.png"


def test_translate_openai_request_carries_multiple_images():
    request = OpenAIChatRequest(
        model="m365-copilot",
        messages=[
            OpenAIMessage(
                role="user",
                content=[
                    ContentPart(type="text", text="compare"),
                    ContentPart(type="image_url", image_url={"url": _PNG_DATA_URL}),
                    ContentPart(type="image_url", image_url={"url": _JPG_DATA_URL}),
                ],
            )
        ],
    )

    translated = translate_openai_request(request)

    assert len(translated.images) == 2


# --- image-only turns (no text part at all) --------------------------------
#
# Measured 2026-09-04 against the live substrate: a turn whose only content is
# an image and whose text is empty comes back with a real description of the
# picture. The OpenAI path used to refuse it (the empty-text skip ran before the
# last message was claimed, dropping the images with it) while the other two
# sent it, so the same request 400'd on one endpoint and worked on two.

_IMAGE_ONLY_OPENAI = [ContentPart(type="image_url", image_url={"url": _PNG_DATA_URL})]
_IMAGE_ONLY_ANTHROPIC = [
    ContentPart(
        type="image",
        source={"type": "base64", "media_type": "image/png", "data": _B64},
    )
]
_IMAGE_ONLY_RESPONSES = [
    {"role": "user", "content": [{"type": "input_image", "image_url": {"url": _PNG_DATA_URL}}]}
]


def _openai(parts, **kwargs):
    return translate_openai_request(
        OpenAIChatRequest(
            model="m365-copilot",
            messages=[OpenAIMessage(role="user", content=parts)],
        ),
        **kwargs,
    )


def _anthropic(parts, **kwargs):
    return translate_anthropic_request(
        AnthropicMessagesRequest(
            model="m365-copilot",
            max_tokens=64,
            messages=[AnthropicMessage(role="user", content=parts)],
        ),
        **kwargs,
    )


def _responses(items, **kwargs):
    return translate_responses_request(
        OpenAIResponsesRequest(model="m365-copilot", input=items), **kwargs
    )


def test_openai_image_only_turn_keeps_the_image_and_an_empty_prompt():
    translated = _openai(_IMAGE_ONLY_OPENAI)

    assert translated.prompt == ""
    assert len(translated.images) == 1
    assert translated.images[0].base64 == _B64


def test_anthropic_image_only_turn_keeps_the_image_and_an_empty_prompt():
    translated = _anthropic(_IMAGE_ONLY_ANTHROPIC)

    assert translated.prompt == ""
    assert len(translated.images) == 1


def test_responses_image_only_turn_keeps_the_image_and_an_empty_prompt():
    translated = _responses(_IMAGE_ONLY_RESPONSES)

    assert translated.prompt == ""
    assert len(translated.images) == 1


def test_openai_last_user_message_with_neither_text_nor_image_is_still_refused():
    """Claiming the last message early must not turn a genuinely empty turn into
    an empty prompt sent upstream."""
    with pytest.raises(ValueError, match="final user message is required"):
        _openai([ContentPart(type="text", text="   ")])


def test_openai_last_message_from_the_assistant_is_still_refused():
    """The role check moved out of the last-message branch; it must still fire."""
    with pytest.raises(ValueError, match="must be a user message"):
        translate_openai_request(
            OpenAIChatRequest(
                model="m365-copilot",
                messages=[
                    OpenAIMessage(role="user", content="hi"),
                    OpenAIMessage(role="assistant", content="hello"),
                ],
            )
        )


# --- Consumer accounts upload images too -----------------------------------
#
# The bridge used to drop inbound images, so an image-only turn was refused here
# with a 400 rather than reaching upstream as an empty text part. It now uploads
# them (`ConsumerCopilotClient._upload_images` -> `/c/api/attachments`, measured
# 2026-09-04 against the live account: the model named both halves of a freshly
# minted two-colour PNG), so translation must hand the images on for Consumer
# exactly as it does for M365 -- no provider branch at all. consumer_tool_max_chars
# is the provider signal: the routes pass the budget for Consumer, None for M365.
_CONSUMER = {"consumer_tool_max_chars": 8000}


@pytest.mark.parametrize(
    "translate, parts",
    [
        (_openai, _IMAGE_ONLY_OPENAI),
        (_anthropic, _IMAGE_ONLY_ANTHROPIC),
        (_responses, _IMAGE_ONLY_RESPONSES),
    ],
    ids=["openai", "anthropic", "responses"],
)
def test_consumer_image_only_turn_is_translated_not_refused(translate, parts):
    translated = translate(parts, **_CONSUMER)

    assert translated.prompt == ""
    assert len(translated.images) == 1


def test_consumer_turn_carrying_both_text_and_image_keeps_both():
    translated = _openai(
        [ContentPart(type="text", text="what is this"), *_IMAGE_ONLY_OPENAI],
        **_CONSUMER,
    )

    assert translated.prompt == "what is this"
    assert len(translated.images) == 1
    assert translated.images[0].base64 == _B64
