from __future__ import annotations

import json
import re
from typing import Iterable
from urllib.parse import unquote

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012, UnknownDialect, specification_with

from .consumer_prompt import validate_consumer_required_content
from .models import (
    AnthropicMessagesRequest,
    ContentPart,
    ImageData,
    OpenAIChatRequest,
    OpenAIResponsesRequest,
    ToolCall,
    ToolDefinition,
    ToolFunction,
    TranslatedRequest,
)
from .tool_call_parser import _NO_TOOL_MARKER


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
    "- To deliver file content you MUST emit a Write tool_call whose `content` argument holds the FULL file body. NEVER substitute a markdown link like [name](file:///...), a normal code block, or a usage/run command for the actual Write action — those do not create the file.\n"
    "- Do NOT generate, upload, or attach a file of your own, and do NOT return a download link to one. A file you host is not the file the user asked for: it never reaches the path they named, and the host cannot act on it. Write it to their path with a Write tool_call instead.\n"
    "- If you will not emit a tool_call block, then write the answer inline as text: state the destination as a backticked absolute path (`S:/dir/name.ext`) on its own line, followed by the complete file body in a fenced code block tagged with the file's language (```bat, ```python, ```html). Never send an attachment in place of this.\n\n"
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


def normalize_tool_choice(tool_choice, parallel_tool_calls=None) -> tuple[str, str | None, bool]:
    """Collapse both APIs' tool_choice shapes into ``(mode, name, allow_parallel)``.

    ``mode`` is one of ``auto`` / ``none`` / ``required`` / ``tool``; ``name`` is
    set only for ``tool``. OpenAI passes a bare string or ``{"type":"function",
    "function":{"name":...}}``; Anthropic passes ``{"type":"auto|any|tool|none"}``
    with the name flat on the object and parallelism as
    ``disable_parallel_tool_use``. Unknown values fall back to ``auto`` -- the
    API default -- so a client sending a shape we do not know still gets tools.
    """
    mode, name = "auto", None
    allow_parallel = parallel_tool_calls is not False

    if isinstance(tool_choice, str):
        # OpenAI: "none" | "auto" | "required". Legacy clients also send a bare
        # tool name, which the spec never allowed but is unambiguous.
        lowered = tool_choice.strip().lower()
        if lowered in ("none", "auto", "required"):
            mode = lowered
        elif lowered:
            mode, name = "tool", tool_choice.strip()
    elif isinstance(tool_choice, dict):
        raw_type = str(tool_choice.get("type") or "").strip().lower()
        function = tool_choice.get("function")
        fn_name = function.get("name") if isinstance(function, dict) else None
        # Anthropic keeps the name flat; OpenAI nests it under `function`.
        picked = (fn_name or tool_choice.get("name") or "").strip() or None
        if raw_type in ("function", "tool") or (not raw_type and picked):
            mode, name = ("tool", picked) if picked else ("required", None)
        elif raw_type == "any":  # Anthropic's "call some tool"
            mode = "required"
        elif raw_type in ("none", "auto", "required"):
            mode = raw_type
        if tool_choice.get("disable_parallel_tool_use") is True:
            allow_parallel = False

    return mode, name, allow_parallel


def effective_tools(tools, choice: tuple[str, str | None, bool]):
    """The tool list that actually applies, honouring ``tool_choice``.

    ``none`` returns ``[]`` so every downstream consumer -- prompt injection,
    response parsing, the prose-write fallback and the corrective retry -- sees a
    request with no tools. Withholding the contract is a local decision and thus
    the one part of tool_choice that is fully reliable; the forced modes only
    nudge the upstream model, which may still ignore them.

    ``tool`` narrows the list to the named tool when it exists, so a model that
    complies cannot pick a different one. An unknown name is left alone rather
    than emptying the list: the client asked for something we cannot see, and
    silently dropping every tool would look like the request had none.
    """
    mode, name, _ = choice
    if mode == "none":
        return []
    if mode == "tool" and name:
        narrowed = [t for t in (tools or []) if _tool_name(t) == name]
        if narrowed:
            return narrowed
    return tools


def _tool_name(tool) -> str:
    """Tool name from either API's shape (OpenAI nests it, Anthropic keeps it flat)."""
    function = getattr(tool, "function", None)
    return (getattr(function, "name", None) or getattr(tool, "name", "") or "").strip()


def _tool_namespace_label(function) -> str:
    namespace = (getattr(function, "namespace", None) or "").strip()
    if not namespace:
        return ""
    description = (getattr(function, "namespace_description", None) or "").strip()
    detail = f"namespace {namespace}"
    if description:
        detail += f": {description}"
    return f" [{detail}]"


