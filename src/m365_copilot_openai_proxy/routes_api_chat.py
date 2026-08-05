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
from .models import OpenAIChatRequest
from .response_helpers import _openai_stream
from .routes_api_common import (
    effective_run_permission,
    request_model_alias,
    resolve_request_tone,
)
from .routes_media_proxy import request_media_rewriter
from .session_helpers import _persistent_session
from .tone_resolver import build_models_list, normalized_session_model
from .session_store import PersistentSession
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError
from .tool_call_parser import (
    _RETRY_INSTRUCTION,
    _extract_prose_write,
    _extract_tool_calls,
    _filter_read_only_tool_calls,
    _has_read_only_intent,
    _looks_like_fake_file_claim,
    _strip_tool_call_blocks,
)
from .translator import flatten_content, translate_openai_request


def register_chat_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[[Request], SubstrateCopilotClient],
) -> None:
    @app.get("/v1/models")
    async def list_models(raw_request: Request, settings: Settings = Depends(get_settings)) -> dict:
        tone_options = getattr(app.state, "tone_options", None) or []
        created = int(time.time())
        return {
            "object": "list",
            "data": build_models_list(tone_options, created),
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        raw_request: Request,
        request: OpenAIChatRequest,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        _log = logging.getLogger("copilot_proxy")
        model_alias = request_model_alias(app, raw_request, settings)
        _log.info("[/v1/chat/completions] stream=%s tools=%d messages=%d model=%s",
                  request.stream, len(request.tools) if request.tools else 0,
                  len(request.messages), request.model)
        if request.tools:
            for t in request.tools:
                _log.info("  tool: %s", t.function.name if t.function else "?")
        # Record call for web UI
        call_record = {
            "api": "chat",
            "endpoint": "/v1/chat/completions",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [t.function.name for t in request.tools] if request.tools else [],
            "messages": len(request.messages),
            "model": request.model,
            "tool_calls_result": None,
        }
        try:
            # Each tone is exposed as its own model via /v1/models, so the
            # requested model name now selects the conversation tone (and its
            # persistent variant). Override the client tone accordingly; the
            # persist marker is normalized so _persistent_session's suffix check
            # keeps working regardless of which variant the client addressed.
            resolved_tone, _is_persist = resolve_request_tone(app, request.model)
            client._tone = resolved_tone
            session = _persistent_session(app, raw_request, normalized_session_model(request.model), request.user, request)
            # Whenever we reuse a persistent M365 session that already has history
            # (both auto mode and explicit :persist mode), the server remembers the
            # prior turns — so only send the incremental turn instead of resending the
            # whole transcript on every request.
            incremental = (
                session is not None
                and session.turn_count > 0
            )
            # Diagnostics: surface in the web call-log so we can see whether the
            # incremental optimization actually kicks in across turns.
            call_record["incremental"] = incremental
            call_record["turn_count"] = session.turn_count if session is not None else None
            _key_obj = getattr(raw_request.state, "api_key_obj", None)
            call_record["tone"] = resolved_tone
            # System prompt: the key's own override wins; if the key hasn't set one,
            # fall back to the global system prompt (admin's "系统提示词（全局）").
            _key_sp = ((_key_obj.system_prompt if _key_obj is not None else "") or "").strip()
            _system_override = _key_sp or getattr(app.state, 'system_prompt', '')
            run_permission = effective_run_permission(app, _key_obj)
            read_only_guard = run_permission == "read_only" or _has_read_only_intent(*(flatten_content(m.content) for m in request.messages if m.role == "user"))
            call_record["run_permission"] = run_permission
            call_record["read_only_guard"] = read_only_guard
            translated = translate_openai_request(request, incremental=incremental, system_override=_system_override)
            media_rewriter = request_media_rewriter(app, raw_request)
            if request.stream:
                # Save call record for streaming (tool_calls_result resolved later)
                call_record["streaming"] = True
                append_call_log(app.state, call_record)
                if request.tools:
                    # When tools are present, buffer the full stream then parse tool_calls
                    return StreamingResponse(
                        _openai_stream_with_tools(
                            model_alias,
                            client,
                            translated.prompt,
                            translated.additional_context,
                            session,
                            call_log=app.state.call_log,
                            call_record=call_record,
                            tool_names={t.function.name for t in request.tools if t.function},
                            read_only_guard=read_only_guard,
                            text_transform=media_rewriter,
                            images=translated.images,
                        ),
                        media_type="text/event-stream",
                    )
                return StreamingResponse(
                    _openai_stream(
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
            # Keep the RAW model text for parsing; the media rewriter is applied
            # at delivery time below. Rewriting first base64-encodes the source
            # URL into a ?u= parameter, erasing the file extension that
            # _looks_like_fake_file_claim needs to detect a natively generated
            # file, so the corrective retry never fired. Deferring it also keeps
            # the rewriter away from a Write tool_call's file content.
            text = await client.chat(translated.prompt, translated.additional_context, session, translated.images)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # If request included tools, parse model output for tool_call blocks
        tool_calls = _extract_tool_calls(text) if request.tools else []
        if read_only_guard and tool_calls:
            blocked = len(tool_calls)
            tool_calls = _filter_read_only_tool_calls(tool_calls)
            if len(tool_calls) != blocked:
                _log.info("  read-only guard filtered mutating tool_call(s)")
        if not tool_calls and request.tools and not read_only_guard:
            # Prose fallback: model described "save as <path>" + code block
            tool_names = {t.function.name for t in request.tools if t.function}
            tool_calls = _extract_prose_write(text, tool_names)
            if tool_calls:
                _log.info("  prose fallback synthesized Write tool_call")
        # Corrective retry: M365 sometimes "creates" a file via its native
        # attachment feature (hosted URL) instead of a tool_call. If it claims a
        # file but emitted none, force one retry demanding a real tool_call.
        if not tool_calls and request.tools and not read_only_guard and _looks_like_fake_file_claim(text):
            _log.info("  fake file claim detected, forcing corrective retry")
            try:
                retry_text = await client.chat(_RETRY_INSTRUCTION, translated.additional_context, session)
                retry_calls = _extract_tool_calls(retry_text)
                if not retry_calls:
                    tool_names = {t.function.name for t in request.tools if t.function}
                    retry_calls = _extract_prose_write(retry_text, tool_names)
                if retry_calls:
                    _log.info("  retry produced %d tool_call(s)", len(retry_calls))
                    text, tool_calls = retry_text, retry_calls
                    call_record["retried"] = True
            except SubstrateCopilotError:
                pass  # Keep original response if retry fails
        _log.info("[/v1/chat/completions] response len=%d tool_calls=%d", len(text), len(tool_calls))
        if tool_calls:
            _log.info("  parsed tool_calls: %s", [tc["function"]["name"] for tc in tool_calls])
        # Save call record
        call_record["response_len"] = len(text)
        call_record["response_text"] = text[:8000]
        call_record["response_repr"] = repr(text[:2000])
        call_record["tool_calls_result"] = [tc["function"]["name"] for tc in tool_calls] if tool_calls else []
        append_call_log(app.state, call_record)
        if tool_calls:
            remaining = media_rewriter(_strip_tool_call_blocks(text))
            msg = {"role": "assistant", "content": remaining or None, "tool_calls": tool_calls}
            return JSONResponse({
                "id": f"chatcmpl_{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_alias,
                "choices": [
                    {
                        "index": 0,
                        "message": msg,
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })

        return JSONResponse({
            "id": f"chatcmpl_{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_alias,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": media_rewriter(text)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


async def _openai_stream_with_tools(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
    call_log: list | None = None,
    call_record: dict | None = None,
    tool_names: set | None = None,
    read_only_guard: bool = False,
    text_transform: Callable[[str], str] | None = None,
    images: list | None = None,
) -> AsyncIterator[str]:
    """Buffer full stream, then emit as tool_calls if found, else normal content stream."""
    _log = logging.getLogger("copilot_proxy")
    chunks: list[str] = []
    async for delta in client.chat_stream(prompt, additional_context, session, images):
        chunks.append(delta)
    # Raw text for parsing; the media rewriter runs at delivery time below. This
    # path previously never applied it at all, so media links reached streaming
    # clients unrewritten.
    full_text = "".join(chunks)

    tool_calls = _extract_tool_calls(full_text)
    if read_only_guard and tool_calls:
        blocked = len(tool_calls)
        tool_calls = _filter_read_only_tool_calls(tool_calls)
        if len(tool_calls) != blocked:
            _log.info("  read-only guard filtered mutating tool_call(s)")
    if not tool_calls and tool_names and not read_only_guard:
        # Prose fallback: model described "save as <path>" + code block
        tool_calls = _extract_prose_write(full_text, tool_names)
        if tool_calls:
            _log.info("  prose fallback synthesized Write tool_call")
    # Corrective retry: M365 native file-gen (hosted URL) instead of a tool_call.
    if not tool_calls and tool_names and not read_only_guard and _looks_like_fake_file_claim(full_text):
        _log.info("  fake file claim detected, forcing corrective retry")
        try:
            retry_chunks: list[str] = []
            async for delta in client.chat_stream(_RETRY_INSTRUCTION, additional_context, session):
                retry_chunks.append(delta)
            retry_text = "".join(retry_chunks)
            retry_calls = _extract_tool_calls(retry_text)
            if not retry_calls:
                retry_calls = _extract_prose_write(retry_text, tool_names)
            if retry_calls:
                _log.info("  retry produced %d tool_call(s)", len(retry_calls))
                full_text, tool_calls = retry_text, retry_calls
                if call_record is not None:
                    call_record["retried"] = True
        except SubstrateCopilotError:
            pass  # Keep original response if retry fails
    _log.info("[stream_with_tools] full_text len=%d tool_calls=%d", len(full_text), len(tool_calls))
    if tool_calls:
        _log.info("  parsed tool_calls: %s", [tc["function"]["name"] for tc in tool_calls])
    # Update call record with results
    if call_record is not None:
        call_record["response_len"] = len(full_text)
        call_record["response_text"] = full_text[:8000]
        call_record["response_repr"] = repr(full_text[:2000])
        call_record["tool_calls_result"] = [tc["function"]["name"] for tc in tool_calls] if tool_calls else []
    completion_id = f"chatcmpl_{uuid.uuid4().hex}"
    created = int(time.time())

    if tool_calls:
        remaining = _strip_tool_call_blocks(full_text)
        if text_transform is not None:
            remaining = text_transform(remaining)
        # Emit role chunk
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
        # Emit remaining text content if any
        if remaining:
            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'content': remaining}, 'finish_reason': None}]})}\n\n"
        # Emit tool_calls chunks — one per tool call
        for i, tc in enumerate(tool_calls):
            delta_tc = [{"index": i, "id": tc["id"], "type": "function", "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}]
            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'tool_calls': delta_tc}, 'finish_reason': None}]})}\n\n"
        # Final chunk with finish_reason
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})}\n\n"
        yield "data: [DONE]\n\n"
    else:
        # No tool calls found — re-stream as normal content
        delivered = text_transform(full_text) if text_transform is not None else full_text
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'content': delivered}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"
