from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator, Callable

from fastapi.responses import JSONResponse

from .session_store import PersistentSession
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError, _dedupe_repeated_delta


def _transform_complete_text(full_text: str, text_transform: Callable[[str], str] | None) -> str:
    return text_transform(full_text) if text_transform is not None else full_text


def _json_err(status: int, message: str, error_type: str = "error") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": error_type}},
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def _openai_stream(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
    on_text_done: Callable[[str], None] | None = None,
    text_transform: Callable[[str], str] | None = None,
    images: list | None = None,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl_{uuid.uuid4().hex}"
    created = int(time.time())
    first_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_alias,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(first_chunk)}\n\n"
    raw_text = ""
    full_text = ""
    try:
        async for delta in client.chat_stream(prompt, additional_context, session, images):
            delta = _dedupe_repeated_delta(raw_text, delta)
            if not delta:
                continue
            raw_text += delta
            if text_transform is not None:
                continue
            full_text += delta
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_alias,
                "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
    except SubstrateCopilotError as exc:
        yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'upstream_error'}})}\n\n"
        yield "data: [DONE]\n\n"
        return
    if text_transform is not None:
        full_text = _transform_complete_text(raw_text, text_transform)
        if full_text:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_alias,
                "choices": [{"index": 0, "delta": {"content": full_text}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
    if on_text_done is not None:
        on_text_done(full_text)
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_alias,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


async def _responses_stream(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
    on_text_done: Callable[[str], None] | None = None,
    text_transform: Callable[[str], str] | None = None,
    response_id: str | None = None,
    images: list | None = None,
) -> AsyncIterator[str]:
    resp_id = response_id or f"resp_{uuid.uuid4().hex}"
    item_id = f"msg_{uuid.uuid4().hex}"
    created = int(time.time())

    yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': resp_id, 'object': 'response', 'created_at': created, 'model': model_alias, 'status': 'in_progress', 'output': []}})}\n\n"
    yield f"data: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': {'id': item_id, 'type': 'message', 'role': 'assistant', 'content': []}})}\n\n"
    yield f"data: {json.dumps({'type': 'response.content_part.added', 'item_id': item_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': ''}})}\n\n"

    raw_text = ""
    full_text = ""
    try:
        async for delta in client.chat_stream(prompt, additional_context, session, images):
            delta = _dedupe_repeated_delta(raw_text, delta)
            if not delta:
                continue
            raw_text += delta
            if text_transform is not None:
                continue
            full_text += delta
            yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': item_id, 'output_index': 0, 'content_index': 0, 'delta': delta})}\n\n"
    except SubstrateCopilotError as exc:
        # Emit both the out-of-band `error` event (kept for existing clients) and
        # the semantic `response.failed` envelope. Responses API does NOT use a
        # `[DONE]` sentinel; `response.failed` is the terminal event that lets
        # strict clients stop cleanly instead of hanging for more deltas.
        yield f"data: {json.dumps({'type': 'error', 'error': {'message': str(exc), 'type': 'upstream_error'}})}\n\n"
        yield f"data: {json.dumps({'type': 'response.failed', 'response': {'id': resp_id, 'object': 'response', 'created_at': created, 'model': model_alias, 'status': 'failed', 'error': {'message': str(exc), 'code': 'upstream_error'}}})}\n\n"
        return

    if text_transform is not None:
        full_text = _transform_complete_text(raw_text, text_transform)
        if full_text:
            yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': item_id, 'output_index': 0, 'content_index': 0, 'delta': full_text})}\n\n"
    if on_text_done is not None:
        on_text_done(full_text)
    yield f"data: {json.dumps({'type': 'response.output_text.done', 'item_id': item_id, 'output_index': 0, 'content_index': 0, 'text': full_text})}\n\n"
    yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': resp_id, 'object': 'response', 'created_at': created, 'model': model_alias, 'status': 'completed', 'output': [{'id': item_id, 'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': full_text}]}], 'usage': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}})}\n\n"


async def _anthropic_stream(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
    on_text_done: Callable[[str], None] | None = None,
    text_transform: Callable[[str], str] | None = None,
    images: list | None = None,
) -> AsyncIterator[str]:
    msg_id = f"msg_{uuid.uuid4().hex}"

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    yield sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant", "content": [], "model": model_alias, "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})
    yield sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
    yield sse("ping", {"type": "ping"})

    raw_text = ""
    full_text = ""
    try:
        async for delta in client.chat_stream(prompt, additional_context, session, images):
            delta = _dedupe_repeated_delta(raw_text, delta)
            if not delta:
                continue
            raw_text += delta
            if text_transform is not None:
                continue
            full_text += delta
            yield sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": delta}})
    except SubstrateCopilotError as exc:
        yield sse("error", {"type": "error", "error": {"type": "upstream_error", "message": str(exc)}})
        return

    if text_transform is not None:
        full_text = _transform_complete_text(raw_text, text_transform)
        if full_text:
            yield sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": full_text}})
    if on_text_done is not None:
        on_text_done(full_text)
    yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 0}})
    yield sse("message_stop", {"type": "message_stop"})
