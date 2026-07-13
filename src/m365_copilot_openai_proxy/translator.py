from __future__ import annotations

import json
import re
from typing import Iterable

from .models import (
    AnthropicMessagesRequest,
    ContentPart,
    ImageData,
    OpenAIChatRequest,
    OpenAIResponsesRequest,
    ToolCall,
    TranslatedRequest,
)


def flatten_content(content: str | list[ContentPart] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(part.text or "" for part in content if part.type == "text")


# data:<media_type>;base64,<data>
_DATA_URL_RE = re.compile(r"^data:(?P<media>[^;,]+);base64,(?P<data>.+)$", re.DOTALL)

_MEDIA_TYPE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
}


def _ext_from_media_type(media_type: str) -> str:
    return _MEDIA_TYPE_EXT.get(media_type.lower(), "png")


def _image_from_url(url: str, index: int) -> ImageData | None:
    """Build ImageData from a data: URL (inline base64) or an http(s) URL.

    For data URLs the base64 bytes are extracted inline. For http(s) URLs the
    bytes are not fetched here; the returned ImageData carries ``url`` and its
    base64 is filled in later by downloading (see
    SubstrateCopilotClient._upload_images). Returns None for unusable input."""
    url = url.strip()
    match = _DATA_URL_RE.match(url)
    if match:
        media_type = match.group("media").strip() or "image/png"
        data = match.group("data").strip()
        if not data:
            return None
        return ImageData(
            base64=data,
            media_type=media_type,
            file_name=f"upload-{index}.{_ext_from_media_type(media_type)}",
        )
    if url.startswith(("http://", "https://")):
        return ImageData(
            url=url,
            file_name=f"upload-{index}",
        )
    return None


def _part_field(part: ContentPart, key: str):
    """Read an extra (non-text) field off a ContentPart (extra='allow')."""
    value = getattr(part, key, None)
    if value is not None:
        return value
    extra = getattr(part, "model_extra", None) or {}
    return extra.get(key)


def extract_images_from_dicts(content: list) -> list[ImageData]:
    """Extract images from Responses-style dict content parts.

    Handles OpenAI Responses ``input_image``/``image_url`` (data URL or http(s))
    and Anthropic-style ``image`` (source.type == base64). Remote http(s) URLs
    are carried on ImageData.url and downloaded at upload time.
    """
    images: list[ImageData] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype in ("image_url", "input_image"):
            image_url = part.get("image_url")
            url = ""
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "")
            elif isinstance(image_url, str):
                url = image_url
            if url:
                img = _image_from_url(url, len(images))
                if img:
                    images.append(img)
        elif ptype == "image":
            source = part.get("source")
            if isinstance(source, dict) and source.get("type") == "base64":
                data = str(source.get("data") or "")
                media_type = str(source.get("media_type") or "image/png")
                if data:
                    images.append(ImageData(
                        base64=data,
                        media_type=media_type,
                        file_name=f"upload-{len(images)}.{_ext_from_media_type(media_type)}",
                    ))
    return images


def extract_images(content: str | list[ContentPart] | None) -> list[ImageData]:
    """Extract images from OpenAI/Anthropic multimodal content.

    Supports OpenAI ``image_url`` parts (data URL or http(s)) and Anthropic
    ``image`` parts (source.type == base64). Remote http(s) URLs are carried on
    ImageData.url and downloaded at upload time; unknown parts are ignored.
    """
    if not isinstance(content, list):
        return []
    images: list[ImageData] = []
    for part in content:
        ptype = getattr(part, "type", None)
        if ptype in ("image_url", "input_image"):
            image_url = _part_field(part, "image_url")
            url = ""
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "")
            elif isinstance(image_url, str):
                url = image_url
            if url:
                img = _image_from_url(url, len(images))
                if img:
                    images.append(img)
        elif ptype == "image":
            source = _part_field(part, "source")
            if isinstance(source, dict) and source.get("type") == "base64":
                data = str(source.get("data") or "")
                media_type = str(source.get("media_type") or "image/png")
                if data:
                    images.append(ImageData(
                        base64=data,
                        media_type=media_type,
                        file_name=f"upload-{len(images)}.{_ext_from_media_type(media_type)}",
                    ))
    return images


def _join_lines(lines: Iterable[str]) -> str:
    return "\n".join(line for line in lines if line).strip()