def _tool_choice_instruction(mode: str, name: str | None, allow_parallel: bool) -> str | None:
    """The extra instruction line a non-default tool_choice implies, if any."""
    lines = []
    if mode == "required":
        lines.append(
            "You MUST call one of the tools listed above for this turn. Emit a "
            "tool_call block; do not answer in prose instead."
        )
    elif mode == "tool" and name:
        lines.append(
            f"You MUST call the tool named {name} for this turn, and no other "
            f"tool. Emit a tool_call block for it; do not answer in prose instead."
        )
    if not allow_parallel:
        lines.append("Emit at most ONE tool_call for this turn, never several.")
    return "\n".join(lines) if lines else None


def tool_description_lines(tools) -> list[str]:
    """One human-readable block per tool: name, description, parameter signatures.

    Shared by the two injection shapes -- the native fenced-block contract below
    and the router prompt in ``tool_router`` -- so a tool reads identically to the
    model whichever mode is planning the turn.
    """
    tool_descriptions = []
    for tool in tools:
        func = tool.function
        desc = (
            f"- {func.name}{_tool_namespace_label(func)}: "
            f"{func.description or 'No description'}"
        )
        if func.parameters:
            schema = func.parameters
            prompt_schema = _schema_prompt_view(schema, schema)
            props = (
                prompt_schema.get("properties", {})
                if isinstance(prompt_schema, dict)
                else {}
            )
            required = (
                prompt_schema.get("required", [])
                if isinstance(prompt_schema, dict)
                else []
            )
            param_parts = []
            for pname, pdef in props.items():
                ptype = _compact_schema_signature(pdef, root_schema=schema)
                prompt_definition = _schema_prompt_view(pdef, schema)
                pdesc = (
                    prompt_definition.get("description", "")
                    if isinstance(prompt_definition, dict)
                    else ""
                )
                req_flag = " (required)" if pname in required else ""
                param_parts.append(f"    - {pname}: {ptype}{req_flag} — {pdesc}")
            if param_parts:
                desc += "\n  Parameters:\n" + "\n".join(param_parts)
        tool_descriptions.append(desc)
    return tool_descriptions


def _format_tools_prompt(
    tools,
    system_override: str | None = None,
    choice: tuple[str, str | None, bool] | None = None,
) -> str | None:
    """Format tool definitions into a system-level prompt so the model knows about available tools.

    The static instruction block can be overridden by the user (system_override); the
    dynamic tool list is always appended automatically.
    """
    if not tools:
        return None
    tool_descriptions = tool_description_lines(tools)
    base = (system_override or "").strip() or _DEFAULT_TOOL_SYSTEM_PROMPT
    out = (
        base + "\n\n"
        "Available action types (tool_name and arguments):\n" + "\n".join(tool_descriptions)
    )
    # Appended outside the admin-overridable base so the signal survives a custom
    # system prompt. Without it, "no tool_call in the reply" is ambiguous between a
    # deliberate no-action answer and a model that ignored the contract.
    out += (
        "\n\nIf the request needs no action at all, answer it normally and end your "
        f"reply with the single token {_NO_TOOL_MARKER} on its own line, so the host "
        "can tell a deliberate no-action answer apart from a missed action request."
    )
    # A forced choice goes last so it sits closest to the prompt, matching where
    # the [FORMAT] block puts the instructions the model follows most reliably.
    if choice is not None:
        extra = _tool_choice_instruction(*choice)
        if extra:
            out += "\n\n" + extra
    return out


_CONSUMER_TOOL_BUDGET_ERROR = (
    "Consumer Copilot prompt budget cannot fit the required tool signatures"
)


def _local_schema_ref_target(
    schema: dict,
    root_schema: dict,
) -> dict | bool | None:
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None
    if ref == "#":
        return root_schema
    if not ref.startswith("#/"):
        anchor = unquote(ref[1:])
        legacy_id_keyword = None
        dialect = root_schema.get("$schema")
        if isinstance(dialect, str):
            try:
                dialect_name = specification_with(dialect).name
            except UnknownDialect:
                dialect_name = ""
            if dialect_name == "draft-04":
                legacy_id_keyword = "id"
            elif dialect_name in {"draft-06", "draft-07"}:
                legacy_id_keyword = "$id"
        pending = [root_schema]
        while pending:
            candidate = pending.pop()
            if isinstance(candidate, dict):
                if (
                    anchor
                    in {
                        candidate.get("$anchor"),
                        candidate.get("$dynamicAnchor"),
                    }
                    or (
                        legacy_id_keyword is not None
                        and candidate.get(legacy_id_keyword) == ref
                    )
                ):
                    return candidate
                pending.extend(candidate.values())
            elif isinstance(candidate, list):
                pending.extend(candidate)
        return None

    target = root_schema
    for raw_token in ref[2:].split("/"):
        token = unquote(raw_token).replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict) and token in target:
            target = target[token]
        elif isinstance(target, list) and token.isdigit():
            index = int(token)
            if index >= len(target):
                return None
            target = target[index]
        else:
            return None
    return target if isinstance(target, (dict, bool)) else None


