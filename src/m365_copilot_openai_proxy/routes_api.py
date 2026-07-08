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
from .key_store import ApiKey
from .models import AnthropicMessagesRequest, OpenAIChatRequest, OpenAIResponsesRequest
from .response_helpers import _anthropic_stream, _openai_stream, _responses_stream
from .routes_media_proxy import request_media_rewriter
from .runtime_settings import _RUN_PERMISSIONS
from .session_helpers import (
    _PERSIST_MODEL_SUFFIX,
    _messages_session_key,
    _persistent_session,
    _responses_session_key,
)
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
from .translator import (
    flatten_content,
    translate_anthropic_request,
    translate_openai_request,
    translate_responses_request,
)


def register_api_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[[Request], SubstrateCopilotClient],
) -> None:
    def _request_model_alias(raw_request: Request, settings: Settings) -> str:
        key_obj = getattr(raw_request.state, "api_key_obj", None)
        return getattr(key_obj, "model_alias", "") or getattr(app.state, "model_alias", settings.model_alias)

    def _effective_run_permission(k: ApiKey | None) -> str:
        value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
        return value if value in _RUN_PERMISSIONS else getattr(app.state, "run_permission", "full")

    @app.get("/v1/models")
    async def list_models(raw_request: Request, settings: Settings = Depends(get_settings)) -> dict:
        model_alias = _request_model_alias(raw_request, settings)
        return {
            "object": "list",
            "data": [
                {
                    "id": model_alias,
                    "object": "model",
                    "owned_by": "microsoft-365-copilot",
                },
                {
                    "id": f"{model_alias}{_PERSIST_MODEL_SUFFIX}",
                    "object": "model",
                    "owned_by": "microsoft-365-copilot",
                },
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        raw_request: Request,
        request: OpenAIChatRequest,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        _log = logging.getLogger("copilot_proxy")
        model_alias = _request_model_alias(raw_request, settings)
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
            session = _persistent_session(app, raw_request, request.model, request.user, request)
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
            call_record["tone"] = (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic'
            # System prompt: the key's own override wins; if the key hasn't set one,
            # fall back to the global system prompt (admin's "系统提示词（全局）").
            _key_sp = ((_key_obj.system_prompt if _key_obj is not None else "") or "").strip()
            _system_override = _key_sp or getattr(app.state, 'system_prompt', '')
            run_permission = _effective_run_permission(_key_obj)
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
                    ),
                    media_type="text/event-stream",
                )
            text = media_rewriter(await client.chat(translated.prompt, translated.additional_context, session))
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
                retry_text = media_rewriter(await client.chat(_RETRY_INSTRUCTION, translated.additional_context, session))
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
            remaining = _strip_tool_call_blocks(text)
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
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    @app.post("/v1/responses")
    async def openai_responses(
        raw: Request,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        model_alias = _request_model_alias(raw, settings)
        body = await raw.json()
        try:
            request = OpenAIResponsesRequest.model_validate(body)
            translated = translate_responses_request(request)
            session = _persistent_session(app, raw, request.model, _responses_session_key(request))
            media_rewriter = request_media_rewriter(app, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _key_obj = getattr(raw.state, "api_key_obj", None)
        call_record = {
            "api": "responses",
            "endpoint": "/v1/responses",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [],
            "messages": len(request.input) if isinstance(request.input, list) else 1,
            "model": request.model,
            "tone": (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic',
            "tool_calls_result": None if request.stream else [],
        }

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            return StreamingResponse(
                _responses_stream(
                    model_alias,
                    client,
                    translated.prompt,
                    translated.additional_context,
                    session,
                    on_text_done=lambda text: record_response_text(app.state, call_record, text),
                    text_transform=media_rewriter,
                ),
                media_type="text/event-stream",
            )

        try:
            text = media_rewriter(await client.chat(translated.prompt, translated.additional_context, session))
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        record_response_text(app.state, call_record, text)
        append_call_log(app.state, call_record)

        return JSONResponse({
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "created_at": int(time.time()),
            "model": model_alias,
            "output": [{
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        })

    @app.post("/v1/messages")
    async def anthropic_messages(
        raw_request: Request,
        request: AnthropicMessagesRequest,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        model_alias = _request_model_alias(raw_request, settings)
        try:
            translated = translate_anthropic_request(request)
            session = _persistent_session(app, raw_request, request.model, _messages_session_key(request), request)
            media_rewriter = request_media_rewriter(app, raw_request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _key_obj = getattr(raw_request.state, "api_key_obj", None)
        call_record = {
            "api": "anthropic",
            "endpoint": "/v1/messages",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [],
            "messages": len(request.messages),
            "model": request.model,
            "tone": (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic',
            "tool_calls_result": None if request.stream else [],
        }

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            return StreamingResponse(
                _anthropic_stream(
                    model_alias,
                    client,
                    translated.prompt,
                    translated.additional_context,
                    session,
                    on_text_done=lambda text: record_response_text(app.state, call_record, text),
                    text_transform=media_rewriter,
                ),
                media_type="text/event-stream",
            )

        try:
            text = media_rewriter(await client.chat(translated.prompt, translated.additional_context, session))
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        record_response_text(app.state, call_record, text)
        append_call_log(app.state, call_record)

        return JSONResponse({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": model_alias,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
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
) -> AsyncIterator[str]:
    """Buffer full stream, then emit as tool_calls if found, else normal content stream."""
    _log = logging.getLogger("copilot_proxy")
    chunks: list[str] = []
    async for delta in client.chat_stream(prompt, additional_context, session):
        chunks.append(delta)
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
            if text_transform is not None:
                retry_text = text_transform(retry_text)
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
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'content': full_text}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"