# Default system-level instruction block injected before the (dynamic) tool list.
# Users may override this via the web admin page; the dynamic "Available action types"
# list is always appended automatically and is NOT part of the editable text.
_DEFAULT_TOOL_SYSTEM_PROMPT = (
    "You are the reasoning component of an automated agent system. You do NOT execute anything yourself. "
    "Your ONLY job is to emit structured action requests as JSON. A separate execution engine (the IDE host) "
    "receives your JSON, runs the action on its side, and sends you the result back. "
    "You never touch any filesystem — you only decide WHICH action to request, and the host performs it.\n\n"
    "Because the host performs all actions, you must NEVER reply with phrases like "
    "\"I cannot access files\", \"I am a cloud assistant\", \"I am in a sandbox\", or \"the path does not exist\". "
    "Those statements are wrong in this system: you are not the executor. Just emit the action request and the host handles the rest.\n\n"
    "To request an action, output a fenced code block tagged `tool_call` containing a single JSON object:\n"
    "```tool_call\n"
    '{"name": "<tool_name>", "arguments": {<key-value pairs>}}\n'
    "```\n\n"
    "Rules:\n"
    "- If the user asks to only analyze/review/read, or says not to modify/write/save/run/delete files, treat the task as read-only: request Read/search actions only and never request Write, Edit, Delete, or command execution.\n"
    "- To read a file, emit a Read action request. Do NOT claim you cannot read it — the host reads it and returns the content.\n"
    "- To create or write a file, emit a Write action request with the full content. Do NOT paste the content as a normal code block.\n"
    "- To modify a file, emit an Edit action request. Do NOT just describe the change.\n"
    "- Emit ONLY the tool_call block when an action is needed (optionally a short sentence before it). Wait for the host's result before continuing.\n"
    "- Use the exact file paths given by the user verbatim (including Windows drive letters like S:\\...). The host resolves them, not you.\n"
    "- NEVER claim an action is done unless you actually emitted its tool_call block in THIS reply. Do NOT say \"已生成\", \"已创建\", \"已保存\", \"已校验\", \"file created\", \"done\", or similar before the host has run the action and returned a result. Saying a file exists without emitting a Write tool_call is a hallucination and is forbidden.\n"
    "- To deliver file content you MUST emit a Write tool_call whose `content` argument holds the FULL file body. NEVER substitute a markdown link like [name](file:///...), a normal code block, or a usage/run command for the actual Write action — those do not create the file.\n\n"
    "Examples:\n"
    "Read a file:\n"
    "```tool_call\n"
    '{"name": "Read", "arguments": {"file_path": "S:/path/to/file"}}\n'
    "```\n\n"
    "Write a file:\n"
    "```tool_call\n"
    '{"name": "Write", "arguments": {"file_path": "S:/path/to/file", "content": "file content here"}}\n'
    "```\n\n"
    "Edit a file:\n"
    "```tool_call\n"
    '{"name": "Edit", "arguments": {"file_path": "S:/path/to/file", "old_string": "text to replace", "new_string": "replacement text"}}\n'
    "```"
)


def default_tool_system_prompt() -> str:
    """Return the built-in default system-level tool-call instruction (for restore/display)."""
    return _DEFAULT_TOOL_SYSTEM_PROMPT


def _format_tools_prompt(tools, system_override: str | None = None) -> str | None:
    """Format tool definitions into a system-level prompt so the model knows about available tools.

    The static instruction block can be overridden by the user (system_override); the
    dynamic tool list is always appended automatically.
    """
    if not tools:
        return None
    tool_descriptions = []
    for tool in tools:
        func = tool.function
        desc = f"- {func.name}: {func.description or 'No description'}"
        if func.parameters:
            props = func.parameters.get("properties", {})
            required = func.parameters.get("required", [])
            param_parts = []
            for pname, pdef in props.items():
                ptype = pdef.get("type", "any")
                pdesc = pdef.get("description", "")
                req_flag = " (required)" if pname in required else ""
                param_parts.append(f"    - {pname}: {ptype}{req_flag} — {pdesc}")
            if param_parts:
                desc += "\n  Parameters:\n" + "\n".join(param_parts)
        tool_descriptions.append(desc)
    base = (system_override or "").strip() or _DEFAULT_TOOL_SYSTEM_PROMPT
    return (
        base + "\n\n"
        "Available action types (tool_name and arguments):\n" + "\n".join(tool_descriptions)
    )


def _format_tool_results(tool_calls: list[ToolCall] | None, content: str, name: str | None, tool_call_id: str | None) -> str:
    """Format a tool role message into human-readable text."""
    parts = []
    if name:
        parts.append(f"Tool result from {name}")
    elif tool_call_id:
        parts.append(f"Tool result (id: {tool_call_id})")
    if content:
        parts.append(content)
    return "\n".join(parts)