def _schema_prompt_view(schema, root_schema: dict):
    """Resolve one local ref for compact prompt rendering."""
    if not isinstance(schema, dict):
        return schema
    target = _local_schema_ref_target(schema, root_schema)
    if target is None:
        return schema

    dialect = root_schema.get("$schema")
    if isinstance(dialect, str):
        try:
            legacy_ref = specification_with(dialect).name in {
                "draft-04",
                "draft-06",
                "draft-07",
            }
        except UnknownDialect:
            legacy_ref = False
        if legacy_ref:
            return target

    siblings = {key: value for key, value in schema.items() if key != "$ref"}
    if not siblings:
        return target
    if target is True:
        return siblings
    if target is False:
        return False
    merged = {**target, **siblings}
    target_properties = target.get("properties")
    sibling_properties = siblings.get("properties")
    if isinstance(target_properties, dict) and isinstance(sibling_properties, dict):
        merged_properties = dict(target_properties)
        for name, definition in sibling_properties.items():
            target_definition = merged_properties.get(name)
            if isinstance(target_definition, dict) and isinstance(definition, dict):
                merged_properties[name] = {**target_definition, **definition}
            else:
                merged_properties[name] = definition
        merged["properties"] = merged_properties
    target_required = target.get("required")
    sibling_required = siblings.get("required")
    if isinstance(target_required, list) and isinstance(sibling_required, list):
        merged["required"] = list(dict.fromkeys([*target_required, *sibling_required]))
    # ponytail: this is a prompt summary, not a schema compiler; jsonschema
    # remains authoritative for overlapping non-object constraints.
    return merged


def _compact_schema_signature(
    schema,
    depth: int = 0,
    root_schema: dict | None = None,
) -> str:
    """Render JSON Schema without descriptions, examples, titles, or defaults."""
    if isinstance(schema, bool):
        return "any" if schema else "never"
    if not isinstance(schema, dict):
        return "any"
    if root_schema is None:
        root_schema = schema
    if depth >= 12:
        raw_type = schema.get("type")
        if isinstance(raw_type, str) and raw_type:
            return raw_type
        if isinstance(schema.get("properties"), dict):
            return "object"
        if "items" in schema:
            return "array"
        return "any"

    prompt_schema = _schema_prompt_view(schema, root_schema)
    if prompt_schema is not schema:
        return _compact_schema_signature(prompt_schema, depth + 1, root_schema)

    alternatives = schema.get("oneOf") or schema.get("anyOf")
    if isinstance(alternatives, list) and alternatives:
        kind = "oneOf" if schema.get("oneOf") else "anyOf"
        rendered = f"{kind}<" + " | ".join(
            _compact_schema_signature(option, depth + 1, root_schema)
            for option in alternatives
        ) + ">"
    else:
        raw_type = schema.get("type")
        if isinstance(raw_type, list):
            rendered = "|".join(str(item) for item in raw_type)
        elif isinstance(raw_type, str) and raw_type:
            rendered = raw_type
        elif isinstance(schema.get("properties"), dict):
            rendered = "object"
        elif "items" in schema:
            rendered = "array"
        else:
            rendered = "any"

        if rendered == "object":
            properties = schema.get("properties")
            if isinstance(properties, dict) and properties:
                required = schema.get("required")
                required_names = set(required) if isinstance(required, list) else set()
                fields = []
                for name, definition in properties.items():
                    marker = " required" if name in required_names else ""
                    fields.append(
                        f"{name}: {_compact_schema_signature(definition, depth + 1, root_schema)}{marker}"
                    )
                rendered += "{" + "; ".join(fields) + "}"
        elif rendered == "array":
            items = schema.get("items")
            if isinstance(items, list):
                item_signature = " | ".join(
                    _compact_schema_signature(item, depth + 1, root_schema)
                    for item in items
                )
            else:
                item_signature = _compact_schema_signature(
                    items,
                    depth + 1,
                    root_schema,
                )
            rendered += f"<{item_signature}>"

    if "enum" in schema:
        rendered += " enum=" + json.dumps(
            schema["enum"], ensure_ascii=False, separators=(",", ":")
        )
    if "const" in schema:
        rendered += " const=" + json.dumps(
            schema["const"], ensure_ascii=False, separators=(",", ":")
        )
    return rendered


