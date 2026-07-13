from __future__ import annotations

import pytest

from m365_copilot_openai_proxy.models import AnthropicMessage, AnthropicMessagesRequest, ContentPart
from m365_copilot_openai_proxy.translator import translate_anthropic_request


def _system_context(translated) -> str:
    """Return the injected 'System instructions:' block, or '' if none."""
    for ctx in translated.additional_context:
        if ctx.startswith("System instructions:\n"):
            return ctx[len("System instructions:\n"):]
    return ""


def test_anthropic_system_accepts_plain_string():
    request = AnthropicMessagesRequest(
        model="claude",
        system="You are a helpful assistant.",
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    translated = translate_anthropic_request(request)

    assert translated.prompt == "hi"
    assert _system_context(translated) == "You are a helpful assistant."


def test_anthropic_system_accepts_text_content_block_array():
    """Claude Code sends system as [{type:"text", text:"..."}]; both blocks must
    be flattened into a single system instruction."""
    request = AnthropicMessagesRequest(
        model="claude",
        system=[
            ContentPart(type="text", text="Block one."),
            ContentPart(type="text", text="Block two."),
        ],
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    translated = translate_anthropic_request(request)

    assert _system_context(translated) == "Block one.Block two."


def test_anthropic_system_ignores_non_text_blocks():
    """Only type=='text' blocks contribute; other block types are dropped."""
    request = AnthropicMessagesRequest(
        model="claude",
        system=[
            ContentPart(type="text", text="Keep me."),
            ContentPart(type="image", text=None),
        ],
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    translated = translate_anthropic_request(request)

    assert _system_context(translated) == "Keep me."


def test_anthropic_system_none_yields_no_system_context():
    request = AnthropicMessagesRequest(
        model="claude",
        system=None,
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    translated = translate_anthropic_request(request)

    assert _system_context(translated) == ""


def test_anthropic_requires_final_user_message():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[AnthropicMessage(role="assistant", content="I am last")],
    )

    with pytest.raises(ValueError):
        translate_anthropic_request(request)
