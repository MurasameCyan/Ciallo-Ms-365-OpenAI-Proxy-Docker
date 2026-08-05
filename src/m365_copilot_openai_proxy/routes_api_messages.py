from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .call_log_store import append_call_log, record_response_text
from .config import Settings
from .models import AnthropicMessagesRequest
from .response_helpers import _anthropic_stream
from .routes_api_common import (
    effective_run_permission,
    request_model_alias,
    resolve_request_tone,
    upstream_http_error,
)
from .routes_media_proxy import request_media_rewriter
from .session_helpers import _messages_session_key, _persistent_session
from .session_store import PersistentSession
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError
from .tone_resolver import normalized_session_model
from .tool_call_parser import (
    _RETRY_INSTRUCTION,
    _extract_prose_write,
    _extract_tool_calls,
    _filter_read_only_tool_calls,
    _has_read_only_intent,
    _looks_like_fake_file_claim,
    _strip_tool_call_blocks,
)
from .translator import effective_tools, flatten_content, normalize_tool_choice, translate_anthropic_request


def _tool_use_blocks(tool_calls: list[dict]) -> list[dict]:
    """Convert parsed OpenAI-shaped tool_calls into Anthropic ``tool_use`` blocks.

    Anthropic carries the arguments as a decoded ``input`` object, not the JSON
    string OpenAI uses, so a client that cannot parse a string payload still sees
    a usable tool call.
    """
    blocks: list[dict] = []
    for call in tool_calls:
        fn = call.get("function") or {}
        raw = fn.get("arguments")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None
        blocks.append({
            "type": "tool_use",
            "id": call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
            "name": fn.get("name") or "tool",
            "input": parsed if isinstance(parsed, dict) else {"raw": raw},
        })
    return blocks