def _format_consumer_tools_contract(
    tools,
    choice: tuple[str, str | None, bool],
    max_chars: int,
) -> str | None:
    """Build the complete, compact tool contract used only by Consumer Copilot."""
    if not tools:
        return None

    tool_lines = []
    for tool in tools:
        func = tool.function
        name = (func.name or "").strip()
        if not name:
            continue
        schema = func.parameters if isinstance(func.parameters, dict) else {}
        prompt_schema = _schema_prompt_view(schema, schema)
        properties = (
            prompt_schema.get("properties")
            if isinstance(prompt_schema, dict)
            else None
        )
        required = (
            prompt_schema.get("required")
            if isinstance(prompt_schema, dict)
            else None
        )
        required_names = set(required) if isinstance(required, list) else set()
        params = []
        if isinstance(properties, dict):
            for param_name, definition in properties.items():
                marker = " required" if param_name in required_names else ""
                params.append(
                    f"{param_name}: {_compact_schema_signature(definition, root_schema=schema)}{marker}"
                )
        elif schema:
            params.append(
                "arguments: "
                f"{_compact_schema_signature(prompt_schema, root_schema=schema)}"
            )
        tool_lines.append(
            f"- {name}({'; '.join(params)}){_tool_namespace_label(func)}"
        )

    if not tool_lines:
        return None

    mode, selected_name, allow_parallel = choice
    if mode == "required":
        choice_line = "MUST request one listed tool."
    elif mode == "tool" and selected_name:
        choice_line = f"MUST request only tool named {selected_name}."
    else:
        choice_line = "Tool use is optional."
    parallel_line = (
        "Multiple tool calls are allowed; use one tool_call block per call."
        if allow_parallel
        else "Request at most one tool call."
    )
    contract = "\n".join([
        "Consumer tool contract:",
        "You do not execute tools. The client executes requests you emit as:",
        "```tool_call",
        '{"name":"<exact tool name>","arguments":{}}',
        "```",
        "Available tools:",
        *tool_lines,
        choice_line,
        parallel_line,
    ])
    if len(contract) > max_chars:
        raise ValueError(_CONSUMER_TOOL_BUDGET_ERROR)
    return contract


