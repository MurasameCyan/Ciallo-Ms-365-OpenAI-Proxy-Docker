from __future__ import annotations

from typing import Iterable

from .models import (
    AnthropicMessagesRequest,
    ContentPart,
    OpenAIChatRequest,
    TranslatedRequest,
)


def flatten_content(content: str | list[ContentPart] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(part.text or "" for part in content if part.type == "text")


def _join_lines(lines: Iterable[str]) -> str:
    return "\n".join(line for line in lines if line).strip()


def translate_openai_request(request: OpenAIChatRequest) -> TranslatedRequest:
    system_lines: list[str] = []
    transcript_lines: list[str] = []
    prompt = ""

    for index, message in enumerate(request.messages):
        text = flatten_content(message.content).strip()
        if not text:
            continue
        is_last = index == len(request.messages) - 1
        if message.role in {"system", "developer"}:
            system_lines.append(text)
            continue
        if is_last:
            if message.role != "user":
                raise ValueError("The final OpenAI message must be a user message.")
            prompt = text
            continue
        transcript_lines.append(f"{message.role.capitalize()}: {text}")

    if not prompt:
        raise ValueError("A final user message is required.")

    additional_context: list[str] = []
    system_text = _join_lines(system_lines)
    if system_text:
        additional_context.append(f"System instructions:\n{system_text}")
    transcript_text = _join_lines(transcript_lines)
    if transcript_text:
        additional_context.append(f"Prior conversation transcript:\n{transcript_text}")
    return TranslatedRequest(prompt=prompt, additional_context=additional_context)


def translate_responses_request(request: "OpenAIResponsesRequest") -> TranslatedRequest:
    from .models import OpenAIResponsesRequest
    instructions = request.instructions or ""
    if isinstance(request.input, str):
        return TranslatedRequest(
            prompt=request.input,
            additional_context=[f"System instructions:\n{instructions}"] if instructions else [],
        )
    # input is a list of message dicts
    system_lines: list[str] = []
    if instructions:
        system_lines.append(instructions)
    transcript_lines: list[str] = []
    prompt = ""
    items = request.input
    for index, item in enumerate(items):
        role = item.get("role", "") if isinstance(item, dict) else ""
        content = item.get("content", "") if isinstance(item, dict) else str(item)
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in ("text", "input_text"))
        text = content.strip()
        if not text:
            continue
        is_last = index == len(items) - 1
        if role in {"system", "developer"}:
            system_lines.append(text)
            continue
        if is_last:
            if role != "user":
                raise ValueError("The final Responses input message must be a user message.")
            prompt = text
            continue
        transcript_lines.append(f"{role.capitalize()}: {text}")
    if not prompt:
        raise ValueError("No user message found in input.")
    additional_context: list[str] = []
    system_text = _join_lines(system_lines)
    if system_text:
        additional_context.append(f"System instructions:\n{system_text}")
    transcript_text = _join_lines(transcript_lines)
    if transcript_text:
        additional_context.append(f"Prior conversation transcript:\n{transcript_text}")
    return TranslatedRequest(prompt=prompt, additional_context=additional_context)


def translate_anthropic_request(
    request: AnthropicMessagesRequest,
) -> TranslatedRequest:
    system_text = flatten_content(request.system).strip()
    transcript_lines: list[str] = []
    prompt = ""

    for index, message in enumerate(request.messages):
        text = flatten_content(message.content).strip()
        if not text:
            continue
        is_last = index == len(request.messages) - 1
        if is_last:
            if message.role != "user":
                raise ValueError("The final Anthropic message must be a user message.")
            prompt = text
            continue
        transcript_lines.append(f"{message.role.capitalize()}: {text}")

    if not prompt:
        raise ValueError("A final user message is required.")

    additional_context: list[str] = []
    if system_text:
        additional_context.append(f"System instructions:\n{system_text}")
    transcript_text = _join_lines(transcript_lines)
    if transcript_text:
        additional_context.append(f"Prior conversation transcript:\n{transcript_text}")
    return TranslatedRequest(prompt=prompt, additional_context=additional_context)
