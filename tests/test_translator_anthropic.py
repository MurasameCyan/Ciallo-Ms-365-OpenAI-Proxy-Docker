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


def test_anthropic_message_role_accepts_system():
    """OpenAI->Anthropic bridging clients (e.g. desktop-cc-gui) put a system
    message inside messages[]; the model must not reject it with a 422."""
    message = AnthropicMessage(role="system", content="You are helpful.")

    assert message.role == "system"


def test_anthropic_system_message_folds_into_system_context():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(role="user", content="hi"),
            AnthropicMessage(role="system", content="You are helpful."),
            AnthropicMessage(role="user", content="你是什么模型"),
        ],
    )

    translated = translate_anthropic_request(request)

    assert translated.prompt == "你是什么模型"
    assert _system_context(translated) == "You are helpful."
    # The system message must not leak into the transcript.
    transcript = [c for c in translated.additional_context if c.startswith("Prior conversation")]
    assert transcript == ["Prior conversation transcript:\nUser: hi"]


def test_anthropic_system_message_merges_with_top_level_system():
    request = AnthropicMessagesRequest(
        model="claude",
        system="Top level.",
        messages=[
            AnthropicMessage(role="system", content="From messages."),
            AnthropicMessage(role="user", content="hi"),
        ],
    )

    translated = translate_anthropic_request(request)

    assert _system_context(translated) == "Top level.\nFrom messages."


def test_anthropic_trailing_system_message_still_finds_user_prompt():
    """A system message in the last slot must not trigger the
    'final message must be a user message' error."""
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(role="user", content="你是什么模型"),
            AnthropicMessage(role="system", content="Be concise."),
        ],
    )

    translated = translate_anthropic_request(request)

    assert translated.prompt == "你是什么模型"
    assert _system_context(translated) == "Be concise."


def test_anthropic_system_message_content_block_array_is_flattened():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(
                role="system",
                content=[
                    ContentPart(type="text", text="Part one. "),
                    ContentPart(type="text", text="Part two."),
                ],
            ),
            AnthropicMessage(role="user", content="hi"),
        ],
    )

    translated = translate_anthropic_request(request)

    assert _system_context(translated) == "Part one. Part two."


def test_anthropic_incremental_tool_result_omits_already_seen_turns():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(role="user", content="original-user-sentinel"),
            AnthropicMessage(
                role="assistant",
                content=[ContentPart.model_validate({
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Read",
                    "input": {"file_path": "/tmp/a.txt"},
                })],
            ),
            AnthropicMessage(
                role="user",
                content=[ContentPart.model_validate({
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "tool-result-sentinel",
                })],
            ),
        ],
    )

    translated = translate_anthropic_request(request, incremental=True)
    context = "\n".join(translated.additional_context)

    assert "tool-result-sentinel" in context
    assert "original-user-sentinel" not in context
    assert "Assistant called tool: Read" not in context


def test_anthropic_empty_system_message_adds_no_system_context():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(role="system", content="   "),
            AnthropicMessage(role="user", content="hi"),
        ],
    )

    translated = translate_anthropic_request(request)

    assert _system_context(translated) == ""


def test_anthropic_all_system_messages_still_requires_user():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[AnthropicMessage(role="system", content="Only system.")],
    )

    with pytest.raises(ValueError):
        translate_anthropic_request(request)


def test_anthropic_system_message_keeps_images_on_final_user_turn():
    """Images must still be picked up from the last user turn when a system
    message follows it in messages[]."""
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(
                role="user",
                content=[
                    ContentPart(type="text", text="look"),
                    ContentPart.model_validate({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
                    }),
                ],
            ),
            AnthropicMessage(role="system", content="Be brief."),
        ],
    )

    translated = translate_anthropic_request(request)

    assert translated.prompt == "look"
    assert len(translated.images) == 1
    assert translated.images[0].base64 == "QUJD"