def _anthropic_tools_as_openai(tools) -> list[ToolDefinition]:
    """Adapt Anthropic tool definitions to the OpenAI shape.

    Anthropic keeps ``name``/``description``/``input_schema`` flat on the tool;
    OpenAI nests them under ``function`` with the schema called ``parameters``.
    Re-shaping here lets the Anthropic path reuse ``_format_tools_prompt`` (and
    the admin-editable system prompt it renders) unchanged.
    """
    adapted: list[ToolDefinition] = []
    for tool in tools or []:
        name = (getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        schema = getattr(tool, "input_schema", None)
        if schema is None:
            extra = getattr(tool, "model_extra", None) or {}
            schema = extra.get("parameters")
        adapted.append(ToolDefinition(function=ToolFunction(
            name=name,
            description=getattr(tool, "description", None),
            parameters=schema if isinstance(schema, dict) else None,
        )))
    return adapted


def _anthropic_tool_blocks(content) -> tuple[list[str], list[str]]:
    """Split Anthropic ``tool_use`` / ``tool_result`` blocks out of message content.

    Claude-style clients carry the agentic loop inside content blocks: the
    assistant's request is a ``tool_use`` block, and the host's answer comes back
    as a ``tool_result`` block on a *user* message. ``flatten_content`` only reads
    ``text`` blocks, so without this both halves vanished and the model never saw
    that its tool call had run. Returns (tool_use lines, tool_result lines) in the
    same wording ``translate_openai_request`` uses for its transcript.
    """
    uses: list[str] = []
    results: list[str] = []
    if not isinstance(content, list):
        return uses, results
    for part in content:
        ptype = getattr(part, "type", None)
        if ptype == "tool_use":
            name = _part_field(part, "name") or "tool"
            args = _part_field(part, "input")
            try:
                rendered = json.dumps(args, ensure_ascii=False) if args is not None else "{}"
            except (TypeError, ValueError):
                rendered = str(args)
            uses.append(f"Assistant called tool: {name}({rendered})")
        elif ptype == "tool_result":
            body = _part_field(part, "content")
            if isinstance(body, list):
                text = "".join(
                    str(block.get("text") or "")
                    for block in body
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            else:
                text = "" if body is None else str(body)
            label = "Tool result"
            if _part_field(part, "is_error"):
                label = "Tool error"
            results.append(f"Tool: {label}\n{text}".rstrip())
    return uses, results


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


def translate_openai_request(
    request: OpenAIChatRequest,
    incremental: bool = False,
    system_override: str | None = None,
    consumer_tool_max_chars: int | None = None,
) -> TranslatedRequest:
    system_lines: list[str] = []
    transcript_lines: list[str] = []
    prompt = ""
    images: list[ImageData] = []
    consumer_tools_contract = None

    # Inject tool definitions into system context. tool_choice="none" means the
    # client forbids tool calls this turn, so the whole tool contract is withheld
    # -- see effective_tools(), which the route uses to disable parsing to match.
    choice = normalize_tool_choice(request.tool_choice, getattr(request, "parallel_tool_calls", None))
    tools = effective_tools(request.tools, choice)
    if consumer_tool_max_chars is None:
        tools_prompt = _format_tools_prompt(tools, system_override, choice)
        if tools_prompt:
            system_lines.append(tools_prompt)
    else:
        consumer_tools_contract = _format_consumer_tools_contract(
            tools, choice, consumer_tool_max_chars
        )
        if consumer_tools_contract and (system_override or "").strip():
            system_lines.append(system_override.strip())

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

    if consumer_tools_contract:
        validate_consumer_required_content(
            prompt, consumer_tools_contract, consumer_tool_max_chars
        )

    additional_context: list[str] = []
    if consumer_tools_contract:
        additional_context.append(consumer_tools_contract)
    system_text = _join_lines(system_lines)
    if system_text:
        additional_context.append(f"System instructions:\n{system_text}")
    transcript_text = _join_lines(transcript_lines)
    if transcript_text:
        additional_context.append(f"Prior conversation transcript:\n{transcript_text}")
    return TranslatedRequest(prompt=prompt, additional_context=additional_context, images=images)


def _schema_validator_and_specification(schema: dict):
    dialect = schema.get("$schema")
    if dialect is None:
        return Draft202012Validator, DRAFT202012
    if not isinstance(dialect, str):
        raise ValueError("Responses JSON Schema $schema must be a string.")
    try:
        specification = specification_with(dialect)
    except UnknownDialect as exc:
        raise ValueError(
            f"Unsupported Responses JSON Schema dialect: {dialect}."
        ) from exc
    return validator_for(schema), specification


def _validate_local_schema_references(
    schema: dict,
    validator_class,
    specification,
) -> None:
    """Reject references that cannot resolve within the submitted schema."""
    root = specification.create_resource(schema)
    resolver = Registry().resolver_with_root(root)

    def visit(contents, current_resolver) -> None:
        if isinstance(contents, dict):
            for ref_keyword in ("$ref", "$recursiveRef", "$dynamicRef"):
                if (
                    ref_keyword in validator_class.VALIDATORS
                    and ref_keyword in contents
                ):
                    current_resolver.lookup(contents[ref_keyword])
        for subcontents in specification.subresources_of(contents):
            subresource = specification.create_resource(subcontents)
            visit(
                subcontents,
                current_resolver.in_subresource(subresource),
            )

    visit(schema, resolver)


def _adapt_responses_function_tool(
    tool: dict,
    *,
    namespace: str | None = None,
    namespace_description: str | None = None,
) -> ToolDefinition:
    supported_fields = {
        "type", "name", "description", "parameters", "strict",
        "allowed_callers", "defer_loading", "output_schema",
    }
    unknown_fields = sorted(set(tool) - supported_fields)
    if unknown_fields:
        raise ValueError(
            "Responses function tool fields are not supported by this proxy: "
            + ", ".join(unknown_fields)
            + "."
        )
    unsupported_semantics = [
        field
        for field in ("allowed_callers", "output_schema")
        if tool.get(field) is not None
    ]
    if tool.get("defer_loading") not in (None, False):
        unsupported_semantics.append("defer_loading")
    if unsupported_semantics:
        raise ValueError(
            "Responses function tool fields are not supported by this proxy: "
            + ", ".join(unsupported_semantics)
            + "."
        )
    name = tool.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Responses function tools require a non-empty name.")
    parameters = tool.get("parameters")
    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError("Responses function tool parameters must be an object.")
    if isinstance(parameters, dict):
        properties = parameters.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise ValueError(
                "Responses function tool parameter properties must be an object."
            )
        if isinstance(properties, dict) and any(
            not isinstance(schema, (dict, bool))
            for schema in properties.values()
        ):
            raise ValueError(
                "Responses function tool property schemas must be objects."
            )
        required = parameters.get("required")
        if required is not None and (
            not isinstance(required, list)
            or any(not isinstance(name, str) for name in required)
        ):
            raise ValueError(
                "Responses function tool required must be an array of strings."
            )
        try:
            validator_class, specification = _schema_validator_and_specification(
                parameters
            )
            validator_class.check_schema(parameters)
            if tool.get("strict") is True:
                _validate_local_schema_references(
                    parameters,
                    validator_class,
                    specification,
                )
        except SchemaError as exc:
            raise ValueError(
                "Responses function tool parameters must be valid JSON Schema: "
                f"{exc.message}"
            ) from exc
        except Unresolvable as exc:
            raise ValueError(
                "Responses strict function tool references must be locally "
                f"resolvable: {exc}"
            ) from exc
        except RecursionError as exc:
            raise ValueError(
                "Responses function tool parameters are too deeply nested."
            ) from exc
    description = tool.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("Responses function tool description must be a string.")
    strict = tool.get("strict", False)
    if strict is None:
        strict = False
    if not isinstance(strict, bool):
        raise ValueError("Responses function tool strict must be a boolean.")
    return ToolDefinition(function=ToolFunction(
        name=name.strip(),
        description=description,
        parameters=parameters,
        strict=strict,
        namespace=namespace,
        namespace_description=namespace_description,
    ))


def responses_tools_as_openai(tools: list[dict] | None) -> list[ToolDefinition]:
    """Flatten supported Responses function tools into the shared OpenAI shape."""
    adapted: list[ToolDefinition] = []
    seen_namespaces: dict[str, str | None] = {}

    def add_function(tool: dict, namespace: str | None = None, description=None):
        if tool.get("type") != "function":
            if namespace is not None:
                raise ValueError(
                    "Responses namespace tools must contain only function tools."
                )
            raise ValueError(
                "Responses only function tools are supported by this proxy; "
                "OpenAI hosted tools are unavailable."
            )
        definition = _adapt_responses_function_tool(
            tool,
            namespace=namespace,
            namespace_description=description,
        )
        name = definition.function.name
        if name in seen_namespaces:
            raise ValueError(
                f"Responses tools contain duplicate function name '{name}'."
            )
        seen_namespaces.setdefault(name, namespace)
        adapted.append(definition)

    for tool in tools or []:
        if not isinstance(tool, dict):
            raise ValueError("Responses tools must be JSON objects.")
        if tool.get("type") != "namespace":
            add_function(tool)
            continue

        unknown_fields = sorted(set(tool) - {"type", "name", "description", "tools"})
        if unknown_fields:
            raise ValueError(
                "Responses namespace fields are not supported by this proxy: "
                + ", ".join(unknown_fields)
                + "."
            )
        namespace = tool.get("name")
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("Responses namespaces require a non-empty name.")
        description = tool.get("description")
        if not isinstance(description, str):
            raise ValueError("Responses namespace description must be a string.")
        nested_tools = tool.get("tools")
        if not isinstance(nested_tools, list):
            raise ValueError("Responses namespace tools must be an array.")
        namespace = namespace.strip()
        for nested_tool in nested_tools:
            if not isinstance(nested_tool, dict):
                raise ValueError("Responses namespace tools must be JSON objects.")
            add_function(nested_tool, namespace, description)
    return adapted


def responses_tool_config(
    tools: list[dict] | None,
    tool_choice,
    parallel_tool_calls=None,
) -> tuple[tuple[str, str | None, bool], list[ToolDefinition]]:
    """Validate Responses tool fields and return normalized choice + tools."""
    adapted = responses_tools_as_openai(tools)
    allow_parallel = parallel_tool_calls is not False

    if tool_choice is None:
        choice = ("auto", None, allow_parallel)
    elif isinstance(tool_choice, str):
        mode = tool_choice.strip().lower()
        if mode not in {"auto", "none", "required"}:
            raise ValueError(f"Unsupported Responses tool_choice: {tool_choice}.")
        choice = (mode, None, allow_parallel)
    elif isinstance(tool_choice, dict):
        if tool_choice.get("type") != "function":
            raise ValueError("Unsupported Responses tool_choice object.")
        name = tool_choice.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                "Responses function tool_choice requires a non-empty function name."
            )
        choice = ("tool", name.strip(), allow_parallel)
    else:
        raise ValueError("Unsupported Responses tool_choice value.")

    names = {_tool_name(tool) for tool in adapted}
    if choice[0] == "required" and not names:
        raise ValueError(
            "Responses tool_choice=required requires at least one function tool."
        )
    if choice[0] == "tool" and choice[1] not in names:
        raise ValueError(
            f"Responses tool_choice function '{choice[1]}' is not declared."
        )
    return choice, effective_tools(adapted, choice)


def _responses_content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
            and part.get("type") in {"text", "input_text", "output_text"}
        )
    return "" if content is None else str(content)