def translate_openai_request(request: OpenAIChatRequest, incremental: bool = False, system_override: str | None = None) -> TranslatedRequest:
    system_lines: list[str] = []
    transcript_lines: list[str] = []
    prompt = ""
    images: list[ImageData] = []

    # Inject tool definitions into system context
    tools_prompt = _format_tools_prompt(request.tools, system_override)
    if tools_prompt:
        system_lines.append(tools_prompt)

    # In incremental (persistent-session continuation) mode, the M365 server already
    # remembers everything up to and including its last assistant response. Only the
    # content AFTER the last assistant message is new (the latest user turn plus any
    # locally-executed tool results). We drop older transcript lines to avoid resending
    # the whole history each turn. System/tool instructions are always kept.
    last_assistant_index = -1
    if incremental:
        for i, m in enumerate(request.messages):
            if m.role == "assistant":
                last_assistant_index = i

    for index, message in enumerate(request.messages):
        is_last = index == len(request.messages) - 1
        # Skip already-seen transcript content in incremental mode (but never skip the
        # last message, which becomes the prompt, nor system/developer instructions).
        skip_transcript = (
            incremental
            and index <= last_assistant_index
            and not is_last
            and message.role not in {"system", "developer"}
        )

        # Handle tool result messages
        if message.role == "tool":
            text = _format_tool_results(
                message.tool_calls,
                flatten_content(message.content),
                message.name,
                message.tool_call_id,
            )
            if not skip_transcript:
                transcript_lines.append(f"Tool: {text}")
            # If this tool result is the last message (agentic loop: the host executed
            # a tool and sent the result back with no trailing user turn), synthesize a
            # continuation prompt so the model keeps going instead of erroring out.
            if is_last:
                prompt = (
                    "The tool action you requested has been executed by the host and the "
                    "result is shown above. Continue the task: if more actions are needed, "
                    "emit the next tool_call; otherwise give the user your final answer."
                )
            continue

        text = flatten_content(message.content).strip()

        # Handle assistant messages with tool_calls
        if message.role == "assistant" and message.tool_calls:
            tool_call_texts = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    tool_call_texts.append(f"Assistant called tool: {tc.function.name}({json.dumps(args, ensure_ascii=False)})")
                except (json.JSONDecodeError, TypeError):
                    tool_call_texts.append(f"Assistant called tool: {tc.function.name}({tc.function.arguments})")
            if text:
                tool_call_texts.insert(0, f"Assistant: {text}")
            if not skip_transcript:
                transcript_lines.append("\n".join(tool_call_texts))
            if is_last:
                prompt = (
                    "Continue the task based on the conversation above. If more actions "
                    "are needed, emit the next tool_call; otherwise give your final answer."
                )
            continue

        if not text:
            continue
        if message.role in {"system", "developer"}:
            system_lines.append(text)
            continue
        if is_last:
            if message.role != "user":
                raise ValueError("The final OpenAI message must be a user message.")
            prompt = text
            images = extract_images(message.content)
            continue
        if not skip_transcript:
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
    return TranslatedRequest(prompt=prompt, additional_context=additional_context, images=images)


def translate_responses_request(request: OpenAIResponsesRequest) -> TranslatedRequest:
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
    images: list[ImageData] = []
    items = request.input
    for index, item in enumerate(items):
        role = item.get("role", "") if isinstance(item, dict) else ""
        raw_content = item.get("content", "") if isinstance(item, dict) else str(item)
        if isinstance(raw_content, list):
            content = "".join(p.get("text", "") for p in raw_content if isinstance(p, dict) and p.get("type") in ("text", "input_text"))
        else:
            content = raw_content
        text = content.strip()
        is_last = index == len(items) - 1
        # The final user turn may carry images (and possibly no text), so extract
        # before the empty-text skip below would otherwise drop an image-only turn.
        if is_last and role == "user" and isinstance(raw_content, list):
            images = extract_images_from_dicts(raw_content)
        if not text and not (is_last and images):
            continue
        if role in {"system", "developer"}:
            system_lines.append(text)
            continue
        if is_last:
            if role != "user":
                raise ValueError("The final Responses input message must be a user message.")
            prompt = text
            continue
        transcript_lines.append(f"{role.capitalize()}: {text}")
    if not prompt and not images:
        raise ValueError("No user message found in input.")
    additional_context: list[str] = []
    system_text = _join_lines(system_lines)
    if system_text:
        additional_context.append(f"System instructions:\n{system_text}")
    transcript_text = _join_lines(transcript_lines)
    if transcript_text:
        additional_context.append(f"Prior conversation transcript:\n{transcript_text}")
    return TranslatedRequest(prompt=prompt, additional_context=additional_context, images=images)


def translate_anthropic_request(
    request: AnthropicMessagesRequest,
) -> TranslatedRequest:
    system_text = flatten_content(request.system).strip()
    transcript_lines: list[str] = []
    prompt = ""
    images: list[ImageData] = []

    for index, message in enumerate(request.messages):
        text = flatten_content(message.content).strip()
        is_last = index == len(request.messages) - 1
        if is_last:
            if message.role != "user":
                raise ValueError("The final Anthropic message must be a user message.")
            prompt = text
            images = extract_images(message.content)
            continue
        if not text:
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
    return TranslatedRequest(prompt=prompt, additional_context=additional_context, images=images)