def register_messages_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[[Request], SubstrateCopilotClient],
) -> None:
    @app.post("/v1/messages")
    async def anthropic_messages(
        raw_request: Request,
        request: AnthropicMessagesRequest,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        _log = logging.getLogger("copilot_proxy")
        model_alias = request_model_alias(app, raw_request, settings)
        # Effective list, not the raw one: tool_choice={"type":"none"} empties it so
        # parsing and the corrective retry are disabled along with the prompt
        # injection, and {"type":"tool","name":X} narrows it to X.
        choice = normalize_tool_choice(request.tool_choice)
        _tools = effective_tools(request.tools, choice)
        tool_names = {t.name for t in _tools if getattr(t, "name", "")} if _tools else set()
        try:
            # The requested model name selects the conversation tone (and its
            # persistent variant); override the client tone and normalize the
            # persist marker for _persistent_session's suffix check.
            resolved_tone, _is_persist = resolve_request_tone(app, request.model)
            client._tone = resolved_tone
            # System prompt: the key's own override wins, else the global one --
            # same precedence the OpenAI chat route uses.
            _key_obj = getattr(raw_request.state, "api_key_obj", None)
            _key_sp = ((_key_obj.system_prompt if _key_obj is not None else "") or "").strip()
            _system_override = _key_sp or getattr(app.state, "system_prompt", "")
            run_permission = effective_run_permission(app, _key_obj)
            read_only_guard = run_permission == "read_only" or _has_read_only_intent(
                *(flatten_content(m.content) for m in request.messages if m.role == "user")
            )
            translated = translate_anthropic_request(request, system_override=_system_override)
            session = _persistent_session(app, raw_request, normalized_session_model(request.model), _messages_session_key(request), request)
            media_rewriter = request_media_rewriter(app, raw_request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        call_record = {
            "api": "anthropic",
            "endpoint": "/v1/messages",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": sorted(tool_names),
            "tool_choice": choice[0],
            "messages": len(request.messages),
            "model": request.model,
            "tone": resolved_tone,
            "run_permission": run_permission,
            "read_only_guard": read_only_guard,
            "tool_calls_result": None if request.stream else [],
        }

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            if tool_names:
                # Tools present: buffer the turn so tool_call blocks can be parsed
                # out and re-emitted as Anthropic tool_use content blocks.
                return StreamingResponse(
                    _anthropic_stream_with_tools(
                        model_alias,
                        client,
                        translated.prompt,
                        translated.additional_context,
                        session,
                        call_record=call_record,
                        tool_names=tool_names,
                        read_only_guard=read_only_guard,
                        text_transform=media_rewriter,
                        images=translated.images,
                        on_text_done=lambda text: record_response_text(app.state, call_record, text),
                    ),
                    media_type="text/event-stream",
                )
            return StreamingResponse(
                _anthropic_stream(
                    model_alias,
                    client,
                    translated.prompt,
                    translated.additional_context,
                    session,
                    on_text_done=lambda text: record_response_text(app.state, call_record, text),
                    text_transform=media_rewriter,
                    images=translated.images,
                ),
                media_type="text/event-stream",
            )

        try:
            raw_text = await client.chat(translated.prompt, translated.additional_context, session, translated.images)
        except SubstrateCopilotError as exc:
            raise upstream_http_error(exc) from exc

        # Parse the RAW model text, never the media-rewritten one. The rewriter
        # base64-encodes the source URL into a ?u= parameter, which destroys the
        # file extension _looks_like_fake_file_claim keys on -- so a natively
        # generated file (hosted URL, no tool_call) slipped past the corrective
        # retry. Rewriting is a delivery concern and is applied further down, to
        # the prose only, so it can also never touch a Write's file content.
        tool_calls = _resolve_tool_calls(raw_text, tool_names, read_only_guard)
        if not tool_calls and tool_names and not read_only_guard and _looks_like_fake_file_claim(raw_text):
            _log.info("  fake file claim detected, forcing corrective retry")
            try:
                retry_text = await client.chat(_RETRY_INSTRUCTION, translated.additional_context, session)
                retry_calls = _resolve_tool_calls(retry_text, tool_names, read_only_guard)
                if retry_calls:
                    raw_text, tool_calls = retry_text, retry_calls
                    call_record["retried"] = True
            except SubstrateCopilotError:
                pass  # Keep original response if retry fails

        record_response_text(app.state, call_record, raw_text)
        call_record["tool_calls_result"] = [b["name"] for b in _tool_use_blocks(tool_calls)] if tool_calls else []
        append_call_log(app.state, call_record)

        if tool_calls:
            remaining = media_rewriter(_strip_tool_call_blocks(raw_text))
            content: list[dict] = []
            if remaining:
                content.append({"type": "text", "text": remaining})
            content.extend(_tool_use_blocks(tool_calls))
            return JSONResponse({
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "model": model_alias,
                "content": content,
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            })

        return JSONResponse({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": model_alias,
            "content": [{"type": "text", "text": media_rewriter(raw_text)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })


def _resolve_tool_calls(text: str, tool_names: set, read_only_guard: bool) -> list[dict]:
    """Parse tool_calls out of model text, applying the same guards as the chat path."""
    if not tool_names:
        return []
    _log = logging.getLogger("copilot_proxy")
    tool_calls = _extract_tool_calls(text)
    if read_only_guard and tool_calls:
        blocked = len(tool_calls)
        tool_calls = _filter_read_only_tool_calls(tool_calls)
        if len(tool_calls) != blocked:
            _log.info("  read-only guard filtered mutating tool_call(s)")
    if not tool_calls and not read_only_guard:
        tool_calls = _extract_prose_write(text, tool_names)
        if tool_calls:
            _log.info("  prose fallback synthesized Write tool_call")
    return tool_calls


async def _anthropic_stream_with_tools(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
    call_record: dict | None = None,
    tool_names: set | None = None,
    read_only_guard: bool = False,
    text_transform: Callable[[str], str] | None = None,
    images: list | None = None,
    on_text_done: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """Buffer the turn, then emit Anthropic tool_use blocks if tool_calls are found.

    Mirrors ``_openai_stream_with_tools``: the tool_call contract is prompt-based,
    so the fenced block only becomes parseable once the whole answer has arrived.
    """
    _log = logging.getLogger("copilot_proxy")
    msg_id = f"msg_{uuid.uuid4().hex}"

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    try:
        chunks: list[str] = []
        async for delta in client.chat_stream(prompt, additional_context, session, images):
            chunks.append(delta)
        # Parsing runs on the RAW text: the media rewriter base64-encodes the
        # source URL into a ?u= parameter, erasing the file extension that
        # _looks_like_fake_file_claim needs to spot a natively generated file.
        # Rewriting happens at delivery time, over the prose only.
        full_text = "".join(chunks)

        tool_calls = _resolve_tool_calls(full_text, tool_names or set(), read_only_guard)
        if not tool_calls and tool_names and not read_only_guard and _looks_like_fake_file_claim(full_text):
            _log.info("  fake file claim detected, forcing corrective retry")
            retry_chunks: list[str] = []
            async for delta in client.chat_stream(_RETRY_INSTRUCTION, additional_context, session):
                retry_chunks.append(delta)
            retry_text = "".join(retry_chunks)
            retry_calls = _resolve_tool_calls(retry_text, tool_names or set(), read_only_guard)
            if retry_calls:
                full_text, tool_calls = retry_text, retry_calls
                if call_record is not None:
                    call_record["retried"] = True
    except SubstrateCopilotError as exc:
        yield sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant", "content": [], "model": model_alias, "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})
        yield sse("error", {"type": "error", "error": {"type": "upstream_error", "message": str(exc)}})
        if on_text_done is not None:
            on_text_done("")
        return

    blocks = _tool_use_blocks(tool_calls)
    text_out = _strip_tool_call_blocks(full_text) if tool_calls else full_text
    if text_transform is not None:
        text_out = text_transform(text_out)
    if call_record is not None:
        call_record["tool_calls_result"] = [b["name"] for b in blocks]
    if blocks:
        _log.info("[anthropic_stream_with_tools] tool_use blocks: %s", [b["name"] for b in blocks])

    yield sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant", "content": [], "model": model_alias, "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})
    index = 0
    # A text block is always opened at index 0 so clients that assume one exists
    # stay happy; it just carries an empty string when the whole reply was a call.
    yield sse("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})
    if text_out:
        yield sse("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text_out}})
    yield sse("content_block_stop", {"type": "content_block_stop", "index": index})

    for block in blocks:
        index += 1
        yield sse("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}})
        # Anthropic streams tool arguments as incremental input_json_delta; the
        # buffered payload is sent as a single complete chunk.
        yield sse("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)}})
        yield sse("content_block_stop", {"type": "content_block_stop", "index": index})

    stop_reason = "tool_use" if blocks else "end_turn"
    yield sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": 0}})
    yield sse("message_stop", {"type": "message_stop"})
    if on_text_done is not None:
        on_text_done(full_text)