def _responses_function_arguments(item: dict) -> str:
    arguments = item.get("arguments")
    if not isinstance(arguments, str):
        raise ValueError(
            "Responses function_call items require arguments as a JSON string."
        )
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Responses function_call arguments must encode a JSON object."
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            "Responses function_call arguments must encode a JSON object."
        )
    return arguments


def _responses_function_output(item: dict) -> str:
    if "output" not in item:
        raise ValueError("Responses function_call_output items require an output.")
    output = item["output"]
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts: list[str] = []
        for part in output:
            if (
                not isinstance(part, dict)
                or part.get("type") not in {"text", "input_text", "output_text"}
                or not isinstance(part.get("text"), str)
            ):
                raise ValueError(
                    "Responses function_call_output output supports only text."
                )
            parts.append(part["text"])
        return "".join(parts)
    raise ValueError("Responses function_call_output output supports only text.")


def _responses_last_action_index(items) -> int | None:
    if not isinstance(items, list):
        return None
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if (
            isinstance(item, dict)
            and item.get("type") in (None, "message")
            and item.get("role") in {"system", "developer"}
        ):
            continue
        return index
    return None


def translate_responses_request(
    request: OpenAIResponsesRequest,
    system_override: str | None = None,
    consumer_tool_max_chars: int | None = None,
    allow_unmatched_function_call_outputs: bool = False,
) -> TranslatedRequest:
    instructions = (request.instructions or "").strip()
    choice, tools = responses_tool_config(
        request.tools,
        request.tool_choice,
        getattr(request, "parallel_tool_calls", None),
    )
    consumer_tools_contract = None
    system_lines: list[str] = []
    if consumer_tool_max_chars is None:
        tools_prompt = _format_tools_prompt(tools, system_override, choice)
        if tools_prompt:
            system_lines.append(tools_prompt)
    else:
        consumer_tools_contract = _format_consumer_tools_contract(
            tools, choice, consumer_tool_max_chars
        )
        if consumer_tools_contract and (system_override or "").strip():
            system_lines.append(system_override.strip())
    if instructions:
        system_lines.append(instructions)

    if isinstance(request.input, str):
        prompt = request.input
        if consumer_tools_contract:
            validate_consumer_required_content(
                prompt, consumer_tools_contract, consumer_tool_max_chars
            )
        additional_context: list[str] = []
        if consumer_tools_contract:
            additional_context.append(consumer_tools_contract)
        system_text = _join_lines(system_lines)
        if system_text:
            additional_context.append(f"System instructions:\n{system_text}")
        return TranslatedRequest(prompt=prompt, additional_context=additional_context)

    items = request.input
    parsed_items: list[tuple[str, dict]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Responses input items must be JSON objects.")
        item_type = item.get("type")
        if item_type == "function_call":
            parsed_items.append(("function_call", item))
        elif item_type == "function_call_output":
            parsed_items.append(("function_call_output", item))
        elif item_type in (None, "message") and isinstance(item.get("role"), str):
            parsed_items.append(("message", item))
        else:
            label = str(item_type or "unknown")
            raise ValueError(f"Unsupported Responses input item type: {label}.")

    last_action_index = _responses_last_action_index(items)
    if last_action_index is None:
        raise ValueError("No user message found in input.")

    transcript_lines: list[str] = []
    prompt = ""
    images: list[ImageData] = []
    function_call_ids: set[str] = set()
    function_output_ids: set[str] = set()
    for index, (kind, item) in enumerate(parsed_items):
        is_last_action = index == last_action_index
        if kind == "function_call":
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id.strip():
                raise ValueError("Responses function_call items require a call_id.")
            call_id = call_id.strip()
            if call_id in function_call_ids:
                raise ValueError(
                    f"Responses input contains duplicate function_call call_id: {call_id}."
                )
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Responses function_call items require a name.")
            namespace = item.get("namespace")
            if namespace is not None and (
                not isinstance(namespace, str) or not namespace.strip()
            ):
                raise ValueError(
                    "Responses function_call namespace must be a non-empty string."
                )
            arguments = _responses_function_arguments(item)
            function_call_ids.add(call_id)
            qualified_name = (
                f"{namespace.strip()}.{name.strip()}"
                if isinstance(namespace, str)
                else name.strip()
            )
            transcript_lines.append(
                f"Assistant called tool (id: {call_id}): {qualified_name}({arguments})"
            )
            if is_last_action:
                raise ValueError(
                    "The final Responses input item must be a user message or function_call_output."
                )
            continue

        if kind == "function_call_output":
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id.strip():
                raise ValueError("Responses function_call_output items require a call_id.")
            call_id = call_id.strip()
            if call_id in function_output_ids:
                raise ValueError(
                    "Responses input contains duplicate function_call_output "
                    f"call_id: {call_id}."
                )
            if call_id not in function_call_ids and not allow_unmatched_function_call_outputs:
                if function_call_ids:
                    raise ValueError(
                        "Responses function_call_output call_id does not match a prior "
                        "function_call."
                    )
                raise ValueError(
                    "Stateless Responses requests must resend the matching "
                    "function_call before each function_call_output."
                )
            output = _responses_function_output(item)
            function_output_ids.add(call_id)
            transcript_lines.append(
                f"Tool: Tool result (id: {call_id})\n{output}".rstrip()
            )
            if is_last_action:
                prompt = (
                    "The tool action you requested has been executed by the host and the "
                    "result is shown above. Continue the task: if more actions are needed, "
                    "emit the next tool_call; otherwise give the user your final answer."
                )
            continue

        role = str(item.get("role") or "")
        raw_content = item.get("content", "")
        text = _responses_content_text(raw_content).strip()
        if role in {"system", "developer"}:
            if text:
                system_lines.append(text)
            continue
        if is_last_action:
            if role != "user":
                raise ValueError("The final Responses input message must be a user message.")
            prompt = text
            if isinstance(raw_content, list):
                images = extract_images_from_dicts(raw_content)
            continue
        if text:
            transcript_lines.append(f"{role.capitalize()}: {text}")

    if not prompt and not images:
        raise ValueError("No user message found in input.")
    if consumer_tools_contract:
        validate_consumer_required_content(
            prompt, consumer_tools_contract, consumer_tool_max_chars
        )
    additional_context: list[str] = []
    if consumer_tools_contract:
        additional_context.append(consumer_tools_contract)
    system_text = _join_lines(system_lines)
    if system_text:
        additional_context.append(f"System instructions:\n{system_text}")
    transcript_text = _join_lines(transcript_lines)
    if transcript_text:
        additional_context.append(f"Prior conversation transcript:\n{transcript_text}")
    return TranslatedRequest(prompt=prompt, additional_context=additional_context, images=images)


def translate_anthropic_request(
    request: AnthropicMessagesRequest,
    system_override: str | None = None,
    consumer_tool_max_chars: int | None = None,
) -> TranslatedRequest:
    system_lines: list[str] = []
    consumer_tools_contract = None

    # Same tool instruction block the OpenAI path injects, so a Claude-style
    # client asking for a file write gets the ```tool_call``` contract too.
    choice = normalize_tool_choice(request.tool_choice)
    tools = _anthropic_tools_as_openai(effective_tools(request.tools, choice))
    if consumer_tool_max_chars is None:
        tools_prompt = _format_tools_prompt(tools, system_override, choice)
        if tools_prompt:
            system_lines.append(tools_prompt)
    else:
        consumer_tools_contract = _format_consumer_tools_contract(
            tools, choice, consumer_tool_max_chars
        )
        if consumer_tools_contract and (system_override or "").strip():
            system_lines.append(system_override.strip())

    top_level_system = flatten_content(request.system).strip()
    if top_level_system:
        system_lines.append(top_level_system)
    transcript_lines: list[str] = []
    prompt = ""
    images: list[ImageData] = []

    # OpenAI->Anthropic bridging clients may put system prompts inside messages[].
    # Those never become the prompt, so the "final message must be user" check
    # applies to the last non-system message instead.
    last_content_index = -1
    for index, message in enumerate(request.messages):
        if message.role != "system":
            last_content_index = index

    for index, message in enumerate(request.messages):
        text = flatten_content(message.content).strip()
        if message.role == "system":
            if text:
                system_lines.append(text)
            continue
        is_last = index == last_content_index
        tool_uses, tool_results = _anthropic_tool_blocks(message.content)
        if is_last:
            if message.role != "user":
                raise ValueError("The final Anthropic message must be a user message.")
            prompt = text
            images = extract_images(message.content)
            if tool_results:
                # Agentic loop: the host ran the tool and sent only its result
                # back, with no new user text. Put the result in the transcript
                # and synthesize the same continuation prompt the OpenAI path
                # uses, so the turn is not rejected as an empty prompt.
                transcript_lines.extend(tool_results)
                if not prompt:
                    prompt = (
                        "The tool action you requested has been executed by the host and the "
                        "result is shown above. Continue the task: if more actions are needed, "
                        "emit the next tool_call; otherwise give the user your final answer."
                    )
            continue
        for line in (*tool_uses, *tool_results):
            transcript_lines.append(line)
        if not text:
            continue
        transcript_lines.append(f"{message.role.capitalize()}: {text}")

    if not prompt and not images:
        raise ValueError("A final user message is required.")

    if consumer_tools_contract:
        validate_consumer_required_content(
            prompt, consumer_tools_contract, consumer_tool_max_chars
        )

    additional_context: list[str] = []
    if consumer_tools_contract:
        additional_context.append(consumer_tools_contract)
    system_text = _join_lines(system_lines)
    if system_text:
        additional_context.append(f"System instructions:\n{system_text}")
    transcript_text = _join_lines(transcript_lines)
    if transcript_text:
        additional_context.append(f"Prior conversation transcript:\n{transcript_text}")
    return TranslatedRequest(prompt=prompt, additional_context=additional_context, images=images)
